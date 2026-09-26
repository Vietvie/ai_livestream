#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
python app.py --config config.yaml --transport webrtc
