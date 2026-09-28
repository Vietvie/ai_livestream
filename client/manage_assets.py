"""Self-service avatar and voice provisioning for one OBS client."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
from urllib.parse import quote

import requests

from obs_client import _load_config, _setting


def _response_json(response: requests.Response) -> dict:
    try:
        payload = response.json()
    except Exception:
        response.raise_for_status()
        raise RuntimeError(response.text or "Server returned an invalid response")
    if response.status_code >= 400 or payload.get("code") != 0:
        raise RuntimeError(payload.get("msg", response.text))
    return payload.get("data") or {}


def _wait_for_job(
    server: str,
    client_id: str,
    token: str,
    job_id: str,
    timeout: float,
) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    deadline = time.monotonic() + timeout
    previous = ""
    while time.monotonic() < deadline:
        data = _get_job(server, client_id, headers, job_id)
        status = str(data.get("status", ""))
        if status != previous:
            print(f"Asset job {job_id}: {status}", flush=True)
            previous = status
        if status == "completed":
            print(json.dumps(data, ensure_ascii=False, indent=2))
            return data
        if status == "failed":
            raise RuntimeError(data.get("error") or "Asset preparation failed")
        time.sleep(2)
    raise TimeoutError(
        f"Timed out after {timeout:.0f}s; check again with: status {job_id}"
    )


def _get_job(
    server: str, client_id: str, headers: dict, job_id: str
) -> dict:
    url = (
        f"{server.rstrip('/')}/api/v1/clients/"
        f"{quote(client_id, safe='')}/assets/jobs/{quote(job_id, safe='')}"
    )
    return _response_json(requests.get(url, headers=headers, timeout=30))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create this client's private avatar or cloned voice"
    )
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--server")
    parser.add_argument("--client-id")
    parser.add_argument("--token")
    parser.add_argument("--timeout", type=float, default=3600)
    commands = parser.add_subparsers(dest="command", required=True)

    avatar = commands.add_parser("avatar", help="Upload a presenter video")
    avatar.add_argument("file")
    avatar.add_argument("--no-wait", action="store_true")

    voice = commands.add_parser("voice", help="Upload a voice reference WAV")
    voice.add_argument("file")
    voice.add_argument(
        "--text",
        default="",
        help="Exact transcript; omit to let the server transcribe Vietnamese",
    )
    voice.add_argument("--no-wait", action="store_true")

    status = commands.add_parser("status", help="Check an asset job")
    status.add_argument("job_id")
    args = parser.parse_args()

    try:
        config = _load_config(args.config)
    except ValueError as exc:
        parser.error(str(exc))
    server = str(
        _setting(
            args.server,
            config,
            "server_url",
            "LIVESTREAM_SERVER_URL",
            "http://127.0.0.1:8010",
        )
    ).strip()
    client_id = str(
        _setting(args.client_id, config, "client_id", "LIVESTREAM_CLIENT_ID", "")
    ).strip()
    token = str(
        _setting(
            args.token,
            config,
            "stream_token",
            "LIVESTREAM_STREAM_TOKEN",
            "",
        )
    ).strip()
    if not client_id or not token:
        parser.error("config.json must contain client_id and stream_token")

    if args.command == "status":
        job = _get_job(
            server,
            client_id,
            {"Authorization": f"Bearer {token}"},
            args.job_id,
        )
        print(json.dumps(job, ensure_ascii=False, indent=2))
        return 0

    source = Path(args.file).expanduser().resolve()
    if not source.is_file():
        parser.error(f"File not found: {source}")
    max_size = 25 * 1024 * 1024 if args.command == "voice" else 500 * 1024 * 1024
    if source.stat().st_size > max_size:
        parser.error(
            f"File exceeds the {max_size // (1024 * 1024)} MB client limit"
        )

    url = (
        f"{server.rstrip('/')}/api/v1/clients/"
        f"{quote(client_id, safe='')}/assets/{args.command}"
    )
    headers = {"Authorization": f"Bearer {token}"}
    data = {"consent": "true"}
    if args.command == "voice":
        data["ref_text"] = args.text

    print(f"Uploading {source.name}...", flush=True)
    with source.open("rb") as handle:
        job = _response_json(
            requests.post(
                url,
                headers=headers,
                data=data,
                files={"file": (source.name, handle, "application/octet-stream")},
                timeout=(30, 1800),
            )
        )
    print(json.dumps(job, ensure_ascii=False, indent=2))
    if not args.no_wait:
        _wait_for_job(
            server, client_id, token, str(job["job_id"]), args.timeout
        )
        print(
            "Completed. You can now start start.ps1; the server profile was "
            f"updated with the new {args.command}."
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, TimeoutError, requests.RequestException) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
