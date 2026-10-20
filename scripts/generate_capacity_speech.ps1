param([Parameter(Mandatory = $true)][string]$OutputPath)

# Offline Windows SAPI only. No provider, network, secrets or customer content.
$syntheticTarget = [System.IO.Path]::GetFullPath($OutputPath)
if (Test-Path -LiteralPath $syntheticTarget) { throw 'Existing speech fixture is preserved.' }
if (-not (Test-Path -LiteralPath ([System.IO.Path]::GetDirectoryName($syntheticTarget)))) {
    throw 'Create the intended benchmark directory first.'
}
Add-Type -AssemblyName System.Speech
$syntheticVoice = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $syntheticVoice.SelectVoice('Microsoft David Desktop')
    $syntheticText = (1..12 | ForEach-Object {
        "Section $_. Today we are testing a video editing service with a practical example. A creator records a clear explanation, chooses the important moments, and checks the final captions. Reliable systems measure their queue before accepting more work. They preserve the original file and protect the account balance when processing fails. We compare time, memory, storage, and output quality. A small experiment teaches us which resource needs attention. These sentences are synthetic benchmark speech, generated locally without an external provider. We should report each measurement honestly and keep estimates separate from observed results."
    }) -join ' '
    $syntheticVoice.SetOutputToWaveFile($syntheticTarget)
    $syntheticVoice.Speak($syntheticText)
} finally {
    $syntheticVoice.Dispose()
}
