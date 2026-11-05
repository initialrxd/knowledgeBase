$ErrorActionPreference = 'Stop'
$kbProject = Split-Path -Parent $PSScriptRoot
$kbPython = Join-Path $kbProject '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $kbPython)) { throw 'Run scripts\Install.ps1 first.' }
Set-Location -LiteralPath $kbProject
& $kbPython -X utf8 scripts\manage.py stop-knowledge
if ($LASTEXITCODE -ne 0) { throw 'Standalone knowledge service failed to stop. Check the error above.' }
