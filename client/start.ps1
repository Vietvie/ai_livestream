param(
    [switch]$ForceAssets
)

$ErrorActionPreference = "Stop"
$ClientDir = $PSScriptRoot
Set-Location $ClientDir

$Python = Join-Path $ClientDir ".venv\Scripts\python.exe"
$Ffmpeg = Join-Path $ClientDir "bin\ffmpeg.exe"
$NeedsSetup = -not (Test-Path -LiteralPath $Python -PathType Leaf) -or `
    -not (Test-Path -LiteralPath $Ffmpeg -PathType Leaf)
if (-not $NeedsSetup) {
    & $Python -c "import requests" 2>$null
    $NeedsSetup = $LASTEXITCODE -ne 0
}
if ($NeedsSetup) {
    Write-Host "First run: installing the lightweight OBS client..."
    & (Join-Path $ClientDir "install.ps1")
    if ($LASTEXITCODE -ne 0) {
        throw "Client installation failed with code $LASTEXITCODE"
    }
}

# Register the client-selected ID and persist its private stream token before
# uploading private assets or opening the long-running OBS stream.
& $Python obs_client.py --config config.json --register-only
if ($LASTEXITCODE -ne 0) {
    throw "Client registration failed with code $LASTEXITCODE"
}

$AssetArguments = @("auto_setup_assets.py", "--config", "config.json")
if ($ForceAssets) { $AssetArguments += "--force" }
& $Python @AssetArguments
if ($LASTEXITCODE -ne 0) {
    throw "Client avatar/voice setup failed with code $LASTEXITCODE"
}

& (Join-Path $ClientDir "run.ps1")
exit $LASTEXITCODE
