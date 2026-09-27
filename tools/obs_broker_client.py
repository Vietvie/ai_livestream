"""Receive one broker client stream and relay it to local OBS over UDP."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from urllib.parse import quote

import requests


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Relay a GPU server client stream to an OBS Media Source"
    )
    parser.add_argument(
        "--server", default=os.getenv("LIVESTREAM_SERVER_URL", "http://127.0.0.1:8010")
    )
    parser.add_argument(
        "--client-id", default=os.getenv("LIVESTREAM_CLIENT_ID", "client01")
    )
    parser.add_argument(
        "--token", default=os.getenv("LIVESTREAM_API_TOKEN", "")
    )
    parser.add_argument(
        "--obs-url", default="udp://127.0.0.1:23000?pkt_size=1316"
    )
    parser.add_argument("--reconnect-delay", type=float, default=2.0)
    args = parser.parse_args()

    if not args.token:
        parser.error("Set LIVESTREAM_API_TOKEN or pass --token")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        parser.error("ffmpeg was not found in PATH")

    stream_url = (
        f"{args.server.rstrip('/')}/api/v1/clients/"
        f"{quote(args.client_id, safe='')}/stream.ts"
    )
    headers = {"Authorization": f"Bearer {args.token}"}
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "warning",
        "-fflags",
        "+nobuffer+discardcorrupt",
        "-flags",
        "low_delay",
        "-f",
        "mpegts",
        "-i",
        "pipe:0",
        "-map",
        "0:v:0",
        "-map",
        "0:a:0",
        "-c",
        "copy",
        "-f",
        "mpegts",
        args.obs_url,
    ]

    print(f"Client: {args.client_id}")
    print(f"Server stream: {stream_url}")
    print(f"OBS Input: {args.obs_url.split('?')[0]}")
    print("OBS Input Format: mpegts")

    while True:
        process = None
        try:
            with requests.get(
                stream_url,
                headers=headers,
                stream=True,
                timeout=(15, None),
            ) as response:
                response.raise_for_status()
                process = subprocess.Popen(command, stdin=subprocess.PIPE)
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if not chunk:
                        continue
                    if process.poll() is not None:
                        raise RuntimeError(
                            f"FFmpeg exited with code {process.returncode}"
                        )
                    process.stdin.write(chunk)
        except KeyboardInterrupt:
            print("Stopping OBS broker client...")
            return 0
        except Exception as exc:
            print(
                f"Stream disconnected: {exc}; reconnecting in "
                f"{args.reconnect_delay:.1f}s",
                file=sys.stderr,
            )
            time.sleep(max(0.2, args.reconnect_delay))
        finally:
            if process is not None:
                if process.stdin:
                    try:
                        process.stdin.close()
                    except Exception:
                        pass
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=2)


if __name__ == "__main__":
    raise SystemExit(main())
