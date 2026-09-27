param(
    [string]$AvatarId = "host01_muse_fan",
    [int]$SrtPort = 10080,
    [string]$SrtPassphrase = "MatKhauSRT123456",
    [int]$RelayPort = 23001
)

$ErrorActionPreference = "Stop"
$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $ProjectDir
$env:PATH = "$ProjectDir\bin;$env:PATH"
$env:PYTHONUTF8 = "1"
$env:OMP_NUM_THREADS = "4"
$env:MKL_NUM_THREADS = "4"
$env:OPENBLAS_NUM_THREADS = "4"
$env:NUMEXPR_NUM_THREADS = "4"
$env:OPENCV_FOR_THREADS_NUM = "2"
$env:TOKENIZERS_PARALLELISM = "false"

$VenvPython = Join-Path $PWD ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    throw ".venv was not found. Run .\scripts\setup_windows.ps1 first."
}
if (-not $env:LIVESTREAM_API_TOKEN) {
    $env:LIVESTREAM_API_TOKEN = "local-test-token"
    Write-Warning "Using the test API token: local-test-token"
}

if ($env:LIVESTREAM_AVATAR_ID) {
    $AvatarId = $env:LIVESTREAM_AVATAR_ID
}
if ($env:LIVESTREAM_SRT_PORT) {
    $SrtPort = [int]$env:LIVESTREAM_SRT_PORT
}
if ($env:LIVESTREAM_SRT_PASSPHRASE) {
    $SrtPassphrase = $env:LIVESTREAM_SRT_PASSPHRASE
}
if ($SrtPassphrase.Length -lt 10 -or $SrtPassphrase.Length -gt 79) {
    throw "SRT passphrase must contain 10-79 characters."
}

$Ffmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
if (-not $Ffmpeg) {
    throw "ffmpeg was not found. Run .\scripts\setup_windows.ps1 first."
}
$FfmpegProtocols = (& ffmpeg -hide_banner -protocols 2>&1 | Out-String)
if ($FfmpegProtocols -notmatch "(?m)^\s+srt\s*$") {
    throw "The installed ffmpeg build does not include the SRT protocol."
}

$ObsUrl = if ($env:LIVESTREAM_OBS_URL) {
    $env:LIVESTREAM_OBS_URL
} else {
    "srt://0.0.0.0:${SrtPort}?mode=listener&transtype=live&latency=500000&pkt_size=1316&passphrase=${SrtPassphrase}&pbkeylen=16"
}
$VideoEncoder = if ($env:LIVESTREAM_OBS_ENCODER) {
    $env:LIVESTREAM_OBS_ENCODER
} else {
    "h264_nvenc"
}
$LocalObsUrl = "srt://127.0.0.1:${SrtPort}?mode=caller&transtype=live&latency=500000&passphrase=${SrtPassphrase}&pbkeylen=16"
$RemoteObsUrl = "srt://IP_PUBLIC_VPS:${SrtPort}?mode=caller&transtype=live&latency=500000&passphrase=${SrtPassphrase}&pbkeylen=16"

Write-Host "Avatar: $AvatarId"
Write-Host "OBS local Input:  $LocalObsUrl"
Write-Host "OBS remote Input: $RemoteObsUrl"
Write-Host "OBS Input Format: mpegts"

& $VenvPython app.py `
    --config config.yaml `
    --transport obs `
    --obs_url $ObsUrl `
    --obs_video_encoder $VideoEncoder `
    --obs_video_bitrate 3000000 `
    --obs_srt_relay_port $RelayPort `
    --model musetalk `
    --avatar_id $AvatarId `
    --batch_size 4 `
    --max_session 1 `
    --tts omnivoice `
    --omnivoice_num_step 8

exit $LASTEXITCODE
