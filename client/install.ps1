$ErrorActionPreference = "Stop"
$ClientDir = $PSScriptRoot
Set-Location $ClientDir

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
    throw "Python 3.12 was not found. Install it with: py install 3.12"
}

$Command = Find-Python312
$PythonExe = $Command.Exe
$PythonArgs = $Command.Args
& $PythonExe @PythonArgs -m venv .venv
$Python = Join-Path $ClientDir ".venv\Scripts\python.exe"
& $Python -m pip install --upgrade pip
& $Python -m pip install -r requirements.txt

$FfmpegSource = (& $Python -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())").Trim()
$BinDirectory = Join-Path $ClientDir "bin"
New-Item -ItemType Directory -Force -Path $BinDirectory | Out-Null
Copy-Item -Force $FfmpegSource (Join-Path $BinDirectory "ffmpeg.exe")

$Config = Join-Path $ClientDir "config.json"
if (-not (Test-Path -LiteralPath $Config -PathType Leaf)) {
    Copy-Item (Join-Path $ClientDir "config.example.json") $Config
    Write-Host "Created config.json. Enter the server URL, client ID and stream token before running."
}

Write-Host "OBS Client installation completed."
Write-Host "Next: edit config.json, then run .\run.ps1"
