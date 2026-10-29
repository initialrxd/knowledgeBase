param([switch]$WithOpenWebUI, [switch]$WithoutOCR)
$ErrorActionPreference = 'Stop'
$kbProject = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $kbProject
$env:PYTHONUTF8 = '1'
$kbArguments = @('scripts/manage.py', 'install')
if ($WithOpenWebUI) { $kbArguments += '--with-openwebui' }
if ($WithoutOCR) { $kbArguments += '--without-ocr' }
& py -3.11 @kbArguments
if ($LASTEXITCODE -ne 0) { throw 'Installation failed. Check the error above.' }
