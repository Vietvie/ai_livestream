param(
    [string]$Output = "dist\AI_LIVESTREAM_OBS_CLIENT.zip"
)

$ErrorActionPreference = "Stop"
$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $ProjectDir

$Python = Join-Path $ProjectDir ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw ".venv was not found. Run scripts\setup_windows.ps1 first."
}

& $Python tools\build_obs_client_package.py --output $Output
exit $LASTEXITCODE
