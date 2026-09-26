"""Frame-paced sink used for headless MP4 recording tests."""

from __future__ import annotations

import time

from registry import register
from streamout.base_output import BaseOutput
from utils.logger import logger


@register("streamout", "null")
class NullOutput(BaseOutput):
    """Discard output frames while preserving realtime pacing and events.

    BaseAvatar still passes every frame to its recorder, so this transport is
    ideal for validating TTS + lip-sync + MP4 generation without OBS/SRS.
    """

    def __init__(self, opt=None, parent=None, **kwargs):
        super().__init__(opt, parent)
        self.fps = max(1, int(getattr(opt, "fps", 25)))
        self._frame_index = 0
        self._started_at = 0.0

    def start(self) -> None:
        self._frame_index = 0
        self._started_at = time.perf_counter()
        logger.info("Null output started at %s fps", self.fps)

    def push_video_frame(self, frame) -> None:
        target = self._started_at + self._frame_index / self.fps
        delay = target - time.perf_counter()
        if delay > 0:
            time.sleep(delay)
        self._frame_index += 1

    def push_audio_frame(self, frame, eventpoint=None) -> None:
        if self.parent:
            self.parent.notify(eventpoint)

    def stop(self) -> None:
        logger.info("Null output stopped")
