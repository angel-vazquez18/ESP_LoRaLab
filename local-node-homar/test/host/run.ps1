param([string]$Compiler = 'C:\msys64\ucrt64\bin\g++.exe')
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$testBuild = Join-Path $projectRoot '.host-test'
New-Item -ItemType Directory -Path $testBuild -Force | Out-Null
$env:PATH = [IO.Path]::GetDirectoryName($Compiler) + ';' + $env:PATH
& $Compiler -std=c++17 -Wall -Wextra -Werror "-I$projectRoot\include" "$PSScriptRoot\diagnostics_test.cpp" -o "$testBuild\diagnostics_test.exe"
if ($LASTEXITCODE -ne 0) { throw 'Diagnostics test compilation failed' }
& "$testBuild\diagnostics_test.exe"
if ($LASTEXITCODE -ne 0) { throw 'Diagnostics tests failed' }
& $Compiler -std=c++17 -Wall -Wextra -Werror "-I$projectRoot\include" "-I$projectRoot\lib\chunking" "$PSScriptRoot\chunker_test.cpp" "$projectRoot\lib\chunking\chunker.cpp" -o "$testBuild\chunker_test.exe"
if ($LASTEXITCODE -ne 0) { throw 'Chunker test compilation failed' }
& "$testBuild\chunker_test.exe"
if ($LASTEXITCODE -ne 0) { throw 'Chunker tests failed' }
foreach ($variant in @('esp32dev', 'mic_only', 'speaker_only', 'serial_only', 'heltec_v4')) {
  $defines = @()
  if ($variant -eq 'heltec_v4') {
    $defines += '-DAUDIO_BOARD_HELTEC_V4=1'
    $defines += '-DCONFIG_IDF_TARGET_ESP32S3=1'
  }
  if ($variant -in @('speaker_only', 'serial_only')) { $defines += '-DAUDIO_ENABLE_MIC=0' }
  if ($variant -in @('mic_only', 'serial_only')) { $defines += '-DAUDIO_ENABLE_SPEAKER=0' }
  & $Compiler -std=gnu++17 -Wall -Wextra -Werror @defines "-I$PSScriptRoot\stubs" "-I$projectRoot\include" "-I$projectRoot\lib\audio" "$PSScriptRoot\audio_test.cpp" "$projectRoot\lib\audio\audio_manager.cpp" -o "$testBuild\audio_$variant.exe"
  if ($LASTEXITCODE -ne 0) { throw "Audio test compilation failed: $variant" }
  & "$testBuild\audio_$variant.exe"
  if ($LASTEXITCODE -ne 0) { throw "Audio tests failed: $variant" }
}
