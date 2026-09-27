"""Command-line control client for the multi-client livestream broker."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import requests


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--server", default=os.getenv("LIVESTREAM_SERVER_URL", "http://127.0.0.1:8010")
    )
    parser.add_argument(
        "--token", default=os.getenv("LIVESTREAM_API_TOKEN", "")
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    register = subparsers.add_parser("register-client")
    register.add_argument("client_id")
    register.add_argument("--avatar", required=True)
    register.add_argument("--voice", default="")

    upload = subparsers.add_parser("upload-voice")
    upload.add_argument("voice_id")
    upload.add_argument("--file", required=True)
    upload.add_argument(
        "--text",
        default="",
        help="Exact transcript; omit to auto-transcribe Vietnamese with PhoWhisper",
    )

    speak = subparsers.add_parser("speak")
    speak.add_argument("client_id")
    speak.add_argument("text")

    job = subparsers.add_parser("job")
    job.add_argument("job_id")

    subparsers.add_parser("status")
    subparsers.add_parser("assets")
    args = parser.parse_args()

    if not args.token:
        parser.error("Set LIVESTREAM_API_TOKEN or pass --token")
    base = args.server.rstrip("/")
    headers = {"Authorization": f"Bearer {args.token}"}

    if args.command == "register-client":
        response = requests.put(
            f"{base}/api/v1/clients/{args.client_id}",
            headers=headers,
            json={"avatar_id": args.avatar, "voice_id": args.voice},
            timeout=60,
        )
    elif args.command == "upload-voice":
        source = Path(args.file).expanduser().resolve()
        with source.open("rb") as audio:
            response = requests.post(
                f"{base}/api/v1/voices/{args.voice_id}",
                headers=headers,
                data={"ref_text": args.text, "consent": "true"},
                files={"file": (source.name, audio, "audio/wav")},
                timeout=900,
            )
    elif args.command == "speak":
        response = requests.post(
            f"{base}/api/v1/jobs",
            headers=headers,
            json={"client_id": args.client_id, "text": args.text},
            timeout=30,
        )
    elif args.command == "job":
        response = requests.get(
            f"{base}/api/v1/jobs/{args.job_id}", headers=headers, timeout=30
        )
    elif args.command == "status":
        response = requests.get(
            f"{base}/api/v1/queue", headers=headers, timeout=30
        )
    else:
        response = requests.get(
            f"{base}/api/v1/assets", headers=headers, timeout=30
        )

    try:
        payload = response.json()
    except Exception:
        response.raise_for_status()
        print(response.text)
        return 0
    if response.status_code >= 400 or payload.get("code") != 0:
        raise RuntimeError(payload.get("msg", response.text))
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
