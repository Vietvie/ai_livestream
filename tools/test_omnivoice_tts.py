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
    args = parser.parse_args()

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for this GPU smoke test")
    print(f"Loading {args.model} on {torch.cuda.get_device_name(0)}")
    model = OmniVoice.from_pretrained(
        args.model, device_map="cuda:0", dtype=torch.float16
    )
    audio = model.generate(
        text=args.text,
        language="vietnamese",
        instruct="female, young adult, moderate pitch",
        num_step=args.num_step,
    )
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    sf.write(destination, audio[0], int(getattr(model, "sampling_rate", 24000)))
    print(f"Saved {destination.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
