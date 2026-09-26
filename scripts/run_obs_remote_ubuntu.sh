#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"

if [[ -x .venv/bin/python ]]; then
  python_bin=.venv/bin/python
else
  python_bin=python3
fi

: "${LIVESTREAM_API_TOKEN:?Set LIVESTREAM_API_TOKEN before starting the server}"

avatar_id="${LIVESTREAM_AVATAR_ID:-host01_muse_fan}"
srt_port="${LIVESTREAM_SRT_PORT:-10080}"
srt_latency="${LIVESTREAM_SRT_LATENCY:-500000}"
video_encoder="${LIVESTREAM_OBS_ENCODER:-libx264}"
obs_url="${LIVESTREAM_OBS_URL:-}"

if [[ -z "$obs_url" ]]; then
  obs_url="srt://0.0.0.0:${srt_port}?mode=listener&transtype=live&latency=${srt_latency}&pkt_size=1316"
  if [[ -n "${LIVESTREAM_SRT_PASSPHRASE:-}" ]]; then
    if [[ ! "$LIVESTREAM_SRT_PASSPHRASE" =~ ^[A-Za-z0-9._~-]{10,79}$ ]]; then
      echo "LIVESTREAM_SRT_PASSPHRASE must be 10-79 URL-safe ASCII characters." >&2
      exit 2
    fi
    obs_url="${obs_url}&passphrase=${LIVESTREAM_SRT_PASSPHRASE}&pbkeylen=16"
  fi
fi

echo "Avatar: $avatar_id"
echo "SRT listener: UDP port $srt_port"
echo "Start the OBS Media Source caller; the first output frame waits for it."

exec "$python_bin" app.py \
  --config config.yaml \
  --transport obs \
  --obs_url "$obs_url" \
  --obs_video_encoder "$video_encoder" \
  --model musetalk \
  --avatar_id "$avatar_id" \
  --batch_size 4 \
  --max_session 1 \
  --tts omnivoice
