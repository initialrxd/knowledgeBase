$ErrorActionPreference = 'Stop'
$kbProject = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $kbProject
$env:PYTHONUTF8 = '1'
& py -3.11 -X utf8 scripts\openwebui.py install
if ($LASTEXITCODE -ne 0) { throw 'Open WebUI installation failed. Check the error above.' }
