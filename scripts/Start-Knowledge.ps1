param([switch]$Background)
$ErrorActionPreference = 'Stop'
$kbProject = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $kbProject
$env:PYTHONUTF8 = '1'
$kbPython = Join-Path $kbProject '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $kbPython)) { throw 'Run scripts\Install.ps1 first.' }
try {
    $kbHealth = Invoke-RestMethod -Uri 'http://127.0.0.1:8765/health' -TimeoutSec 2
    if ($kbHealth.service -eq 'knowledge-admin') {
        Write-Output 'Knowledge service is already running.'
        return
    }
} catch { }
if ($Background) {
    New-Item -ItemType Directory -Path (Join-Path $kbProject 'logs') -Force | Out-Null
    $kbProcess = Start-Process -FilePath $kbPython -ArgumentList '-X','utf8','-m','knowledge_service.cli','serve' -WorkingDirectory $kbProject -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $kbProject 'logs\knowledge.out.log') -RedirectStandardError (Join-Path $kbProject 'logs\knowledge.err.log')
    $kbProcess.Id | Set-Content -LiteralPath (Join-Path $kbProject 'logs\knowledge.pid')
    Write-Output "Knowledge service launched (PID $($kbProcess.Id)); tools http://127.0.0.1:8766"
} else {
    & $kbPython -X utf8 -m knowledge_service.cli serve
}
