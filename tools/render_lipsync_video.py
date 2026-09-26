from __future__ import annotations

import argparse
from pathlib import Path
import os
import time

import requests


def request_json(session, method, url, **kwargs):
    response = session.request(method, url, timeout=30, **kwargs)
    response.raise_for_status()
    payload = response.json()
    if payload.get("code") != 0:
        raise RuntimeError(payload.get("msg", "Unknown server error"))
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render one TTS sentence to a lip-synced MP4 through a running LiveTalking server"
    )
    parser.add_argument(
        "text",
        nargs="?",
        default=(
            "Xin chào, đây là video thử nghiệm chuyển văn bản thành giọng nói "
            "và đồng bộ khẩu hình hoàn toàn tự động."
        ),
    )
    parser.add_argument("--url", default=os.getenv("LIVESTREAM_URL", "http://127.0.0.1:8010"))
    parser.add_argument("--token", default=os.getenv("LIVESTREAM_API_TOKEN", ""))
    parser.add_argument("--session", default="0")
    parser.add_argument("--output", default="output/lipsync-demo.mp4")
    parser.add_argument("--timeout", type=float, default=180)
    args = parser.parse_args()
    if not args.token:
        parser.error("Use --token or set LIVESTREAM_API_TOKEN")

    base = args.url.rstrip("/")
    client = requests.Session()
    client.headers.update({"Authorization": f"Bearer {args.token}"})

    # Give the render thread enough time to publish its first frame so the
    # recorder knows the source resolution.
    time.sleep(2)
    request_json(
        client,
        "POST",
        f"{base}/record",
        json={"sessionid": args.session, "type": "start_record"},
    )
    try:
        request_json(
            client,
            "POST",
            f"{base}/api/livestream/speak",
            json={"sessionid": args.session, "text": args.text, "interrupt": True},
        )
        deadline = time.monotonic() + args.timeout
        started = False
        quiet_since = None
        while time.monotonic() < deadline:
            payload = request_json(
                client,
                "POST",
                f"{base}/is_speaking",
                json={"sessionid": args.session},
            )
            speaking = bool(payload.get("data"))
            if speaking:
                started = True
                quiet_since = None
            elif started:
                quiet_since = quiet_since or time.monotonic()
                if time.monotonic() - quiet_since >= 1.0:
                    break
            time.sleep(0.2)
        if not started:
            raise TimeoutError("TTS/lip-sync did not start before timeout")
    finally:
        request_json(
            client,
            "POST",
            f"{base}/record",
            json={"sessionid": args.session, "type": "end_record"},
        )

    response = client.get(f"{base}/record/{args.session}", timeout=60)
    response.raise_for_status()
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(response.content)
    print(f"Saved {destination.resolve()} ({destination.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
