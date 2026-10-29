$ErrorActionPreference = 'Stop'
$kbProject = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $kbProject
& (Join-Path $kbProject '.venv\Scripts\python.exe') -m knowledge_service.cli stop
# Open WebUI is a separate subprocess. Validate its command line before stopping it.
$kbPidFile = Join-Path $kbProject 'logs\openwebui-child.pid'
if (Test-Path -LiteralPath $kbPidFile) {
    $kbChildId = [int](Get-Content -LiteralPath $kbPidFile -Raw).Trim()
    $kbProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$kbChildId" -ErrorAction SilentlyContinue
    $kbExpected = Join-Path $kbProject '.venv-webui\Scripts\open-webui.exe'
    if ($kbProcess -and $kbProcess.CommandLine -like "*$kbExpected*") {
        Stop-Process -Id $kbChildId
        Write-Output 'Open WebUI stopped.'
    } elseif ($kbProcess) {
        throw 'PID no longer belongs to this Open WebUI process; refusing to stop it.'
    }
}
