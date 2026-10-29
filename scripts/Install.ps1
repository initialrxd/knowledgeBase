param([switch]$WithOpenWebUI, [switch]$WithoutOCR)
$ErrorActionPreference = 'Stop'
$kbProject = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $kbProject
$env:PYTHONUTF8 = '1'
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    & py -3.11 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.11 is required.' }
}
$kbPython = Join-Path $kbProject '.venv\Scripts\python.exe'
if (Test-Path -LiteralPath 'requirements.lock.txt') {
    & $kbPython -m pip install -r requirements.lock.txt
} else {
    $kbExtra = if ($WithoutOCR) { '.[dev]' } else { '.[dev,ocr]' }
    & $kbPython -m pip install -e $kbExtra
}
if ($LASTEXITCODE -ne 0) { throw 'Knowledge dependency installation failed.' }
& $kbPython -m pip install --no-deps -e .
& $kbPython -m knowledge_service.cli init
& $kbPython -c 'from knowledge_service.config import Settings; s=Settings(); s.prepare(); from knowledge_service.text import encoding; encoding(s.tokenizer); print("Tokenizer ready")'
if ($LASTEXITCODE -ne 0) { throw 'Tokenizer initialization failed; check download access.' }
if ($WithOpenWebUI) {
    if (-not (Test-Path -LiteralPath '.venv-webui\Scripts\python.exe')) { & py -3.11 -m venv .venv-webui }
    $kbWebPython = Join-Path $kbProject '.venv-webui\Scripts\python.exe'
    if (Test-Path -LiteralPath 'requirements-webui.lock.txt') {
        & $kbWebPython -m pip install -r requirements-webui.lock.txt
    } else {
        & $kbWebPython -m pip install 'numpy>=2,<2.3' 'open-webui==0.12.3'
    }
    if ($LASTEXITCODE -ne 0) { throw 'Open WebUI installation failed.' }
}
Write-Output 'Installed. Configure .env, then run scripts\Start-All.ps1.'
