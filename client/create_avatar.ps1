param(
    [Parameter(Mandatory = $true)]
    [string]$Video,
    [switch]$NoWait
)

$ErrorActionPreference = "Stop"
$ClientDir = $PSScriptRoot
Set-Location $ClientDir
$Python = Join-Path $ClientDir ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "Client environment was not found. Run .\install.ps1 first."
}

$Arguments = @("manage_assets.py", "avatar", $Video)
if ($NoWait) { $Arguments += "--no-wait" }
& $Python @Arguments
exit $LASTEXITCODE
