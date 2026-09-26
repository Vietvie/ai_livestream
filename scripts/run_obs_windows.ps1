$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

$VenvPython = Join-Path $PWD ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    throw ".venv was not found. Run .\scripts\setup_windows.ps1 first."
}
if (-not $env:LIVESTREAM_API_TOKEN) {
    throw "Set LIVESTREAM_API_TOKEN before starting the server."
}

$AvatarId = if ($env:LIVESTREAM_AVATAR_ID) { $env:LIVESTREAM_AVATAR_ID } else { "host01_muse_fan" }
$ObsUrl = if ($env:LIVESTREAM_OBS_URL) { $env:LIVESTREAM_OBS_URL } else { "udp://127.0.0.1:23000?pkt_size=1316" }

Write-Host "Avatar: $AvatarId"
Write-Host "OBS Media Source input: udp://127.0.0.1:23000"

& $VenvPython app.py `
    --config config.yaml `
    --transport obs `
    --obs_url $ObsUrl `
    --model musetalk `
    --avatar_id $AvatarId `
    --batch_size 4 `
    --max_session 1 `
    --tts omnivoice
