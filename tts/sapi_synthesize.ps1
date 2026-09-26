param(
    [Parameter(Mandatory = $true)][string]$TextPath,
    [Parameter(Mandatory = $true)][string]$OutputPath,
    [string]$Voice = ""
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Speech
$Synthesizer = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    if ($Voice) {
        $Synthesizer.SelectVoice($Voice)
    }
    $Text = [System.IO.File]::ReadAllText($TextPath, [System.Text.Encoding]::UTF8)
    $Synthesizer.SetOutputToWaveFile($OutputPath)
    $Synthesizer.Speak($Text)
}
finally {
    $Synthesizer.Dispose()
}
