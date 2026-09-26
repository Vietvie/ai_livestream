$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

$VenvPython = Join-Path $PWD ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    throw ".venv was not found. Run .\scripts\setup_windows.ps1 first."
}

& $VenvPython -m pip install --upgrade "huggingface_hub[hf_xet]>=1.23.0,<2.0" "face-alignment==1.5.0"
if ($LASTEXITCODE -ne 0) {
    throw "Could not install MuseTalk Python dependencies."
}

& $VenvPython -m pip check
if ($LASTEXITCODE -ne 0) {
    throw "Python dependency check failed after installing huggingface_hub."
}

& $VenvPython -c "from diffusers import AutoencoderKL; from transformers import WhisperModel; import face_alignment; face_alignment.FaceAlignment(face_alignment.LandmarksType.TWO_D, device='cpu', compile=False); print('MuseTalk dependencies and FAN landmarks: OK')"
if ($LASTEXITCODE -ne 0) {
    throw "MuseTalk dependency import check failed."
}

Write-Host "MuseTalk dependencies are ready. Checkpoints download on first use."
