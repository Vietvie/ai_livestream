from __future__ import annotations

from dataclasses import asdict, dataclass, field
from itertools import count
from queue import Empty, PriorityQueue
from threading import Event, Lock, Thread
from typing import Any
import time

from livestream.openai_agent import OpenAIProductAgent
from livestream.scripts import ScriptStore
from livestream.settings import LivestreamSettings
from utils.logger import logger


@dataclass(order=True)
class QueueItem:
    priority: int
    sequence: int
    kind: str = field(compare=False)
    session_id: str = field(compare=False)
    text: str = field(compare=False, default="")
    external_id: str = field(compare=False, default="")
    interrupt: bool = field(compare=False, default=False)
    metadata: dict[str, Any] = field(compare=False, default_factory=dict)


class LivestreamOrchestrator:
    def __init__(self, settings: LivestreamSettings, agent: OpenAIProductAgent, scripts: ScriptStore, session_manager):
        self.settings = settings
        self.agent = agent
        self.scripts = scripts
        self.session_manager = session_manager
        self.queue: PriorityQueue[QueueItem] = PriorityQueue()
        self._sequence = count()
        self._stop = Event()
        self._paused = Event()
        self._threads: list[Thread] = []
        self._lock = Lock()
        self._last_activity: dict[str, float] = {
            settings.automation.default_session_id: time.monotonic()
        }
        self._last_error = ""
        self._active: QueueItem | None = None
        self._seen_ids: dict[str, float] = {}

    def start(self) -> None:
        if self._threads:
            return
        self._threads = [
            Thread(target=self._worker, daemon=True, name="livestream-worker"),
            Thread(target=self._idle_loop, daemon=True, name="livestream-idle"),
        ]
        for thread in self._threads:
            thread.start()
        logger.info("Livestream orchestrator started")

    def stop(self) -> None:
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout=3)
        self._threads = []

    def pause(self) -> None:
        self._paused.set()

    def resume(self) -> None:
        self._paused.clear()
        self._touch(self.settings.automation.default_session_id)

    def submit_comment(
        self,
        text: str,
        session_id: str | None = None,
        external_id: str = "",
        interrupt: bool | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        if not text.strip():
            raise ValueError("Comment text cannot be empty")
        if external_id and self._is_duplicate(external_id):
            return False
        session_id = session_id or self.settings.automation.default_session_id
        should_interrupt = (
            self.settings.automation.interrupt_idle_on_comment if interrupt is None else interrupt
        )
        self._enqueue("comment", session_id, text, 0, external_id, should_interrupt, metadata)
        return True

    def submit_speech(
        self,
        text: str,
        session_id: str | None = None,
        interrupt: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if not text.strip():
            raise ValueError("Speech text cannot be empty")
        self._enqueue(
            "speech",
            session_id or self.settings.automation.default_session_id,
            text,
            1,
            "",
            interrupt,
            metadata,
        )

    def trigger_script(self, script_id: str, session_id: str | None = None) -> None:
        script = self.scripts.get(script_id)
        if script is None:
            raise KeyError(f"Script not found: {script_id}")
        self._enqueue(
            "script",
            session_id or self.settings.automation.default_session_id,
            script.text,
            5,
            "",
            False,
            {
                "script_id": script.id,
                "mode": script.mode,
                "audiotype": script.audiotype,
            },
        )

    def llm_response(self, message, avatar_session, datainfo=None):
        """Drop-in replacement for LiveTalking's legacy /human chat callback."""
        session_id = str(getattr(avatar_session, "sessionid", "0"))
        self._touch(session_id)
        try:
            return self.agent.reply(
                str(message),
                session_id,
                lambda phrase: avatar_session.put_msg_txt(phrase, datainfo or {}),
            )
        except Exception as exc:
            self._set_error(exc)
            logger.exception("OpenAI livestream response failed")
            avatar_session.put_msg_txt(
                "Xin lỗi, hệ thống tư vấn đang tạm thời gián đoạn. Bạn vui lòng thử lại sau.",
                datainfo or {},
            )
            return ""

    def status(self) -> dict[str, Any]:
        with self._lock:
            active = asdict(self._active) if self._active else None
            last_error = self._last_error
        return {
            "running": bool(self._threads) and not self._stop.is_set(),
            "paused": self._paused.is_set(),
            "queue_size": self.queue.qsize(),
            "active": active,
            "last_error": last_error,
            "default_session_id": self.settings.automation.default_session_id,
            "scripts": self.scripts.list(),
        }

    def _enqueue(self, kind, session_id, text, priority, external_id, interrupt, metadata):
        self._touch(session_id)
        self.queue.put(
            QueueItem(
                priority=priority,
                sequence=next(self._sequence),
                kind=kind,
                session_id=str(session_id),
                text=text.strip(),
                external_id=external_id,
                interrupt=interrupt,
                metadata=metadata or {},
            )
        )

    def _worker(self) -> None:
        while not self._stop.is_set():
            if self._paused.is_set():
                self._stop.wait(0.25)
                continue
            try:
                item = self.queue.get(timeout=0.5)
            except Empty:
                continue
            try:
                with self._lock:
                    self._active = item
                avatar = self.session_manager.get_session(item.session_id)
                if avatar is None:
                    raise RuntimeError(f"Avatar session not found: {item.session_id}")
                if item.interrupt:
                    avatar.flush_talk()
                audiotype = item.metadata.get("audiotype")
                if audiotype is not None and hasattr(avatar, "set_custom_state"):
                    avatar.set_custom_state(int(audiotype))
                if item.kind == "comment" or (
                    item.kind == "script" and item.metadata.get("mode") == "generate"
                ):
                    self.agent.reply(
                        item.text,
                        item.session_id,
                        lambda phrase: avatar.put_msg_txt(phrase, {"source": item.kind, **item.metadata}),
                    )
                else:
                    avatar.put_msg_txt(item.text, {"source": item.kind, **item.metadata})
                self._touch(item.session_id)
            except Exception as exc:
                self._set_error(exc)
                logger.exception("Livestream work item failed: %s", item.kind)
            finally:
                with self._lock:
                    self._active = None
                self.queue.task_done()

    def _idle_loop(self) -> None:
        cfg = self.settings.automation
        while not self._stop.wait(max(0.1, cfg.poll_seconds)):
            if not cfg.enabled or self._paused.is_set() or not self.queue.empty():
                continue
            session_id = cfg.default_session_id
            avatar = self.session_manager.get_session(session_id)
            if avatar is None or avatar.is_speaking():
                continue
            last = self._last_activity.get(session_id, time.monotonic())
            if time.monotonic() - last < cfg.idle_seconds:
                continue
            script = self.scripts.next()
            if script:
                self._enqueue(
                    "script",
                    session_id,
                    script.text,
                    9,
                    "",
                    False,
                    {
                        "script_id": script.id,
                        "mode": script.mode,
                        "audiotype": script.audiotype,
                    },
                )

    def _touch(self, session_id: str) -> None:
        self._last_activity[str(session_id)] = time.monotonic()

    def _set_error(self, exc: Exception) -> None:
        with self._lock:
            self._last_error = f"{type(exc).__name__}: {exc}"

    def _is_duplicate(self, external_id: str) -> bool:
        now = time.monotonic()
        cutoff = now - 3600
        self._seen_ids = {key: ts for key, ts in self._seen_ids.items() if ts >= cutoff}
        if external_id in self._seen_ids:
            return True
        self._seen_ids[external_id] = now
        return False
