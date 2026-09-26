$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

$VenvPython = Join-Path $PWD ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    throw ".venv was not found. Run .\scripts\setup_windows.ps1 first."
}

& $VenvPython -m pip install --upgrade "huggingface_hub[hf_xet]>=1.23.0,<2.0"
if ($LASTEXITCODE -ne 0) {
    throw "Could not install huggingface_hub."
}

& $VenvPython -m pip check
if ($LASTEXITCODE -ne 0) {
    throw "Python dependency check failed after installing huggingface_hub."
}

& $VenvPython tools\download_musetalk_models.py
if ($LASTEXITCODE -ne 0) {
    throw "MuseTalk checkpoint download failed."
}

& $VenvPython -c "from diffusers import AutoencoderKL; from transformers import WhisperModel; print('MuseTalk dependencies: OK')"
if ($LASTEXITCODE -ne 0) {
    throw "MuseTalk dependency import check failed."
}

Write-Host "MuseTalk v1.5 setup complete."
