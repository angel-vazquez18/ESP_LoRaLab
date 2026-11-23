param(
    [string]$Port = 'COM4',
    [string]$Python = (Join-Path $env:USERPROFILE '.platformio\penv\Scripts\python.exe')
)
$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "PlatformIO Python not found: $Python. Pass -Python with a Python executable that has pyserial installed."
}
# The script derives captures/ from its own location, not the shell's directory.
& $Python -u (Join-Path $PSScriptRoot 'record_monitor.py') --port $Port
if ($LASTEXITCODE -ne 0) { throw "Recording console exited with code $LASTEXITCODE" }
