"""Build a standalone ZIP containing only the lightweight OBS client."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import tempfile
import zipfile


CLIENT_FILES = (
    "README.md",
    "requirements.txt",
    "config.example.json",
    "install.ps1",
    "run.ps1",
    "create_avatar.ps1",
    "create_voice.ps1",
    "obs_client.py",
    "manage_assets.py",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default="dist/AI_LIVESTREAM_OBS_CLIENT.zip",
        help="Destination ZIP path",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    source = root / "client"
    output = Path(args.output).expanduser()
    if not output.is_absolute():
        output = root / output
    output.parent.mkdir(parents=True, exist_ok=True)

    missing = [name for name in CLIENT_FILES if not (source / name).is_file()]
    if missing:
        raise FileNotFoundError(f"Missing client files: {', '.join(missing)}")

    with tempfile.TemporaryDirectory(prefix="ai-livestream-client-") as temp:
        package = Path(temp) / "AI_LIVESTREAM_CLIENT"
        package.mkdir()
        for name in CLIENT_FILES:
            shutil.copy2(source / name, package / name)
        shutil.copy2(root / "LICENSE", package / "LICENSE")
        with zipfile.ZipFile(
            output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
        ) as archive:
            for path in sorted(package.iterdir()):
                archive.write(path, f"AI_LIVESTREAM_CLIENT/{path.name}")

    print(f"Created standalone OBS client: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
