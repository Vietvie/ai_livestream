"""Apply local bootstrap clients from server-config.json before startup."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.broker_service import BrokerService  # noqa: E402


def avatar_matches_model(avatar_id: str, model: str) -> bool:
    """Return whether an existing avatar has assets for the selected backend."""
    avatar_dir = ROOT / "data" / "avatars" / avatar_id
    if model == "musetalk":
        return (
            (avatar_dir / "latents.pt").is_file()
            and (avatar_dir / "coords.pkl").is_file()
        )
    return (
        (avatar_dir / "coords.pkl").is_file()
        and (avatar_dir / "full_imgs").is_dir()
        and (avatar_dir / "face_imgs").is_dir()
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="server-config.json")
    args = parser.parse_args()

    config_path = Path(args.config).expanduser()
    if not config_path.is_absolute():
        config_path = ROOT / config_path
    payload = json.loads(config_path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("server-config.json must contain a JSON object")

    model = str(payload.get("model", "wav2lip")).strip().lower()
    runtime_model = "wav2lip" if model == "way2lip" else model
    default_avatar = str(payload.get("default_avatar_id", "host01")).strip()
    clients = payload.get("clients") or []
    if not isinstance(clients, list) or not clients:
        raise ValueError("server-config.json must define at least one client")

    service = BrokerService(ROOT, avatar_model=model)
    for item in clients:
        if not isinstance(item, dict):
            raise ValueError("Each clients entry must be a JSON object")
        client_id = str(item.get("client_id", ""))
        existing = service.profiles.get(client_id)
        reset_assets = item.get("reset_assets") is True
        avatar_id = str(item.get("avatar_id") or default_avatar)
        voice_id = str(item.get("voice_id", ""))
        if existing is not None and not reset_assets:
            # Keep client-created assets across restarts. If the server changes
            # lip-sync backend, retain the voice but fall back to the new
            # backend's configured default avatar.
            voice_id = existing.voice_id
            if avatar_matches_model(existing.avatar_id, runtime_model):
                avatar_id = existing.avatar_id
        profile = service.provision_profile(
            client_id=client_id,
            avatar_id=avatar_id,
            voice_id=voice_id,
            stream_token=str(item.get("stream_token", "")),
        )
        print(
            f"Configured client {profile.client_id}: "
            f"avatar={profile.avatar_id}, voice={profile.voice_id or 'default'}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
