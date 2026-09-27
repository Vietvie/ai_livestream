$ErrorActionPreference = "Stop"
$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $ProjectDir

function Find-Python312 {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $Installed = (& py -0p 2>$null | Out-String)
        if ($Installed -match "3\.12") {
            return @{ Exe = "py"; Args = @("-3.12") }
        }
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        $Version = (& python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null).Trim()
        if ($Version -eq "3.12") {
            return @{ Exe = "python"; Args = @() }
        }
    }
    throw "Python 3.12 was not found. Run: py install 3.12"
}

$Command = Find-Python312
$PythonExe = $Command.Exe
$PythonArgs = $Command.Args
& $PythonExe @PythonArgs -m venv .client-venv
$Python = Join-Path $ProjectDir ".client-venv\Scripts\python.exe"
& $Python -m pip install --upgrade pip
& $Python -m pip install -r requirements-client.txt

$FfmpegSource = (& $Python -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())").Trim()
$BinDirectory = Join-Path $ProjectDir "bin"
New-Item -ItemType Directory -Force -Path $BinDirectory | Out-Null
Copy-Item -Force $FfmpegSource (Join-Path $BinDirectory "ffmpeg.exe")

Write-Host "OBS relay client is ready. No CUDA or AI model is required."
Write-Host 'Set $env:LIVESTREAM_API_TOKEN, then run scripts\run_obs_client_windows.ps1.'
