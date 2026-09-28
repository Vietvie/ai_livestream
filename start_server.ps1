param(
    [string]$Config = "server-config.json"
)

$ErrorActionPreference = "Stop"
$ProjectDir = $PSScriptRoot
Set-Location $ProjectDir

function Get-ConfigValue($Object, [string]$Name, $Default) {
    $Property = $Object.PSObject.Properties[$Name]
    if ($null -eq $Property -or $null -eq $Property.Value -or "$($Property.Value)" -eq "") {
        return $Default
    }
    return $Property.Value
}

$ConfigPath = if ([System.IO.Path]::IsPathRooted($Config)) {
    $Config
} else {
    Join-Path $ProjectDir $Config
}
if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) {
    Copy-Item (Join-Path $ProjectDir "server-config.example.json") $ConfigPath
    throw "Created $ConfigPath. Edit its tokens/settings, then run this command again."
}

$Settings = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
$ApiToken = [string](Get-ConfigValue $Settings "api_token" "")
if ($ApiToken.Length -lt 24 -or $ApiToken.StartsWith("THAY_BANG")) {
    throw "Set api_token in server-config.json to a random value of at least 24 characters."
}
$RegistrationKey = [string](Get-ConfigValue $Settings "client_registration_key" "")
if ($RegistrationKey.Length -lt 24 -or $RegistrationKey.StartsWith("THAY_BANG")) {
    throw "Set client_registration_key in server-config.json to a random value of at least 24 characters."
}
$Model = ([string](Get-ConfigValue $Settings "model" "wav2lip")).ToLowerInvariant()
if ($Model -notin @("wav2lip", "way2lip", "musetalk")) {
    throw "model must be wav2lip, way2lip, or musetalk"
}
$DefaultAvatarId = [string](Get-ConfigValue $Settings "default_avatar_id" "host01")
$AvatarVideoSetting = [string](Get-ConfigValue $Settings "avatar_video" "avatar.mp4")
$ListenPort = [int](Get-ConfigValue $Settings "listen_port" 8010)
$MaxClients = [int](Get-ConfigValue $Settings "max_clients" 2)
$BatchSize = [int](Get-ConfigValue $Settings "batch_size" 4)
$VideoEncoder = [string](Get-ConfigValue $Settings "video_encoder" "h264_nvenc")
$OmniVoiceNumStep = [int](Get-ConfigValue $Settings "omnivoice_num_step" 16)

$Python = Join-Path $ProjectDir ".venv\Scripts\python.exe"
$NeedsSetup = -not (Test-Path -LiteralPath $Python -PathType Leaf)
if (-not $NeedsSetup) {
    & $Python -c "import torch, av, cv2, soundfile, requests, omnivoice" 2>$null
    $NeedsSetup = $LASTEXITCODE -ne 0
}
if ($NeedsSetup) {
    Write-Host "First run: installing the server Python environment..."
    & powershell.exe -NoProfile -ExecutionPolicy Bypass `
        -File (Join-Path $ProjectDir "scripts\setup_windows.ps1")
    if ($LASTEXITCODE -ne 0) {
        throw "Server environment installation failed with code $LASTEXITCODE"
    }
}

$env:PATH = "$ProjectDir\bin;$env:PATH"
$env:PYTHONUTF8 = "1"
$env:LIVESTREAM_API_TOKEN = $ApiToken

$AvatarDir = Join-Path $ProjectDir "data\avatars\$DefaultAvatarId"
$RuntimeModel = if ($Model -eq "way2lip") { "wav2lip" } else { $Model }
$AvatarReady = if ($RuntimeModel -eq "musetalk") {
    (Test-Path (Join-Path $AvatarDir "latents.pt")) -and `
    (Test-Path (Join-Path $AvatarDir "coords.pkl"))
} else {
    (Test-Path (Join-Path $AvatarDir "coords.pkl")) -and `
    (Test-Path (Join-Path $AvatarDir "full_imgs")) -and `
    (Test-Path (Join-Path $AvatarDir "face_imgs"))
}

if (-not $AvatarReady) {
    $AvatarVideo = if ([System.IO.Path]::IsPathRooted($AvatarVideoSetting)) {
        $AvatarVideoSetting
    } else {
        Join-Path $ProjectDir $AvatarVideoSetting
    }
    if (-not (Test-Path -LiteralPath $AvatarVideo -PathType Leaf)) {
        throw "Default avatar is missing. Copy a video to $AvatarVideo"
    }
    Write-Host "First run: preparing $RuntimeModel avatar '$DefaultAvatarId'..."
    $PrepareArgs = @(
        "tools\prepare_avatar.py", $AvatarVideo,
        "--avatar-id", $DefaultAvatarId,
        "--model", $RuntimeModel
    )
    if ($RuntimeModel -eq "musetalk") {
        $PrepareArgs += @(
            "--landmark-backend", "fan",
            "--bbox-shift", "0",
            "--musetalk-version", "v15"
        )
    }
    & $Python @PrepareArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Avatar preparation failed with code $LASTEXITCODE"
    }
}

Write-Host "Starting GPU queue server with one command configuration..."
& (Join-Path $ProjectDir "scripts\run_queue_server_windows.ps1") `
    -Model $Model `
    -DefaultAvatarId $DefaultAvatarId `
    -MaxClients $MaxClients `
    -ListenPort $ListenPort `
    -BatchSize $BatchSize `
    -RegistrationKey $RegistrationKey `
    -VideoEncoder $VideoEncoder `
    -OmniVoiceNumStep $OmniVoiceNumStep

exit $LASTEXITCODE
