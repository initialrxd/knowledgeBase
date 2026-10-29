param([switch]$Background)
$ErrorActionPreference = 'Stop'
$kbProject = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $kbProject
$env:PYTHONUTF8 = '1'
$kbPython = Join-Path $kbProject '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath (Join-Path $kbProject '.venv-webui\Scripts\python.exe'))) { throw 'Run scripts\Install.ps1 -WithOpenWebUI first.' }
try {
    $kbHealth = Invoke-RestMethod -Uri 'http://127.0.0.1:8080/health' -TimeoutSec 2
    if ($kbHealth.status -eq $true) {
        Write-Output 'Open WebUI is already running.'
        return
    }
} catch { }
if ($Background) {
    New-Item -ItemType Directory -Path (Join-Path $kbProject 'logs') -Force | Out-Null
    $kbProcess = Start-Process -FilePath $kbPython -ArgumentList '-X','utf8','scripts\run_openwebui.py' -WorkingDirectory $kbProject -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $kbProject 'logs\openwebui.out.log') -RedirectStandardError (Join-Path $kbProject 'logs\openwebui.err.log')
    $kbProcess.Id | Set-Content -LiteralPath (Join-Path $kbProject 'logs\openwebui.pid')
    Write-Output "Open WebUI launched (PID $($kbProcess.Id)); http://127.0.0.1:8080"
} else {
    & $kbPython -X utf8 scripts\run_openwebui.py
}
