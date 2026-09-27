"""FIFO multi-client speech broker for GPU-backed avatar sessions."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
from io import BytesIO
import json
from pathlib import Path
import re
import subprocess
import sys
from threading import Event, Thread
import time
import uuid

import soundfile as sf

from server.session_manager import session_manager
from streamout.broker import broadcast_registry
from utils.logger import logger


SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def validate_id(value: str, label: str) -> str:
    value = str(value or "").strip()
    if not SAFE_ID.fullmatch(value):
        raise ValueError(
            f"{label} must contain 1-64 letters, numbers, '-' or '_', "
            "and must start with a letter or number"
        )
    return value


@dataclass
class ClientProfile:
    client_id: str
    avatar_id: str
    voice_id: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


@dataclass
class SpeechJob:
    job_id: str
    client_id: str
    text: str
    status: str = "queued"
    error: str = ""
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    completed_at: float | None = None


class BrokerService:
    """Own profiles, one global FIFO queue and per-client render sessions."""

    def __init__(self, root: Path | str = "."):
        self.root = Path(root).resolve()
        self.state_dir = self.root / "data" / "broker"
        self.voice_dir = self.root / "data" / "voices" / "broker"
        self.profile_file = self.state_dir / "clients.json"
        self.profiles: dict[str, ClientProfile] = {}
        self.jobs: dict[str, SpeechJob] = {}
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self._session_locks: dict[str, asyncio.Lock] = {}
        self._managed_sessions: set[str] = set()
        self._worker_task: asyncio.Task | None = None
        self._load_profiles()

    @staticmethod
    def session_id(client_id: str) -> str:
        return f"broker-{client_id}"

    def _load_profiles(self) -> None:
        if not self.profile_file.is_file():
            return
        try:
            payload = json.loads(self.profile_file.read_text(encoding="utf-8"))
            for item in payload.get("clients", []):
                profile = ClientProfile(**item)
                self.profiles[profile.client_id] = profile
        except Exception:
            logger.exception("Could not load broker client profiles")

    def _save_profiles(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.profile_file.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(
                {"clients": [asdict(item) for item in self.profiles.values()]},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.profile_file)

    def start(self) -> None:
        if self._worker_task is None:
            self._worker_task = asyncio.create_task(
                self._worker(), name="broker-fifo-worker"
            )
            logger.info("Multi-client FIFO broker started")

    async def stop(self) -> None:
        task = self._worker_task
        self._worker_task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        for session_id in tuple(self._managed_sessions):
            session_manager.remove_session(session_id)
            broadcast_registry.remove(session_id)
        self._managed_sessions.clear()

    def list_profiles(self) -> list[dict]:
        return [asdict(item) for item in self.profiles.values()]

    def get_profile(self, client_id: str) -> ClientProfile:
        client_id = validate_id(client_id, "client_id")
        profile = self.profiles.get(client_id)
        if profile is None:
            raise KeyError(f"Client profile not found: {client_id}")
        return profile

    def upsert_profile(
        self, client_id: str, avatar_id: str, voice_id: str = ""
    ) -> ClientProfile:
        client_id = validate_id(client_id, "client_id")
        avatar_id = validate_id(avatar_id, "avatar_id")
        voice_id = validate_id(voice_id, "voice_id") if voice_id else ""
        avatar_dir = self.root / "data" / "avatars" / avatar_id
        if not avatar_dir.is_dir():
            raise ValueError(f"Avatar does not exist on server: {avatar_id}")
        if voice_id and not self.voice_metadata_path(voice_id).is_file():
            raise ValueError(f"Voice does not exist on server: {voice_id}")
        self._assert_client_idle(client_id)

        previous = self.profiles.get(client_id)
        now = time.time()
        profile = ClientProfile(
            client_id=client_id,
            avatar_id=avatar_id,
            voice_id=voice_id,
            created_at=previous.created_at if previous else now,
            updated_at=now,
        )
        self.profiles[client_id] = profile
        self._save_profiles()
        if previous and (
            previous.avatar_id != avatar_id or previous.voice_id != voice_id
        ):
            self.remove_session(client_id)
        return profile

    def delete_profile(self, client_id: str) -> None:
        profile = self.get_profile(client_id)
        self._assert_client_idle(profile.client_id)
        self.remove_session(profile.client_id)
        self.profiles.pop(profile.client_id, None)
        self._save_profiles()

    def voice_audio_path(self, voice_id: str) -> Path:
        return self.voice_dir / f"{voice_id}.wav"

    def voice_metadata_path(self, voice_id: str) -> Path:
        return self.voice_dir / f"{voice_id}.json"

    def save_voice(self, voice_id: str, payload: bytes, ref_text: str) -> dict:
        voice_id = validate_id(voice_id, "voice_id")
        for profile in self.profiles.values():
            if profile.voice_id == voice_id:
                self._assert_client_idle(profile.client_id)
        transcript = str(ref_text or "").strip()
        if not payload:
            raise ValueError("Voice reference is empty")
        self.voice_dir.mkdir(parents=True, exist_ok=True)
        audio_path = self.voice_audio_path(voice_id)

        if not transcript:
            source = self.voice_dir / f".{voice_id}-{uuid.uuid4().hex}.wav"
            text_path = self.voice_dir / f"{voice_id}.txt"
            prepare_meta = self.voice_dir / f"{voice_id}.prepare.json"
            source.write_bytes(payload)
            try:
                subprocess.run(
                    [
                        sys.executable,
                        str(self.root / "tools" / "prepare_voice_clone.py"),
                        str(source),
                        "--audio-output", str(audio_path),
                        "--text-output", str(text_path),
                        "--metadata-output", str(prepare_meta),
                        "--asr-model", "vinai/PhoWhisper-medium",
                        "--force",
                    ],
                    cwd=self.root,
                    check=True,
                )
                payload = audio_path.read_bytes()
                transcript = text_path.read_text(encoding="utf-8").strip()
            finally:
                source.unlink(missing_ok=True)

        try:
            audio_info = sf.info(BytesIO(payload))
        except Exception as exc:
            raise ValueError(f"Invalid WAV reference: {exc}") from exc
        duration = audio_info.frames / audio_info.samplerate
        if duration < 3.0 or duration > 30.0:
            raise ValueError("Voice reference duration must be between 3 and 30 seconds")
        audio_tmp = audio_path.with_suffix(".wav.tmp")
        metadata_path = self.voice_metadata_path(voice_id)
        metadata_tmp = metadata_path.with_suffix(".json.tmp")
        write_audio = (
            not audio_path.is_file() or audio_path.read_bytes() != payload
        )
        if write_audio:
            audio_tmp.write_bytes(payload)
        metadata = {
            "voice_id": voice_id,
            "audio": str(audio_path),
            "ref_text": transcript,
            "duration_seconds": round(duration, 3),
            "sample_rate": audio_info.samplerate,
            "channels": audio_info.channels,
            "updated_at": time.time(),
        }
        metadata_tmp.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        if audio_tmp.exists():
            audio_tmp.replace(audio_path)
        metadata_tmp.replace(metadata_path)
        for profile in tuple(self.profiles.values()):
            if profile.voice_id == voice_id:
                self.remove_session(profile.client_id)
        return metadata

    def get_voice(self, voice_id: str) -> dict:
        voice_id = validate_id(voice_id, "voice_id")
        path = self.voice_metadata_path(voice_id)
        if not path.is_file():
            raise KeyError(f"Voice not found: {voice_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def list_voices(self) -> list[dict]:
        if not self.voice_dir.is_dir():
            return []
        voices = []
        for path in sorted(self.voice_dir.glob("*.json")):
            if path.name.endswith(".prepare.json"):
                continue
            try:
                voices.append(json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                logger.warning("Ignoring invalid voice metadata: %s", path)
        return voices

    def list_avatars(self) -> list[str]:
        directory = self.root / "data" / "avatars"
        if not directory.is_dir():
            return []
        return sorted(item.name for item in directory.iterdir() if item.is_dir())

    def submit(self, client_id: str, text: str) -> SpeechJob:
        profile = self.get_profile(client_id)
        speech = str(text or "").strip()
        if not speech:
            raise ValueError("text is required")
        if len(speech) > 4000:
            raise ValueError("text exceeds the 4000 character limit")
        job = SpeechJob(
            job_id=str(uuid.uuid4()), client_id=profile.client_id, text=speech
        )
        self.jobs[job.job_id] = job
        if len(self.jobs) > 5000:
            completed = sorted(
                (
                    item
                    for item in self.jobs.values()
                    if item.status in {"completed", "failed"}
                ),
                key=lambda item: item.completed_at or item.created_at,
            )
            for stale in completed[:1000]:
                self.jobs.pop(stale.job_id, None)
        self.queue.put_nowait(job.job_id)
        return job

    def _assert_client_idle(self, client_id: str) -> None:
        session_id = self.session_id(client_id)
        if broadcast_registry.get(session_id).subscriber_count > 0:
            raise ValueError(
                f"Client {client_id} is connected; stop its OBS relay before "
                "changing the avatar or voice"
            )
        busy = any(
            job.client_id == client_id
            and job.status in {"queued", "waiting_client", "running"}
            for job in self.jobs.values()
        )
        if busy:
            raise ValueError(
                f"Client {client_id} has queued/running jobs; wait before "
                "changing its avatar or voice"
            )

    def get_job(self, job_id: str) -> SpeechJob:
        job = self.jobs.get(str(job_id))
        if job is None:
            raise KeyError(f"Job not found: {job_id}")
        return job

    def status(self) -> dict:
        queued = sum(
            job.status in {"queued", "waiting_client"}
            for job in self.jobs.values()
        )
        running = [asdict(job) for job in self.jobs.values() if job.status == "running"]
        return {
            "queued": queued,
            "running": running,
            "clients": len(self.profiles),
            "active_sessions": len(self._managed_sessions),
        }

    def _session_params(self, profile: ClientProfile) -> dict:
        params = {"avatar": profile.avatar_id}
        if profile.voice_id:
            voice = self.get_voice(profile.voice_id)
            params.update(
                {
                    "refaudio": str(self.voice_audio_path(profile.voice_id).resolve()),
                    "reftext": voice["ref_text"],
                }
            )
        return params

    async def ensure_session(self, client_id: str):
        profile = self.get_profile(client_id)
        session_id = self.session_id(profile.client_id)
        current = session_manager.get_session(session_id)
        if current is not None:
            return current
        lock = self._session_locks.setdefault(profile.client_id, asyncio.Lock())
        async with lock:
            current = session_manager.get_session(session_id)
            if current is not None:
                return current
            await session_manager.create_session(
                self._session_params(profile), sessionid=session_id
            )
            avatar = session_manager.get_session(session_id)
            quit_event = Event()
            thread = Thread(
                target=avatar.render,
                args=(quit_event,),
                daemon=True,
                name=f"broker-render-{profile.client_id}",
            )
            avatar.quit_event = quit_event
            avatar._broker_render_thread = thread
            thread.start()
            self._managed_sessions.add(session_id)
            logger.info(
                "Broker session ready: client=%s avatar=%s voice=%s",
                profile.client_id,
                profile.avatar_id,
                profile.voice_id or "default",
            )
            return avatar

    def remove_session(self, client_id: str) -> None:
        session_id = self.session_id(client_id)
        session_manager.remove_session(session_id)
        broadcast_registry.remove(session_id)
        self._managed_sessions.discard(session_id)

    async def _worker(self) -> None:
        while True:
            job_id = await self.queue.get()
            job = self.jobs.get(job_id)
            if job is None:
                self.queue.task_done()
                continue
            try:
                job.status = "waiting_client"
                await self._wait_for_client(job.client_id)
                job.status = "running"
                job.started_at = time.time()
                avatar = await self.ensure_session(job.client_id)
                avatar.put_msg_txt(
                    job.text,
                    {"source": "broker", "job_id": job.job_id},
                )
                await self._wait_for_speech(avatar, job)
                job.status = "completed"
                job.completed_at = time.time()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                job.status = "failed"
                job.error = str(exc)
                job.completed_at = time.time()
                logger.exception("Broker speech job failed: %s", job.job_id)
            finally:
                self.queue.task_done()

    async def _wait_for_client(self, client_id: str) -> None:
        session_id = self.session_id(client_id)
        broadcast = broadcast_registry.get(session_id)
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            if broadcast.subscriber_count > 0:
                return
            await asyncio.sleep(0.1)
        raise TimeoutError(
            f"OBS client {client_id} is not connected to its stream"
        )

    async def _wait_for_speech(self, avatar, job: SpeechJob) -> None:
        deadline = time.monotonic() + max(180.0, len(job.text) * 1.5)
        started = False
        quiet_since = None
        while time.monotonic() < deadline:
            speaking = bool(avatar.is_speaking())
            if speaking:
                started = True
                quiet_since = None
            elif started:
                quiet_since = quiet_since or time.monotonic()
                if time.monotonic() - quiet_since >= 0.6:
                    return
            await asyncio.sleep(0.05)
        if not started:
            raise TimeoutError("TTS/lip-sync did not start before timeout")
        raise TimeoutError("TTS/lip-sync did not finish before timeout")
