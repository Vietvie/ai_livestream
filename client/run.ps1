param(
    [string]$Config = "config.json",
    [string]$ServerUrl = "",
    [string]$ClientId = "",
    [string]$Token = "",
    [int]$UdpPort = 0
)

$ErrorActionPreference = "Stop"
$ClientDir = $PSScriptRoot
Set-Location $ClientDir
$env:PATH = "$ClientDir\bin;$env:PATH"
$env:PYTHONUTF8 = "1"

$Python = Join-Path $ClientDir ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "Client environment was not found. Run .\install.ps1 first."
}

$Arguments = @("obs_client.py", "--config", $Config)
if ($ServerUrl) { $Arguments += @("--server", $ServerUrl) }
if ($ClientId) { $Arguments += @("--client-id", $ClientId) }
if ($Token) { $Arguments += @("--token", $Token) }
if ($UdpPort -gt 0) { $Arguments += @("--udp-port", "$UdpPort") }

& $Python @Arguments
exit $LASTEXITCODE
