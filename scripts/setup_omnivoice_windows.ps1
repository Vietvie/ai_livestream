param(
    [string]$Model = "splendor1811/omnivoice-vietnamese",
    [switch]$SkipSmokeTest
)

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

$VenvPython = Join-Path $PWD ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    throw ".venv was not found. Run .\scripts\setup_windows.ps1 first."
}

& $VenvPython -m pip install -r requirements-omnivoice.txt
if ($LASTEXITCODE -ne 0) {
    throw "OmniVoice installation failed."
}

& $VenvPython -m pip check
if ($LASTEXITCODE -ne 0) {
    throw "Python dependency check failed after installing OmniVoice."
}

& $VenvPython -c "import omnivoice; print('OmniVoice package: OK')"
if ($LASTEXITCODE -ne 0) {
    throw "OmniVoice import check failed."
}

if (-not $SkipSmokeTest) {
    Write-Host "Downloading the model on first use and generating Vietnamese audio..."
    & $VenvPython tools\test_omnivoice_tts.py --model $Model
    if ($LASTEXITCODE -ne 0) {
        throw "OmniVoice smoke test failed."
    }
    Write-Host "Test audio: output\omnivoice-test.wav"
}

Write-Host "OmniVoice setup complete."
