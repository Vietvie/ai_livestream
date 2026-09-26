$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

if (-not $env:OPENAI_API_KEY) {
    throw "Set OPENAI_API_KEY before starting the server."
}
if (-not $env:LIVESTREAM_API_TOKEN) {
    throw "Set LIVESTREAM_API_TOKEN before starting the server."
}

# virtualcam is the simplest path into OBS on a Windows GPU host.
python app.py --config config.yaml --transport virtualcam --model wav2lip
