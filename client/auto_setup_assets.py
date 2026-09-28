"""Upload client-local avatar.mp4 and voice.wav once when they change."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from obs_client import _load_config


CLIENT_DIR = Path(__file__).resolve().parent
STATE_PATH = CLIENT_DIR / ".asset-state.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _load_state() -> dict:
    if not STATE_PATH.is_file():
        return {}
    try:
        payload = json.loads(STATE_PATH.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _save_state(state: dict) -> None:
    temporary = STATE_PATH.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(STATE_PATH)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config.json")
    parser.add_argument(
        "--force",
        action="store_true",
        help="upload files again even when their contents have not changed",
    )
    args = parser.parse_args()

    config_path = Path(args.config).expanduser().resolve()
    config = _load_config(str(config_path))
    server = str(config.get("server_url", "")).strip().rstrip("/")
    client_id = str(config.get("client_id", "")).strip()
    token = str(config.get("stream_token", "")).strip()
    if not server or not client_id or not token:
        parser.error("Client must be registered before automatic asset setup")

    identity = f"{server}|{client_id}"
    state = _load_state()
    if state.get("identity") != identity:
        state = {"identity": identity, "assets": {}}
    assets = state.setdefault("assets", {})

    candidates = (
        ("avatar", CLIENT_DIR / "avatar.mp4"),
        ("voice", CLIENT_DIR / "voice.wav"),
    )
    found = False
    for kind, source in candidates:
        if not source.is_file():
            continue
        found = True
        fingerprint = _sha256(source)
        previous = assets.get(kind) or {}
        if not args.force and previous.get("sha256") == fingerprint:
            print(f"Private {kind} is unchanged; skipping upload.")
            continue

        print(f"Preparing private {kind} from {source.name}...", flush=True)
        command = [
            sys.executable,
            str(CLIENT_DIR / "manage_assets.py"),
            "--config",
            str(config_path),
            kind,
            str(source),
        ]
        if kind == "voice":
            transcript_path = CLIENT_DIR / "voice.txt"
            if transcript_path.is_file():
                transcript = transcript_path.read_text(encoding="utf-8-sig").strip()
                if transcript:
                    command.extend(("--text", transcript))
        subprocess.run(command, cwd=CLIENT_DIR, check=True)
        assets[kind] = {
            "file": source.name,
            "sha256": fingerprint,
        }
        _save_state(state)

    if not found:
        print("No client avatar.mp4 or voice.wav found; using server defaults.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
