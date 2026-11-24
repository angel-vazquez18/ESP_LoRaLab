param([string]$Compiler = 'g++.exe')
$ErrorActionPreference = 'Stop'
$Compiler = (Get-Command $Compiler -ErrorAction Stop).Source
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
& $Compiler -std=c++17 -Wall -Wextra -Werror "-I$projectRoot\include" "-I$projectRoot\lib\chunking" "$PSScriptRoot\radio_frame_test.cpp" "$projectRoot\lib\chunking\chunker.cpp" -o "$testBuild\radio_frame_test.exe"
if ($LASTEXITCODE -ne 0) { throw 'Radio frame test compilation failed' }
& "$testBuild\radio_frame_test.exe"
if ($LASTEXITCODE -ne 0) { throw 'Radio frame tests failed' }
& $Compiler -std=c++17 -Wall -Wextra -Werror "-I$projectRoot\include" "$PSScriptRoot\lora_display_model_test.cpp" -o "$testBuild\lora_display_model_test.exe"
if ($LASTEXITCODE -ne 0) { throw 'LoRa display model test compilation failed' }
& "$testBuild\lora_display_model_test.exe"
if ($LASTEXITCODE -ne 0) { throw 'LoRa display model tests failed' }

& $Compiler -std=c++17 -Wall -Wextra -Werror "-I$projectRoot\include" "-I$projectRoot\lib\chunking" "$PSScriptRoot\crypto_radio_frame_test.cpp" -o "$testBuild\crypto_radio_frame_test.exe"
if ($LASTEXITCODE -ne 0) { throw 'Crypto metadata test compilation failed' }
& "$testBuild\crypto_radio_frame_test.exe"
if ($LASTEXITCODE -ne 0) { throw 'Crypto metadata tests failed' }
