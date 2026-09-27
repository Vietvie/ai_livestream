"""Download and verify LiveTalking's official Wav2Lip 256 checkpoint."""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DESTINATION = ROOT / "models" / "wav2lip.pth"

# This is wav2lip256.pth from the Google Drive folder linked by LiveTalking.
MODEL_URL = (
    "https://drive.usercontent.google.com/download"
    "?id=1wu6XujFL9rF-0P2l44G6kpeapeY0cME7&export=download&confirm=t"
)
EXPECTED_SIZE = 214_670_409
EXPECTED_SHA256 = "b22d7ac86295df667644b17254dc71250c2600b89e20403e90e58812450bc173"
CHUNK_SIZE = 1024 * 1024


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate(path: Path) -> None:
    if not path.is_file():
        raise RuntimeError(f"Wav2Lip checkpoint was not created: {path}")

    actual_size = path.stat().st_size
    if actual_size != EXPECTED_SIZE:
        raise RuntimeError(
            f"Invalid Wav2Lip checkpoint size: {actual_size} bytes "
            f"(expected {EXPECTED_SIZE})."
        )

    actual_sha256 = _sha256(path)
    if actual_sha256 != EXPECTED_SHA256:
        raise RuntimeError(
            "Wav2Lip checkpoint checksum mismatch. "
            f"Expected {EXPECTED_SHA256}, got {actual_sha256}."
        )


def _download(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    temporary.unlink(missing_ok=True)

    print(
        f"Downloading official Wav2Lip 256 checkpoint (~205 MB) -> {destination}",
        flush=True,
    )
    try:
        with requests.get(url, stream=True, timeout=(30, 120)) as response:
            response.raise_for_status()
            downloaded = 0
            with temporary.open("wb") as file:
                for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                    if not chunk:
                        continue
                    file.write(chunk)
                    downloaded += len(chunk)
                    percent = min(100, downloaded * 100 // EXPECTED_SIZE)
                    print(
                        f"\rWav2Lip download: {percent:3d}% "
                        f"({downloaded / 1024**2:.1f} MiB)",
                        end="",
                        flush=True,
                    )
        print(flush=True)
        _validate(temporary)
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def ensure_wav2lip_model(
    force: bool = False,
    destination: Path | str = DEFAULT_DESTINATION,
) -> Path:
    """Return a verified checkpoint, downloading it on first use."""
    destination = Path(destination).expanduser().resolve()

    if destination.is_file() and not force:
        try:
            _validate(destination)
        except RuntimeError as exc:
            print(
                "Existing Wav2Lip checkpoint failed validation; "
                f"downloading a clean copy ({exc})",
                flush=True,
            )
            destination.unlink()
        else:
            print(f"Wav2Lip checkpoint is ready: {destination}")
            return destination

    _download(MODEL_URL, destination)
    _validate(destination)
    print(f"Wav2Lip checkpoint is ready: {destination}")
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download LiveTalking's official Wav2Lip 256 checkpoint."
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_DESTINATION)
    args = parser.parse_args()
    ensure_wav2lip_model(force=args.force, destination=args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
