$ErrorActionPreference = 'Stop'
$kbProject = Split-Path -Parent $PSScriptRoot
$kbPython = Join-Path $kbProject '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $kbPython)) { throw 'Run scripts\Install.ps1 first.' }
Set-Location -LiteralPath $kbProject
& $kbPython -X utf8 scripts\openwebui.py stop
if ($LASTEXITCODE -ne 0) { throw 'Open WebUI failed to stop. Check the error above.' }
