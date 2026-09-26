param(
    [string]$TorchIndexUrl = "https://download.pytorch.org/whl/cu128"
)

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

function Find-Python312 {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $InstalledPythons = (& py -0p 2>$null | Out-String)
        if ($InstalledPythons -match "3\.12") {
            return @{ Exe = "py"; Args = @("-3.12") }
        }
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        $PythonVersion = (& python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null).Trim()
        if ($PythonVersion -eq "3.12") {
            return @{ Exe = "python"; Args = @() }
        }
    }
    throw "Python 3.12 was not found. Run: py install 3.12, then rerun this script."
}

$PythonCommand = Find-Python312
Write-Host "Creating .venv with $($PythonCommand.Exe) $($PythonCommand.Args -join ' ')"
$PythonExe = $PythonCommand.Exe
$PythonArgs = $PythonCommand.Args
& $PythonExe @PythonArgs -m venv .venv

$VenvPython = Join-Path $PWD ".venv\Scripts\python.exe"
& $VenvPython -m pip install --upgrade pip setuptools wheel
& $VenvPython -m pip install torch==2.9.1 torchvision==0.24.1 torchaudio==2.9.1 --index-url $TorchIndexUrl
& $VenvPython -m pip install -r requirements.txt
& $VenvPython -m pip install -r requirements-livestream.txt
& $VenvPython -m pip install -r requirements-omnivoice.txt
& $VenvPython -m pip install --upgrade "huggingface_hub[hf_xet]>=1.23.0,<2.0" "face-alignment==1.5.0"
& $VenvPython -m pip check
if ($LASTEXITCODE -ne 0) {
    throw "Python dependency check failed. Review the pip conflict shown above."
}

# imageio-ffmpeg ships a Windows ffmpeg executable. Copy it to a stable local
# bin directory so LiveTalking's subprocess calls can find `ffmpeg.exe`.
& $VenvPython -m pip install imageio-ffmpeg
$FfmpegSource = (& $VenvPython -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())").Trim()
$BinDirectory = Join-Path $PWD "bin"
New-Item -ItemType Directory -Force -Path $BinDirectory | Out-Null
Copy-Item -Force $FfmpegSource (Join-Path $BinDirectory "ffmpeg.exe")

Write-Host ""
Write-Host "Setup complete. Model checkpoints will download on first use."
Write-Host "In each new PowerShell terminal run:"
Write-Host '  $env:PATH="$PWD\bin;$env:PATH"'
Write-Host '  $env:LIVESTREAM_API_TOKEN="local-test-token"'
Write-Host '  .\.venv\Scripts\python.exe app.py ...'
Write-Host ""
& $VenvPython -c "import torch; print('CUDA:', torch.cuda.is_available()); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'No CUDA GPU')"
& (Join-Path $BinDirectory "ffmpeg.exe") -version
