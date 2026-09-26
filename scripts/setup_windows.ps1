param(
    [string]$TorchIndexUrl = "https://download.pytorch.org/whl/cu128"
)

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

function Find-Python312 {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3.12 -c "import sys; assert sys.version_info >= (3, 12)" 2>$null
        if ($LASTEXITCODE -eq 0) {
            return @{ Exe = "py"; Args = @("-3.12") }
        }
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        & python -c "import sys; assert sys.version_info >= (3, 12)" 2>$null
        if ($LASTEXITCODE -eq 0) {
            return @{ Exe = "python"; Args = @() }
        }
    }
    throw "Python 3.12 was not found. Install it from python.org, enable Add Python to PATH, then reopen PowerShell."
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

# imageio-ffmpeg ships a Windows ffmpeg executable. Copy it to a stable local
# bin directory so LiveTalking's subprocess calls can find `ffmpeg.exe`.
& $VenvPython -m pip install imageio-ffmpeg
$FfmpegSource = (& $VenvPython -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())").Trim()
$BinDirectory = Join-Path $PWD "bin"
New-Item -ItemType Directory -Force -Path $BinDirectory | Out-Null
Copy-Item -Force $FfmpegSource (Join-Path $BinDirectory "ffmpeg.exe")

Write-Host ""
Write-Host "Setup complete. In each new PowerShell terminal run:"
Write-Host '  .\.venv\Scripts\Activate.ps1'
Write-Host '  $env:PATH="$PWD\bin;$env:PATH"'
Write-Host '  $env:LIVESTREAM_API_TOKEN="local-test-token"'
Write-Host ""
& $VenvPython -c "import torch; print('CUDA:', torch.cuda.is_available()); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'No CUDA GPU')"
& (Join-Path $BinDirectory "ffmpeg.exe") -version
