param([switch]$Background, [switch]$NoBrowser, [int]$Port = 8767)
$ErrorActionPreference = 'Stop'
$kbProject = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $kbProject
$kbPython = Join-Path $kbProject '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $kbPython)) { throw 'Run scripts\Install.ps1 first.' }
if (-not (Test-Path -LiteralPath (Join-Path $kbProject 'knowledge_service\static\index.html'))) {
    throw 'Build the UI first: cd frontend; npm install; npm run build'
}
$kbRunning = $false
try {
    $kbHealth = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 2
    if ($kbHealth.service -ne 'knowledge-manager') { throw 'Port is owned by another application.' }
    $kbRunning = $true
} catch { if ($_.Exception.Message -eq 'Port is owned by another application.') { throw } }
if (-not $kbRunning) {
    if (-not $Background) {
        & $kbPython -X utf8 -m knowledge_service.manager --port $Port
        exit $LASTEXITCODE
    }
    $kbLogDir = Join-Path $kbProject 'logs'
    New-Item -ItemType Directory -Path $kbLogDir -Force | Out-Null
    $kbProcess = Start-Process -FilePath $kbPython -ArgumentList '-X','utf8','-m','knowledge_service.manager','--port',"$Port" -WorkingDirectory $kbProject -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $kbLogDir 'manager.out.log') -RedirectStandardError (Join-Path $kbLogDir 'manager.err.log')
    $kbProcess.Id | Set-Content -LiteralPath (Join-Path $kbLogDir 'manager.pid')
    $kbDeadline = (Get-Date).AddSeconds(45)
    while ((Get-Date) -lt $kbDeadline) {
        if ($kbProcess.HasExited) { throw 'Manager failed to start; see logs\manager.err.log.' }
        try {
            $kbHealth = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 1
            if ($kbHealth.service -eq 'knowledge-manager') { $kbRunning = $true; break }
        } catch { }
        Start-Sleep -Milliseconds 300
    }
    if (-not $kbRunning) { throw 'Manager startup timed out; see logs\manager.err.log.' }
}
if (-not $NoBrowser) {
    $kbSecrets = Get-Content -LiteralPath (Join-Path $kbProject 'manager-data\secrets.json') -Raw | ConvertFrom-Json
    $kbLogin = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:$Port/manager/api/bootstrap" -Headers @{Authorization = "Bearer $($kbSecrets.manager_admin)"}
    Start-Process "http://127.0.0.1:$Port/#login=$($kbLogin.token)"
}
Write-Output "Knowledge console ready: http://127.0.0.1:$Port"
