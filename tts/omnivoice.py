"""Local OmniVoice text-to-speech backend.

The model is loaded lazily with the official ``omnivoice`` Python package and
kept in memory for the lifetime of the avatar session.  Generated 24 kHz audio
is resampled to LiveTalking's 16 kHz audio-frame format before it reaches the
lip-sync pipeline.
"""

from __future__ import annotations

from pathlib import Path
import time

import numpy as np
import resampy

from registry import register
from tts.base_tts import BaseTTS, State
from utils.logger import logger


@register("tts", "omnivoice")
class OmniVoiceTTS(BaseTTS):
    """Run OmniVoice locally, with optional zero-shot voice cloning."""

    def __init__(self, opt, parent):
        super().__init__(opt, parent)
        try:
            import torch
            from omnivoice import OmniVoice
        except ImportError as exc:
            raise RuntimeError(
                "OmniVoice is not installed. Run scripts\\setup_omnivoice_windows.ps1"
            ) from exc

        self._torch = torch
        self.model_id = getattr(
            opt, "omnivoice_model", "splendor1811/omnivoice-vietnamese"
        )
        requested_device = str(getattr(opt, "omnivoice_device", "auto") or "auto")
        if requested_device == "auto":
            requested_device = "cuda:0" if torch.cuda.is_available() else "cpu"
        self.device = requested_device

        dtype_name = str(getattr(opt, "omnivoice_dtype", "float16") or "float16")
        if self.device == "cpu":
            dtype_name = "float32"
        dtype = {
            "float16": torch.float16,
            "bfloat16": torch.bfloat16,
            "float32": torch.float32,
        }.get(dtype_name)
        if dtype is None:
            raise ValueError(
                "omnivoice_dtype must be float16, bfloat16, or float32"
            )

        logger.info(
            "Loading OmniVoice model %s on %s (%s)",
            self.model_id,
            self.device,
            dtype_name,
        )
        started = time.time()
        self.model = OmniVoice.from_pretrained(
            self.model_id,
            device_map=self.device,
            dtype=dtype,
        )
        self.source_sample_rate = int(getattr(self.model, "sampling_rate", 24000))
        self.language = str(getattr(opt, "omnivoice_language", "vietnamese"))
        self.instruct = str(
            getattr(
                opt,
                "omnivoice_instruct",
                "female, young adult, moderate pitch",
            )
            or ""
        )
        self.speed = float(getattr(opt, "omnivoice_speed", 1.0))
        self.num_step = int(getattr(opt, "omnivoice_num_step", 16))
        self.voice_prompt = None

        ref_audio = str(getattr(opt, "omnivoice_ref_audio", "") or "").strip()
        ref_text = str(getattr(opt, "omnivoice_ref_text", "") or "").strip()
        if ref_audio:
            path = Path(ref_audio)
            if not path.is_file():
                raise FileNotFoundError(f"OmniVoice reference audio not found: {path}")
            if not ref_text:
                raise ValueError(
                    "omnivoice_ref_text is required when omnivoice_ref_audio is set"
                )
            logger.info("Creating cached OmniVoice prompt from %s", path)
            self.voice_prompt = self.model.create_voice_clone_prompt(
                ref_audio=str(path), ref_text=ref_text
            )

        logger.info(
            "OmniVoice ready in %.2fs; source sample rate=%d",
            time.time() - started,
            self.source_sample_rate,
        )

    def txt_to_audio(self, msg: tuple[str, dict]):
        text, text_event = msg
        started = time.time()
        generation = {
            "text": text,
            "language": self.language,
            "speed": self.speed,
            "num_step": self.num_step,
        }
        if self.voice_prompt is not None:
            generation["voice_clone_prompt"] = self.voice_prompt
        elif self.instruct:
            generation["instruct"] = self.instruct

        try:
            audio_items = self.model.generate(**generation)
            if not audio_items:
                raise RuntimeError("OmniVoice returned no audio")
            stream = np.asarray(audio_items[0], dtype=np.float32).reshape(-1)
            if self.source_sample_rate != self.sample_rate and stream.size:
                stream = resampy.resample(
                    stream,
                    sr_orig=self.source_sample_rate,
                    sr_new=self.sample_rate,
                ).astype(np.float32)
            self._enqueue_audio(stream, text, text_event)
            logger.info(
                "OmniVoice TTS time: %.3fs for %.2fs audio",
                time.time() - started,
                stream.size / self.sample_rate,
            )
        except Exception:
            logger.exception("OmniVoice synthesis failed")

    def _enqueue_audio(self, stream, text: str, text_event: dict):
        if stream.size == 0 or self.state != State.RUNNING:
            return
        remainder = stream.size % self.chunk
        if remainder:
            stream = np.pad(stream, (0, self.chunk - remainder))
        frame_count = stream.size // self.chunk
        for frame_index in range(frame_count):
            if self.state != State.RUNNING:
                break
            event_point = {}
            if frame_index == 0:
                event_point = {"status": "start", "text": text}
            if frame_index == frame_count - 1:
                event_point = {"status": "end", "text": text}
            event_point.update(**text_event)
            start = frame_index * self.chunk
            self.parent.put_audio_frame(
                stream[start : start + self.chunk], event_point
            )

    def stop_tts(self):
        # Release model memory during a clean server shutdown.
        self.voice_prompt = None
        self.model = None
        if self.device.startswith("cuda") and self._torch.cuda.is_available():
            self._torch.cuda.empty_cache()
