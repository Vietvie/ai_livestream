"""Download/load OmniVoice and render a Vietnamese WAV smoke test."""

from __future__ import annotations

import argparse
from pathlib import Path

import soundfile as sf
import torch
from omnivoice import OmniVoice


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--model", default="splendor1811/omnivoice-vietnamese"
    )
    parser.add_argument("--output", default="output/omnivoice-test.wav")
    parser.add_argument(
        "--text",
        default=(
            "Xin chào, đây là bài kiểm tra giọng nói tiếng Việt bằng "
            "mô hình OmniVoice chạy trực tiếp trên máy chủ."
        ),
    )
    parser.add_argument("--num-step", type=int, default=16)
    parser.add_argument("--ref-audio", default="")
    parser.add_argument("--ref-text", default="")
    args = parser.parse_args()

    if bool(args.ref_audio) != bool(args.ref_text):
        parser.error("--ref-audio and --ref-text must be supplied together")

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for this GPU smoke test")
    print(f"Loading {args.model} on {torch.cuda.get_device_name(0)}")
    model = OmniVoice.from_pretrained(
        args.model, device_map="cuda:0", dtype=torch.float16
    )
    generation = {
        "text": args.text,
        "language": "vietnamese",
        "num_step": args.num_step,
    }
    if args.ref_audio:
        ref_audio = Path(args.ref_audio).expanduser().resolve()
        if not ref_audio.is_file():
            parser.error(f"Reference audio not found: {ref_audio}")
        generation["voice_clone_prompt"] = model.create_voice_clone_prompt(
            ref_audio=str(ref_audio), ref_text=args.ref_text.strip()
        )
        print(f"Using voice clone reference: {ref_audio}")
    else:
        generation["instruct"] = "female, young adult, moderate pitch"
    audio = model.generate(**generation)
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    sf.write(destination, audio[0], int(getattr(model, "sampling_rate", 24000)))
    print(f"Saved {destination.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
