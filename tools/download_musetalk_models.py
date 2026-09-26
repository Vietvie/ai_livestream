"""Download only the checkpoints required by LiveTalking MuseTalk v1.5."""

from __future__ import annotations

import argparse
from pathlib import Path

from huggingface_hub import hf_hub_download


ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "models"


def hf_file(repo_id: str, filename: str, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {repo_id}/{filename} -> {destination}", flush=True)
    hf_hub_download(
        repo_id=repo_id,
        filename=filename,
        local_dir=str(destination),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    downloads = [
        ("TMElyralab/MuseTalk", "musetalkV15/unet.pth", MODELS),
        ("TMElyralab/MuseTalk", "musetalkV15/musetalk.json", MODELS),
        ("stabilityai/sd-vae-ft-mse", "config.json", MODELS / "sd-vae"),
        (
            "stabilityai/sd-vae-ft-mse",
            "diffusion_pytorch_model.bin",
            MODELS / "sd-vae",
        ),
        ("openai/whisper-tiny", "config.json", MODELS / "whisper"),
        ("openai/whisper-tiny", "pytorch_model.bin", MODELS / "whisper"),
        (
            "openai/whisper-tiny",
            "preprocessor_config.json",
            MODELS / "whisper",
        ),
        (
            "ManyOtherFunctions/face-parse-bisent",
            "79999_iter.pth",
            MODELS / "face-parse-bisent",
        ),
        (
            "ManyOtherFunctions/face-parse-bisent",
            "resnet18-5c106cde.pth",
            MODELS / "face-parse-bisent",
        ),
        (
            "camenduru/facexlib",
            "s3fd-619a316812.pth",
            MODELS / "face-detection",
        ),
    ]
    for repo_id, filename, destination in downloads:
        target = destination / filename
        if args.force or not target.is_file() or target.stat().st_size == 0:
            hf_file(repo_id, filename, destination)
        else:
            print(f"Already present: {target}")

    s3fd = MODELS / "face-detection" / "s3fd-619a316812.pth"

    expected = [
        MODELS / "musetalkV15" / "unet.pth",
        MODELS / "musetalkV15" / "musetalk.json",
        MODELS / "sd-vae" / "config.json",
        MODELS / "sd-vae" / "diffusion_pytorch_model.bin",
        MODELS / "whisper" / "config.json",
        MODELS / "whisper" / "pytorch_model.bin",
        MODELS / "whisper" / "preprocessor_config.json",
        MODELS / "face-parse-bisent" / "79999_iter.pth",
        MODELS / "face-parse-bisent" / "resnet18-5c106cde.pth",
        s3fd,
    ]
    missing = [str(path) for path in expected if not path.is_file()]
    if missing:
        raise RuntimeError("Missing MuseTalk files:\n" + "\n".join(missing))
    print("MuseTalk v1.5 checkpoints are ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
