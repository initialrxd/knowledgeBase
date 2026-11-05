param([switch]$Background)
$ErrorActionPreference = 'Stop'
$kbProject = Split-Path -Parent $PSScriptRoot
$kbPython = Join-Path $kbProject '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $kbPython)) { throw 'Run scripts\Install.ps1 first.' }
Set-Location -LiteralPath $kbProject
$kbArguments = @('-X', 'utf8', 'scripts\openwebui.py', 'start')
if ($Background) { $kbArguments += '--background' }
& $kbPython @kbArguments
if ($LASTEXITCODE -ne 0) { throw 'Open WebUI failed to start. Check the error above.' }
