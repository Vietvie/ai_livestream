param(
    [string]$ServerUrl = "http://127.0.0.1:8010",
    [string]$ClientId = "client01",
    [int]$UdpPort = 23000
)

$ErrorActionPreference = "Stop"
$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $ProjectDir
$env:PATH = "$ProjectDir\bin;$env:PATH"
$env:PYTHONUTF8 = "1"

$Python = Join-Path $ProjectDir ".client-venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    $Python = Join-Path $ProjectDir ".venv\Scripts\python.exe"
}
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "No Python environment was found. Run scripts\setup_obs_client_windows.ps1 first."
}
if (-not $env:LIVESTREAM_API_TOKEN) {
    throw "Set LIVESTREAM_API_TOKEN to the same token used by the server."
}

& $Python tools\obs_broker_client.py `
    --server $ServerUrl `
    --client-id $ClientId `
    --obs-url "udp://127.0.0.1:${UdpPort}?pkt_size=1316"

exit $LASTEXITCODE
