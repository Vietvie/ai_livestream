"""Local OmniVoice text-to-speech backend.

The model is loaded lazily with the official ``omnivoice`` Python package and
kept in memory for the lifetime of the avatar session.  Generated 24 kHz audio
is resampled to LiveTalking's 16 kHz audio-frame format before it reaches the
lip-sync pipeline.
"""

from __future__ import annotations

from pathlib import Path
from threading import Lock, RLock
import time

import numpy as np
import resampy
import soundfile as sf

from registry import register
from tts.base_tts import BaseTTS, State
from tts.text_utils import split_synthesis_text
from utils.logger import logger


@register("tts", "omnivoice")
class OmniVoiceTTS(BaseTTS):
    """Run OmniVoice locally, with optional zero-shot voice cloning."""

    # Multiple client sessions share the large GPU model. Voice prompts remain
    # per instance, while generation is serialized by the shared model lock.
    _shared_models = {}
    _shared_models_guard = Lock()

    def __init__(self, opt, parent):
        super().__init__(opt, parent)
        try:
            import torch
            from omnivoice import OmniVoice
        except ImportError as exc:
            raise RuntimeError(
                "OmniVoice is not installed. Rerun scripts\\setup_windows.ps1"
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

        shared_key = (self.model_id, self.device, dtype_name)
        started = time.time()
        with self._shared_models_guard:
            shared = self._shared_models.get(shared_key)
            if shared is None:
                logger.info(
                    "Loading shared OmniVoice model %s on %s (%s)",
                    self.model_id,
                    self.device,
                    dtype_name,
                )
                shared = (
                    OmniVoice.from_pretrained(
                        self.model_id,
                        device_map=self.device,
                        dtype=dtype,
                    ),
                    RLock(),
                )
                self._shared_models[shared_key] = shared
            else:
                logger.info("Reusing shared OmniVoice model for client session")
        self.model, self._model_lock = shared
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
        if not 8 <= self.num_step <= 64:
            raise ValueError("omnivoice_num_step must be between 8 and 64")
        self.voice_prompt = None
        self.voice_prompt_info = None

        ref_audio = str(getattr(opt, "omnivoice_ref_audio", "") or "").strip()
        ref_text = str(getattr(opt, "omnivoice_ref_text", "") or "").strip()
        if bool(ref_audio) != bool(ref_text):
            raise ValueError(
                "omnivoice_ref_audio and omnivoice_ref_text must be supplied together"
            )
        if ref_audio:
            self.configure_voice_clone(ref_audio, ref_text)

        logger.info(
            "OmniVoice ready in %.2fs; source sample rate=%d",
            time.time() - started,
            self.source_sample_rate,
        )

    def txt_to_audio(self, msg: tuple[str, dict]):
        text, text_event = msg
        started = time.time()
        base_generation = {
            "language": self.language,
            "speed": self.speed,
            "num_step": self.num_step,
        }
        try:
            segments = split_synthesis_text(text)
            if not segments:
                return
            generated_streams = []
            # OmniVoice prompt creation and inference share one model instance.
            # Serialize them so a remote voice change cannot corrupt an active
            # synthesis request.
            with self._model_lock:
                if self.voice_prompt is not None:
                    base_generation["voice_clone_prompt"] = self.voice_prompt
                elif self.instruct:
                    base_generation["instruct"] = self.instruct
                for segment in segments:
                    generation = dict(base_generation, text=segment)
                    audio_items = self.model.generate(**generation)
                    if not audio_items:
                        raise RuntimeError(
                            f"OmniVoice returned no audio for segment: {segment}"
                        )
                    generated = np.asarray(
                        audio_items[0], dtype=np.float32
                    ).reshape(-1)
                    if generated.size == 0:
                        raise RuntimeError(
                            f"OmniVoice returned empty audio for segment: {segment}"
                        )
                    generated_streams.append(generated)

            # A small pause prevents adjacent generated segments from masking
            # each other's final/initial phoneme in the realtime stream.
            inter_segment_silence = np.zeros(
                int(self.source_sample_rate * 0.08), dtype=np.float32
            )
            stream_parts = []
            for index, generated in enumerate(generated_streams):
                if index:
                    stream_parts.append(inter_segment_silence)
                stream_parts.append(generated)
            stream = np.concatenate(stream_parts)
            if self.source_sample_rate != self.sample_rate and stream.size:
                stream = resampy.resample(
                    stream,
                    sr_orig=self.source_sample_rate,
                    sr_new=self.sample_rate,
                ).astype(np.float32)
            self._enqueue_audio(stream, text, text_event)
            logger.info(
                "OmniVoice TTS time: %.3fs for %.2fs audio (%d segment(s), %d steps)",
                time.time() - started,
                stream.size / self.sample_rate,
                len(segments),
                self.num_step,
            )
        except Exception:
            logger.exception("OmniVoice synthesis failed")

    def configure_voice_clone(self, ref_audio: str, ref_text: str) -> dict:
        """Build and cache a voice-clone prompt for subsequent utterances."""
        path = Path(ref_audio).expanduser().resolve()
        transcript = str(ref_text or "").strip()
        if not path.is_file():
            raise FileNotFoundError(f"OmniVoice reference audio not found: {path}")
        if path.suffix.lower() != ".wav":
            raise ValueError("Voice reference must be a WAV file")
        if not transcript:
            raise ValueError(
                "An exact reference transcript is required for voice cloning"
            )

        try:
            audio_info = sf.info(str(path))
        except Exception as exc:
            raise ValueError(f"Invalid WAV reference audio: {exc}") from exc
        if audio_info.samplerate <= 0 or audio_info.frames <= 0:
            raise ValueError("Voice reference WAV contains no audio")
        duration = audio_info.frames / audio_info.samplerate
        if duration < 3.0 or duration > 30.0:
            raise ValueError("Voice reference duration must be between 3 and 30 seconds")

        logger.info(
            "Creating OmniVoice clone prompt from %s (%.2fs, %d Hz, %d channel(s))",
            path.name,
            duration,
            audio_info.samplerate,
            audio_info.channels,
        )
        with self._model_lock:
            prompt = self.model.create_voice_clone_prompt(
                ref_audio=str(path), ref_text=transcript
            )
            self.voice_prompt = prompt
            self.voice_prompt_info = {
                "file": path.name,
                "duration_seconds": round(duration, 3),
                "sample_rate": audio_info.samplerate,
                "channels": audio_info.channels,
            }
        logger.info("OmniVoice voice clone enabled: %s", path.name)
        return dict(self.voice_prompt_info)

    def clear_voice_clone(self) -> None:
        """Return to the configured descriptive/default OmniVoice voice."""
        with self._model_lock:
            self.voice_prompt = None
            self.voice_prompt_info = None
        logger.info("OmniVoice voice clone disabled")

    def get_voice_clone_status(self) -> dict:
        with self._model_lock:
            return {
                "enabled": self.voice_prompt is not None,
                "reference": (
                    dict(self.voice_prompt_info) if self.voice_prompt_info else None
                ),
            }

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
        # The GPU model is shared by all client sessions and stays resident for
        # the server lifetime. Only release this client's voice prompt.
        with self._model_lock:
            self.voice_prompt = None
            self.voice_prompt_info = None
