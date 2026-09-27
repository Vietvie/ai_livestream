$ErrorActionPreference = "Stop"
$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Installer = Join-Path $ProjectDir "client\install.ps1"

Write-Warning "OBS Client source moved to the standalone client directory."
& powershell -ExecutionPolicy Bypass -File $Installer
exit $LASTEXITCODE
