param(
    [ValidateSet("musetalk", "wav2lip", "way2lip", "lip2way", "ultralight")]
    [string]$Model = "musetalk",
    [string]$AvatarId = "",
    [string]$VoiceRefAudio = "",
    [string]$VoiceRefText = "",
    [string]$VoiceRefTextFile = "",
    [ValidateSet("udp", "srt")]
    [string]$ObsMode = "udp",
    [int]$LipSyncOffsetFrames = 1,
    [int]$BatchSize = 0,
    [int]$UdpPort = 23000,
    [int]$SrtPort = 10080,
    [string]$SrtPassphrase = "MatKhauSRT123456",
    [int]$RelayPort = 23001,
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

$VenvPython = Join-Path $PWD ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    throw ".venv was not found. Run .\scripts\setup_windows.ps1 first."
}
if (-not $env:LIVESTREAM_API_TOKEN) {
    $env:LIVESTREAM_API_TOKEN = "local-test-token"
    Write-Warning "Using the test API token: local-test-token"
}

if ($env:LIVESTREAM_VOICE_REF_AUDIO) {
    $VoiceRefAudio = $env:LIVESTREAM_VOICE_REF_AUDIO
}
if ($env:LIVESTREAM_VOICE_REF_TEXT) {
    $VoiceRefText = $env:LIVESTREAM_VOICE_REF_TEXT
}
if ($env:LIVESTREAM_VOICE_REF_TEXT_FILE) {
    $VoiceRefTextFile = $env:LIVESTREAM_VOICE_REF_TEXT_FILE
}
if ($VoiceRefText -and $VoiceRefTextFile) {
    throw "Use either VoiceRefText or VoiceRefTextFile, not both."
}
if ($VoiceRefTextFile) {
    if (-not (Test-Path -LiteralPath $VoiceRefTextFile -PathType Leaf)) {
        throw "Voice transcript file was not found: $VoiceRefTextFile"
    }
    $VoiceRefText = (
        Get-Content -LiteralPath $VoiceRefTextFile -Raw -Encoding UTF8
    ).Trim()
}
if ([bool]$VoiceRefAudio -ne [bool]$VoiceRefText) {
    throw "VoiceRefAudio and VoiceRefText (or VoiceRefTextFile) must be supplied together."
}
if ($VoiceRefAudio) {
    if (-not (Test-Path -LiteralPath $VoiceRefAudio -PathType Leaf)) {
        throw "Voice reference audio was not found: $VoiceRefAudio"
    }
    if ([System.IO.Path]::GetExtension($VoiceRefAudio).ToLowerInvariant() -ne ".wav") {
        throw "Voice reference audio must be a WAV file."
    }
    $VoiceRefAudio = (Resolve-Path -LiteralPath $VoiceRefAudio).Path
}

if ($env:LIVESTREAM_MODEL) {
    $Model = $env:LIVESTREAM_MODEL.ToLowerInvariant()
}
if ($Model -notin @("musetalk", "wav2lip", "way2lip", "lip2way", "ultralight")) {
    throw "Model must be musetalk, wav2lip, way2lip, lip2way, or ultralight."
}
$RequestedModel = $Model
$RuntimeModel = if ($Model -in @("way2lip", "lip2way")) { "wav2lip" } else { $Model }

if ($env:LIVESTREAM_AVATAR_ID) {
    $AvatarId = $env:LIVESTREAM_AVATAR_ID
}
if (-not $AvatarId) {
    $AvatarId = switch ($RuntimeModel) {
        "musetalk" { "host01_muse_fan" }
        "wav2lip" { "host01" }
        "ultralight" { "ultralight_avatar1" }
    }
}
if ($BatchSize -le 0) {
    $BatchSize = if ($RuntimeModel -eq "wav2lip") { 8 } else { 4 }
}
if ($env:LIVESTREAM_SRT_PORT) {
    $SrtPort = [int]$env:LIVESTREAM_SRT_PORT
}
if ($env:LIVESTREAM_SRT_PASSPHRASE) {
    $SrtPassphrase = $env:LIVESTREAM_SRT_PASSPHRASE
}
if ($env:LIVESTREAM_OBS_MODE) {
    $ObsMode = $env:LIVESTREAM_OBS_MODE.ToLowerInvariant()
}
if ($env:LIVESTREAM_OMNIVOICE_NUM_STEP) {
    $OmniVoiceNumStep = [int]$env:LIVESTREAM_OMNIVOICE_NUM_STEP
}
if ($OmniVoiceNumStep -lt 8 -or $OmniVoiceNumStep -gt 64) {
    throw "OmniVoiceNumStep must be between 8 and 64."
}
if ($ObsMode -notin @("udp", "srt")) {
    throw "OBS mode must be udp or srt."
}
if ($env:LIVESTREAM_OBS_URL -match "^srt://") {
    $ObsMode = "srt"
} elseif ($env:LIVESTREAM_OBS_URL -match "^udp://") {
    $ObsMode = "udp"
}

$ObsUrl = if ($env:LIVESTREAM_OBS_URL) {
    $env:LIVESTREAM_OBS_URL
} elseif ($ObsMode -eq "udp") {
    "udp://127.0.0.1:${UdpPort}?pkt_size=1316"
} else {
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
    "srt://0.0.0.0:${SrtPort}?mode=listener&transtype=live&latency=500000&pkt_size=1316&passphrase=${SrtPassphrase}&pbkeylen=16"
}
$VideoEncoder = if ($env:LIVESTREAM_OBS_ENCODER) {
    $env:LIVESTREAM_OBS_ENCODER
} else {
    "h264_nvenc"
}

Write-Host "Model: $RequestedModel (runtime backend: $RuntimeModel)"
if ($RequestedModel -in @("way2lip", "lip2way")) {
    Write-Warning "$RequestedModel is an alias for LiveTalking's Wav2Lip backend."
}
Write-Host "Avatar: $AvatarId"
Write-Host "Batch size: $BatchSize"
Write-Host "OmniVoice quality: $OmniVoiceNumStep diffusion steps"
if ($VoiceRefAudio) {
    Write-Host "OmniVoice clone: enabled ($([System.IO.Path]::GetFileName($VoiceRefAudio)))"
} elseif (Test-Path -LiteralPath (Join-Path $ProjectDir "voice.wav") -PathType Leaf) {
    Write-Host "OmniVoice clone: automatic (voice.wav detected; PhoWhisper will create the transcript)"
} else {
    Write-Host "OmniVoice clone: disabled (copy voice.wav to the project root to enable it)"
}
Write-Host "OBS mode: $ObsMode"
if ($RuntimeModel -eq "musetalk") {
    Write-Host "MuseTalk lip-sync correction: $LipSyncOffsetFrames frame(s) ($($LipSyncOffsetFrames * 40) ms)"
}
if ($ObsMode -eq "udp") {
    Write-Host "OBS local Input: udp://127.0.0.1:$UdpPort"
} else {
    $LocalObsUrl = "srt://127.0.0.1:${SrtPort}?mode=caller&transtype=live&latency=500000&passphrase=${SrtPassphrase}&pbkeylen=16"
    $RemoteObsUrl = "srt://IP_PUBLIC_VPS:${SrtPort}?mode=caller&transtype=live&latency=500000&passphrase=${SrtPassphrase}&pbkeylen=16"
    Write-Host "OBS local Input:  $LocalObsUrl"
    Write-Host "OBS remote Input: $RemoteObsUrl"
}
Write-Host "OBS Input Format: mpegts"

$VoiceCloneArgs = @()
if ($VoiceRefAudio) {
    $VoiceCloneArgs = @(
        "--omnivoice_ref_audio", $VoiceRefAudio,
        "--omnivoice_ref_text", $VoiceRefText
    )
}

& $VenvPython app.py `
    --config config.yaml `
    --transport obs `
    --obs_url $ObsUrl `
    --obs_video_encoder $VideoEncoder `
    --obs_video_bitrate 3000000 `
    --obs_srt_relay_port $RelayPort `
    --model $RequestedModel `
    --musetalk_sync_offset_frames $LipSyncOffsetFrames `
    --avatar_id $AvatarId `
    --batch_size $BatchSize `
    --max_session 1 `
    --tts omnivoice `
    --omnivoice_num_step $OmniVoiceNumStep `
    @VoiceCloneArgs

exit $LASTEXITCODE
