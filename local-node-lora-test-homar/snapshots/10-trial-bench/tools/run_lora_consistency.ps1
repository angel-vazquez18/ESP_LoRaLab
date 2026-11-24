[CmdletBinding()]
param(
    [switch]$Start,
    [switch]$Check,
    [string]$RunnerPython,
    [string]$ReportPython,
    [string]$Wav,
    [string]$OutputDir,
    [string]$TxPort = 'COM6',
    [string]$RxPort = 'COM7'
)

$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$runner = Join-Path $PSScriptRoot 'lora_transfer_bench.py'
if (-not $RunnerPython) { $RunnerPython = Join-Path $projectRoot '.venv\Scripts\python.exe' }
if (-not $ReportPython) { $ReportPython = $RunnerPython }
if (-not $Wav) {
    $Wav = Join-Path $projectRoot 'input\source.wav'
}

Write-Host 'Prepared LoRa consistency test: 10 alternating trials, 5 per direction, user-reported separation 24 inches.'
Write-Host 'Both OLEDs show the current test counter. Microphone, speaker and PTT stay inactive.'

# This gate must remain before every process invocation. Default invocation only
# describes the plan; it neither enumerates/opens serial devices nor starts RF.
if (-not $Start -and -not $Check) {
    Write-Host 'No hardware actions performed. Use -Check for local dependency/source/protocol checks only.'
    Write-Host 'Use -Start only when ready to run on the already-flashed, identified boards with antennas connected.'
    Write-Host 'Example: .\tools\run_lora_consistency.ps1 -Start'
    return
}
if ($Start -and $Check) {
    throw 'Choose -Check (local-only) or -Start (hardware run), not both.'
}

$runnerArguments = @(
    $runner, '--wav', $Wav, '--tx-port', $TxPort, '--rx-port', $RxPort,
    '--trials', '10', '--alternate', '--continue-on-failure', '--oled-progress',
    '--distance-inches', '24', '--report-python', $ReportPython
)
if ($OutputDir) { $runnerArguments += @('--output-dir', $OutputDir) }
if ($Check) { $runnerArguments += '--check-only' }

& $RunnerPython @runnerArguments
if ($LASTEXITCODE -ne 0) {
    throw "LoRa consistency command failed with exit code $LASTEXITCODE. See saved evidence when a run was started."
}
