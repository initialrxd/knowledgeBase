param([int]$Port = 8767)
$ErrorActionPreference = 'Stop'
$kbProject = Split-Path -Parent $PSScriptRoot
$kbPython = Join-Path $kbProject '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $kbPython)) { throw 'Run scripts\Install.ps1 first.' }
Set-Location -LiteralPath $kbProject
& $kbPython -X utf8 scripts\manage.py stop-manager --port $Port
if ($LASTEXITCODE -ne 0) { throw 'Knowledge manager failed to stop. Check the error above.' }
