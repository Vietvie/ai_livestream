from __future__ import annotations

import argparse
import json
import os
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def call(base_url: str, token: str, path: str, payload=None):
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        base_url.rstrip("/") + path,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="GET" if payload is None else "POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            print(response.read().decode("utf-8"))
    except HTTPError as exc:
        print(exc.read().decode("utf-8"))
        raise SystemExit(exc.code) from exc


def main():
    parser = argparse.ArgumentParser(description="Control a headless AI livestream server")
    parser.add_argument("command", choices=["comment", "speak", "script", "status", "pause", "resume"])
    parser.add_argument("text", nargs="?", default="")
    parser.add_argument("--url", default=os.getenv("LIVESTREAM_URL", "http://127.0.0.1:8010"))
    parser.add_argument("--token", default=os.getenv("LIVESTREAM_API_TOKEN", ""))
    parser.add_argument("--session", default="0")
    parser.add_argument("--comment-id", default="")
    parser.add_argument("--user", default="")
    parser.add_argument("--interrupt", action="store_true")
    args = parser.parse_args()
    if not args.token:
        parser.error("Use --token or set LIVESTREAM_API_TOKEN")

    if args.command == "status":
        return call(args.url, args.token, "/api/livestream/status")
    if args.command in {"pause", "resume"}:
        return call(args.url, args.token, f"/api/livestream/{args.command}", {})
    if not args.text:
        parser.error("text/script id is required")
    if args.command == "comment":
        payload = {
            "sessionid": args.session,
            "text": args.text,
            "comment_id": args.comment_id,
            "user": args.user,
            "interrupt": args.interrupt,
        }
        return call(args.url, args.token, "/api/livestream/comments", payload)
    if args.command == "speak":
        return call(
            args.url,
            args.token,
            "/api/livestream/speak",
            {"sessionid": args.session, "text": args.text, "interrupt": args.interrupt},
        )
    return call(
        args.url,
        args.token,
        "/api/livestream/scripts/trigger",
        {"sessionid": args.session, "script_id": args.text},
    )


if __name__ == "__main__":
    main()
