[CmdletBinding()]
param(
    [switch]$Start,
    [switch]$Check,
    [string]$Python,
    [string]$Wav,
    [string]$TxPort = 'COM6',
    [string]$RxPort = 'COM7',
    [string]$OutputDir
)

$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
Write-Host 'LoRa comparison: 10 PLAIN trials, then 10 AES-128-GCM trials; five per direction in each group.'
Write-Host 'Same 3-second source and radio settings; user-reported distance 24 inches.'
Write-Host 'Requires heltec_crypto_com6 / heltec_crypto_com7 firmware. No microphone, speaker or PTT activity.'
if (-not $Start -and -not $Check) {
    Write-Host 'No hardware action performed. Use -Check for local checks or -Start for the actual run.'
    return
}
if ($Start -and $Check) { throw 'Choose -Start or -Check, not both.' }
if (-not $Python) { $Python = Join-Path $projectRoot '.venv\Scripts\python.exe' }
if (-not $Wav) { $Wav = Join-Path $projectRoot 'input\source.wav' }
$runnerArguments = @(
    (Join-Path $PSScriptRoot 'lora_crypto_bench.py'),
    '--wav', $Wav, '--tx-port', $TxPort, '--rx-port', $RxPort,
    '--trials-per-mode', '10', '--distance-inches', '24'
)
if ($Check) { $runnerArguments += '--check-only' }
if ($OutputDir) { $runnerArguments += @('--output-dir', $OutputDir) }
& $Python @runnerArguments
if ($LASTEXITCODE -ne 0) {
    throw "LoRa comparison exited with code $LASTEXITCODE; inspect its evidence folder."
}
