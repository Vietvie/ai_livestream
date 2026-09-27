"""Prepare a zero-configuration OmniVoice reference from ``voice.wav``.

The source is normalized to mono 16 kHz WAV and transcribed locally with a
Vietnamese PhoWhisper model.  A small metadata file makes subsequent starts
instant unless the source WAV or ASR model changes.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import unicodedata

import numpy as np
import resampy
import soundfile as sf


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "voice.wav"
DEFAULT_AUDIO = ROOT / "data" / "voices" / "auto-voice.wav"
DEFAULT_TEXT = ROOT / "data" / "voices" / "auto-voice.txt"
DEFAULT_META = ROOT / "data" / "voices" / "auto-voice.json"
DEFAULT_ASR_MODEL = "vinai/PhoWhisper-medium"


def _source_signature(source: Path, asr_model: str) -> dict:
    stat = source.stat()
    return {
        "source": str(source),
        "source_size": stat.st_size,
        "source_mtime_ns": stat.st_mtime_ns,
        "asr_model": asr_model,
        "format_version": 1,
    }


def _cache_is_current(
    source: Path,
    audio_output: Path,
    text_output: Path,
    metadata_output: Path,
    asr_model: str,
) -> bool:
    if not audio_output.is_file() or not text_output.is_file() or not metadata_output.is_file():
        return False
    try:
        cached = json.loads(metadata_output.read_text(encoding="utf-8"))
        transcript = text_output.read_text(encoding="utf-8").strip()
        audio_info = sf.info(str(audio_output))
    except Exception:
        return False
    return (
        cached == _source_signature(source, asr_model)
        and bool(transcript)
        and audio_info.frames > 0
        and audio_info.samplerate == 16000
        and audio_info.channels == 1
    )


def _normalize_audio(source: Path) -> tuple[np.ndarray, int, float]:
    try:
        audio, sample_rate = sf.read(str(source), dtype="float32", always_2d=True)
    except Exception as exc:
        raise ValueError(f"Cannot read voice reference WAV: {exc}") from exc
    if audio.size == 0 or sample_rate <= 0:
        raise ValueError("voice.wav contains no audio")

    # Mix stereo/multichannel samples down to mono and reject NaN/Inf values.
    mono = np.nan_to_num(audio.mean(axis=1), nan=0.0, posinf=0.0, neginf=0.0)
    peak = float(np.max(np.abs(mono)))
    if peak < 1e-5:
        raise ValueError("voice.wav is silent")

    # Trim leading/trailing silence at roughly -40 dB, retaining 200 ms of
    # context so the cloned timbre does not start abruptly.
    active = np.flatnonzero(np.abs(mono) >= peak * 0.01)
    if active.size:
        padding = int(sample_rate * 0.2)
        start = max(0, int(active[0]) - padding)
        end = min(mono.size, int(active[-1]) + padding + 1)
        mono = mono[start:end]

    if sample_rate != 16000:
        mono = resampy.resample(mono, sample_rate, 16000).astype(np.float32)
        sample_rate = 16000

    duration = mono.size / sample_rate
    if duration < 3.0:
        raise ValueError("voice.wav must contain at least 3 seconds of speech")
    if duration > 30.0:
        mono = mono[: 30 * sample_rate]
        duration = 30.0

    # Normalize conservatively to -3 dBFS without applying dynamic compression.
    peak = float(np.max(np.abs(mono)))
    mono = (mono * (0.7079 / max(peak, 1e-8))).astype(np.float32)
    return mono, sample_rate, duration


def _transcribe_vietnamese(audio: np.ndarray, sample_rate: int, model_id: str) -> str:
    import torch
    from transformers import pipeline

    device = 0 if torch.cuda.is_available() else -1
    device_name = torch.cuda.get_device_name(0) if device == 0 else "CPU"
    print(f"Loading Vietnamese ASR {model_id} on {device_name}", flush=True)
    transcriber = pipeline(
        "automatic-speech-recognition",
        model=model_id,
        device=device,
    )
    inputs = {"array": audio, "sampling_rate": sample_rate}
    try:
        result = transcriber(
            inputs,
            generate_kwargs={"language": "vi", "task": "transcribe"},
        )
    except (KeyError, ValueError):
        # Older Transformers releases call the waveform key ``raw``.
        result = transcriber(
            {"raw": audio, "sampling_rate": sample_rate},
            generate_kwargs={"language": "vi", "task": "transcribe"},
        )
    transcript = unicodedata.normalize("NFC", str(result.get("text", ""))).strip()
    if not transcript:
        raise RuntimeError("PhoWhisper returned an empty transcript for voice.wav")
    return transcript


def prepare_voice_clone(
    source: Path,
    audio_output: Path,
    text_output: Path,
    metadata_output: Path,
    asr_model: str,
    force: bool = False,
) -> tuple[Path, Path]:
    source = source.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Voice reference not found: {source}")
    if source.suffix.lower() != ".wav":
        raise ValueError("Voice reference must be named voice.wav")

    if not force and _cache_is_current(
        source, audio_output, text_output, metadata_output, asr_model
    ):
        print(f"Voice clone cache is current: {audio_output}")
        print(f"Transcript: {text_output.read_text(encoding='utf-8').strip()}")
        return audio_output, text_output

    audio, sample_rate, duration = _normalize_audio(source)
    print(
        f"Prepared voice.wav: {duration:.2f}s, mono, {sample_rate} Hz; transcribing...",
        flush=True,
    )
    transcript = _transcribe_vietnamese(audio, sample_rate, asr_model)

    audio_output.parent.mkdir(parents=True, exist_ok=True)
    audio_tmp = audio_output.with_suffix(".wav.tmp")
    text_tmp = text_output.with_suffix(".txt.tmp")
    meta_tmp = metadata_output.with_suffix(".json.tmp")
    sf.write(str(audio_tmp), audio, sample_rate, format="WAV", subtype="PCM_16")
    text_tmp.write_text(transcript + "\n", encoding="utf-8")
    meta_tmp.write_text(
        json.dumps(_source_signature(source, asr_model), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    os.replace(audio_tmp, audio_output)
    os.replace(text_tmp, text_output)
    os.replace(meta_tmp, metadata_output)
    print(f"Automatic transcript: {transcript}")
    print(f"Voice clone audio: {audio_output}")
    print(f"Voice clone text:  {text_output}")
    return audio_output, text_output


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Normalize voice.wav and transcribe it for OmniVoice cloning"
    )
    parser.add_argument("source", nargs="?", default=str(DEFAULT_SOURCE))
    parser.add_argument("--audio-output", default=str(DEFAULT_AUDIO))
    parser.add_argument("--text-output", default=str(DEFAULT_TEXT))
    parser.add_argument("--metadata-output", default=str(DEFAULT_META))
    parser.add_argument("--asr-model", default=DEFAULT_ASR_MODEL)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    prepare_voice_clone(
        Path(args.source),
        Path(args.audio_output).resolve(),
        Path(args.text_output).resolve(),
        Path(args.metadata_output).resolve(),
        args.asr_model,
        force=args.force,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
