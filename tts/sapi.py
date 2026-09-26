"""Offline Windows SAPI text-to-speech backend."""

from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import time

import numpy as np
import resampy
import soundfile as sf

from registry import register
from tts.base_tts import BaseTTS, State
from utils.logger import logger


@register("tts", "sapi")
class SapiTTS(BaseTTS):
    """Use the Windows-installed SAPI voice without an API key or network."""

    def txt_to_audio(self, msg: tuple[str, dict]):
        text, text_event = msg
        script = Path(__file__).with_name("sapi_synthesize.ps1")
        voice = str(getattr(self.opt, "REF_FILE", "") or "")
        # Edge voice identifiers are not Windows SAPI display names.
        if voice.endswith("Neural"):
            voice = ""

        started = time.time()
        with tempfile.TemporaryDirectory(prefix="livetalking-sapi-") as temp_dir:
            temp_path = Path(temp_dir)
            text_path = temp_path / "input.txt"
            output_path = temp_path / "speech.wav"
            text_path.write_text(text, encoding="utf-8")
            command = [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-TextPath",
                str(text_path),
                "-OutputPath",
                str(output_path),
            ]
            if voice:
                command.extend(["-Voice", voice])
            subprocess.run(command, check=True, capture_output=True, text=True)
            stream, sample_rate = sf.read(str(output_path), dtype="float32")

        if stream.ndim > 1:
            stream = stream[:, 0]
        if sample_rate != self.sample_rate and stream.shape[0] > 0:
            stream = resampy.resample(
                x=stream, sr_orig=sample_rate, sr_new=self.sample_rate
            ).astype(np.float32)

        stream_len = stream.shape[0]
        index = 0
        while stream_len >= self.chunk and self.state == State.RUNNING:
            event_point = {}
            stream_len -= self.chunk
            if index == 0:
                event_point = {"status": "start", "text": text}
            elif stream_len < self.chunk:
                event_point = {"status": "end", "text": text}
            event_point.update(**text_event)
            self.parent.put_audio_frame(stream[index:index + self.chunk], event_point)
            index += self.chunk
        logger.info("Windows SAPI TTS time: %.4fs", time.time() - started)
