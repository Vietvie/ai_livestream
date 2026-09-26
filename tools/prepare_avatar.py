from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str]) -> None:
    print("+", " ".join(str(part) for part in command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Normalize a prerecorded presenter video and build a LiveTalking avatar"
    )
    parser.add_argument("video", help="Source presenter video")
    parser.add_argument("--avatar-id", required=True)
    parser.add_argument("--model", choices=["wav2lip", "musetalk"], default="wav2lip")
    parser.add_argument("--fps", type=int, default=25)
    parser.add_argument("--width", type=int, default=720)
    parser.add_argument("--height", type=int, default=1280)
    parser.add_argument("--skip-normalize", action="store_true")
    parser.add_argument("--pads", default="0 10 0 0")
    parser.add_argument("--bbox-shift", type=int, default=0)
    parser.add_argument(
        "--landmark-backend",
        choices=["fan", "detector"],
        default="fan",
        help="MuseTalk face crop backend (fan is recommended for lip accuracy)",
    )
    parser.add_argument("--extra-margin", type=int, default=10)
    parser.add_argument("--parsing-mode", choices=["jaw", "raw", "neck"], default="jaw")
    parser.add_argument("--musetalk-version", choices=["v1", "v15"], default="v15")
    args = parser.parse_args()

    source = Path(args.video).expanduser().resolve()
    if not source.exists():
        parser.error(f"Video not found: {source}")
    if not args.skip_normalize and shutil.which("ffmpeg") is None:
        parser.error("ffmpeg is required and was not found in PATH")

    prepared_dir = ROOT / "data" / "prepared"
    prepared_dir.mkdir(parents=True, exist_ok=True)
    normalized = prepared_dir / f"{args.avatar_id}.mp4"
    if args.skip_normalize:
        normalized = source
    else:
        # Preserve aspect ratio and letterbox to a stable canvas. No shell=True,
        # so file names from the API/CLI cannot become shell commands.
        vf = (
            f"fps={args.fps},scale={args.width}:{args.height}:force_original_aspect_ratio=decrease,"
            f"pad={args.width}:{args.height}:(ow-iw)/2:(oh-ih)/2:black"
        )
        run(
            [
                "ffmpeg", "-y", "-i", str(source), "-an", "-vf", vf,
                "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                "-pix_fmt", "yuv420p", str(normalized),
            ]
        )

    if args.model == "wav2lip":
        run(
            [
                sys.executable,
                "-m",
                "avatars.wav2lip.genavatar",
                "--video_path", str(normalized),
                "--avatar_id", args.avatar_id,
                "--img_size", "256",
                "--pads", *args.pads.split(),
            ]
        )
    else:
        run(
            [
                sys.executable,
                "-m",
                "avatars.musetalk.genavatar",
                "--file", str(normalized),
                "--avatar_id", args.avatar_id,
                "--bbox_shift", str(args.bbox_shift),
                "--landmark_backend", args.landmark_backend,
                "--extra_margin", str(args.extra_margin),
                "--parsing_mode", args.parsing_mode,
                "--version", args.musetalk_version,
            ]
        )
    print(f"Avatar ready: data/avatars/{args.avatar_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
