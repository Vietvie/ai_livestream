"""Receive one authenticated broker stream and relay it to local OBS."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from urllib.parse import quote

import requests


def _load_config(path: str) -> dict:
    config_path = Path(path).expanduser().resolve()
    if not config_path.is_file():
        return {}
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        raise ValueError(f"Cannot read config file {config_path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("config.json must contain a JSON object")
    return payload


def _setting(cli_value, config: dict, key: str, env_name: str, default=None):
    if cli_value not in (None, ""):
        return cli_value
    env_value = os.getenv(env_name, "")
    if env_value:
        return env_value
    return config.get(key, default)


def _register_client(
    server: str,
    client_id: str,
    registration_key: str,
    config_path: Path,
    config: dict,
) -> str:
    """Register a client-selected ID once and persist its private token."""
    if not registration_key:
        raise ValueError(
            "stream_token is empty. Set registration_key in config.json for "
            "first-time registration."
        )
    url = f"{server.rstrip('/')}/api/v1/register"
    try:
        response = requests.post(
            url,
            json={
                "client_id": client_id,
                "registration_key": registration_key,
            },
            timeout=30,
        )
        payload = response.json()
    except requests.RequestException as exc:
        raise ValueError(f"Cannot register with GPU server: {exc}") from exc
    except Exception as exc:
        raise ValueError(
            "GPU server returned an invalid registration response"
        ) from exc
    if response.status_code >= 400 or payload.get("code") != 0:
        raise ValueError(
            payload.get("msg")
            or f"Registration failed: HTTP {response.status_code}"
        )
    token = str((payload.get("data") or {}).get("stream_token", "")).strip()
    if not token:
        raise ValueError("GPU server did not return a client stream token")

    config["server_url"] = server
    config["client_id"] = client_id
    # The shared key is needed only once. Do not retain it on the client after
    # the server has issued this client's private token.
    config["registration_key"] = ""
    config["stream_token"] = token
    config_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = config_path.with_suffix(config_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(config_path)
    print(
        f"Registered new client ID '{client_id}'. Private token saved and "
        "registration key removed from config.json."
    )
    return token


def _stop_process(process: subprocess.Popen | None) -> None:
    if process is None:
        return
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


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Relay an AI Livestream client stream to an OBS Media Source"
    )
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--server")
    parser.add_argument("--client-id")
    parser.add_argument("--token")
    parser.add_argument("--registration-key")
    parser.add_argument(
        "--register-only",
        action="store_true",
        help="register/save a private token if needed, then exit",
    )
    parser.add_argument("--udp-port", type=int)
    parser.add_argument(
        "--obs-url",
        help="Advanced override; defaults to UDP loopback using --udp-port",
    )
    parser.add_argument("--reconnect-delay", type=float)
    args = parser.parse_args()

    config_path = Path(args.config).expanduser().resolve()
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
    registration_key = str(
        _setting(
            args.registration_key,
            config,
            "registration_key",
            "LIVESTREAM_REGISTRATION_KEY",
            "",
        )
    ).strip()
    udp_port = int(
        _setting(args.udp_port, config, "udp_port", "LIVESTREAM_UDP_PORT", 23000)
    )
    reconnect_delay = float(
        _setting(
            args.reconnect_delay,
            config,
            "reconnect_delay",
            "LIVESTREAM_RECONNECT_DELAY",
            2.0,
        )
    )

    if not client_id:
        parser.error("Set client_id in config.json or pass --client-id")
    if not token:
        try:
            token = _register_client(
                server,
                client_id,
                registration_key,
                config_path,
                config,
            )
        except ValueError as exc:
            parser.error(str(exc))
    if not 1 <= udp_port <= 65535:
        parser.error("udp_port must be between 1 and 65535")
    if args.register_only:
        print(f"Client identity is ready: {client_id}")
        return 0

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        parser.error("ffmpeg was not found. Run install.ps1 first.")

    stream_url = (
        f"{server.rstrip('/')}/api/v1/clients/"
        f"{quote(client_id, safe='')}/stream.ts"
    )
    obs_url = args.obs_url or f"udp://127.0.0.1:{udp_port}?pkt_size=1316"
    headers = {"Authorization": f"Bearer {token}"}
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
        obs_url,
    ]

    print(f"Client ID : {client_id}")
    print(f"Server    : {server}")
    print(f"OBS Input : {obs_url.split('?')[0]}")
    print("OBS Format: mpegts")
    print("Press Ctrl+C to stop.")

    while True:
        process = None
        try:
            print("Connecting to GPU server...")
            with requests.get(
                stream_url,
                headers=headers,
                stream=True,
                timeout=(15, None),
            ) as response:
                response.raise_for_status()
                print("Connected. Relaying video and audio to OBS.")
                process = subprocess.Popen(command, stdin=subprocess.PIPE)
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if not chunk:
                        continue
                    if process.poll() is not None:
                        raise RuntimeError(
                            f"FFmpeg exited with code {process.returncode}"
                        )
                    try:
                        process.stdin.write(chunk)
                    except (BrokenPipeError, OSError) as exc:
                        raise RuntimeError("FFmpeg input pipe was closed") from exc
        except KeyboardInterrupt:
            print("Stopping OBS client...")
            _stop_process(process)
            return 0
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "?"
            if status in (401, 403):
                print(
                    "Authentication failed. Check stream_token in config.json.",
                    file=sys.stderr,
                )
            elif status == 404:
                print(
                    f"Client ID '{client_id}' is not registered on the server.",
                    file=sys.stderr,
                )
            else:
                print(f"Server returned HTTP {status}: {exc}", file=sys.stderr)
            time.sleep(max(0.2, reconnect_delay))
        except Exception as exc:
            print(
                f"Stream disconnected: {exc}; reconnecting in "
                f"{reconnect_delay:.1f}s",
                file=sys.stderr,
            )
            time.sleep(max(0.2, reconnect_delay))
        finally:
            _stop_process(process)


if __name__ == "__main__":
    raise SystemExit(main())
