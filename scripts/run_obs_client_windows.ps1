param(
    [string]$ServerUrl = "http://127.0.0.1:8010",
    [string]$ClientId = "client01",
    [int]$UdpPort = 23000,
    [string]$StreamToken = ""
)

$ErrorActionPreference = "Stop"
$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Runner = Join-Path $ProjectDir "client\run.ps1"

if (-not $StreamToken) {
    $StreamToken = $env:LIVESTREAM_STREAM_TOKEN
}

Write-Warning "OBS Client source moved to the standalone client directory."
$Arguments = @(
    "-ExecutionPolicy", "Bypass",
    "-File", $Runner,
    "-ServerUrl", $ServerUrl,
    "-ClientId", $ClientId,
    "-UdpPort", "$UdpPort"
)
if ($StreamToken) { $Arguments += @("-Token", $StreamToken) }

& powershell @Arguments
exit $LASTEXITCODE
