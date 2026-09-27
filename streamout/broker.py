"""In-memory MPEG-TS output used by remote OBS relay clients."""

from __future__ import annotations

from dataclasses import dataclass, field
import queue
from threading import RLock
import time

import av

from registry import register
from streamout.obs import OBSOutput


@dataclass
class StreamBroadcast:
    session_id: str
    _subscribers: set[queue.Queue] = field(default_factory=set)
    _lock: RLock = field(default_factory=RLock)

    def subscribe(self, max_chunks: int = 2048) -> queue.Queue:
        subscriber: queue.Queue = queue.Queue(maxsize=max_chunks)
        with self._lock:
            self._subscribers.add(subscriber)
        return subscriber

    def unsubscribe(self, subscriber: queue.Queue) -> None:
        with self._lock:
            self._subscribers.discard(subscriber)

    def publish(self, payload: bytes) -> None:
        if not payload:
            return
        with self._lock:
            subscribers = tuple(self._subscribers)
        for subscriber in subscribers:
            try:
                subscriber.put_nowait(payload)
            except queue.Full:
                # Keep the live edge. FFmpeg/OBS will recover on the next IDR
                # because the MPEG-TS encoder resends headers regularly.
                try:
                    subscriber.get_nowait()
                except queue.Empty:
                    pass
                try:
                    subscriber.put_nowait(payload)
                except queue.Full:
                    pass

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)


class BroadcastRegistry:
    def __init__(self):
        self._streams: dict[str, StreamBroadcast] = {}
        self._lock = RLock()

    def get(self, session_id: str) -> StreamBroadcast:
        with self._lock:
            return self._streams.setdefault(
                session_id, StreamBroadcast(session_id=session_id)
            )

    def remove(self, session_id: str) -> None:
        with self._lock:
            self._streams.pop(session_id, None)


broadcast_registry = BroadcastRegistry()


class _BroadcastSink:
    """Minimal writable object accepted by PyAV's MPEG-TS muxer."""

    def __init__(self, broadcast: StreamBroadcast):
        self.broadcast = broadcast
        self.closed = False
        self.position = 0

    def write(self, payload) -> int:
        data = bytes(payload)
        self.broadcast.publish(data)
        self.position += len(data)
        return len(data)

    def flush(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True

    def writable(self) -> bool:
        return True

    def readable(self) -> bool:
        return False

    def seekable(self) -> bool:
        return False

    def tell(self) -> int:
        return self.position


@register("streamout", "broker")
class BrokerOutput(OBSOutput):
    """Encode one session as MPEG-TS and fan it out to HTTP subscribers."""

    def __init__(self, opt=None, parent=None, **kwargs):
        super().__init__(opt=opt, parent=parent, **kwargs)
        self.session_id = str(getattr(opt, "sessionid", "0"))
        self.broadcast = broadcast_registry.get(self.session_id)
        self.push_url = f"broker://{self.session_id}"
        self._mux_url = self.push_url
        self._sink = None
        self._without_subscriber_since = None

    def _create_container(self, output_format: str, container_options: dict):
        self._sink = _BroadcastSink(self.broadcast)
        return av.open(
            self._sink,
            mode="w",
            format="mpegts",
            options=container_options,
        )

    def push_video_frame(self, frame) -> None:
        if self.broadcast.subscriber_count == 0:
            now = time.perf_counter()
            self._without_subscriber_since = (
                self._without_subscriber_since or now
            )
            if (
                self._container is not None
                and now - self._without_subscriber_since >= 1.0
            ):
                self._reset_output()
                self._retry_at = 0.0
            time.sleep(1 / self.fps)
            return
        self._without_subscriber_since = None
        super().push_video_frame(frame)

    def push_audio_frame(self, frame, eventpoint=None) -> None:
        if self.broadcast.subscriber_count == 0:
            self._pending_audio.clear()
            return
        super().push_audio_frame(frame, eventpoint)
