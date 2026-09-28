param(
    [ValidateSet("wav2lip", "way2lip", "musetalk")]
    [string]$Model = "way2lip",
    [string]$DefaultAvatarId = "",
    [int]$MaxClients = 4,
    [int]$ListenPort = 8010,
    [int]$BatchSize = 4,
    [Parameter(Mandatory = $true)]
    [string]$RegistrationKey,
    [ValidateSet("h264_nvenc", "libx264")]
    [string]$VideoEncoder = "h264_nvenc",
    [ValidateRange(8, 64)]
    [int]$OmniVoiceNumStep = 16
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

$Python = Join-Path $ProjectDir ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw ".venv was not found. Run scripts\setup_windows.ps1 first."
}
if (-not $env:LIVESTREAM_API_TOKEN) {
    $env:LIVESTREAM_API_TOKEN = "local-test-token"
    Write-Warning "Using test token local-test-token. Change it before exposing the server."
}
if (-not $DefaultAvatarId) {
    $DefaultAvatarId = if ($Model -eq "musetalk") { "host01_muse_fan" } else { "host01" }
}

Write-Host "Queue server: http://0.0.0.0:$ListenPort"
Write-Host "Model: $Model"
Write-Host "Maximum client sessions: $MaxClients"
Write-Host "Video encoder per client: $VideoEncoder"
Write-Host "Shared OmniVoice model: enabled"
Write-Host "Speech scheduling: global FIFO"

& $Python app.py `
    --config config.yaml `
    --transport broker `
    --model $Model `
    --avatar_id $DefaultAvatarId `
    --batch_size $BatchSize `
    --max_session $MaxClients `
    --broker_registration_key $RegistrationKey `
    --listenport $ListenPort `
    --obs_video_encoder $VideoEncoder `
    --obs_video_bitrate 3000000 `
    --tts omnivoice `
    --omnivoice_num_step $OmniVoiceNumStep

exit $LASTEXITCODE
