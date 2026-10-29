param([Parameter(Mandatory=$true)][string]$Url)
$ErrorActionPreference = 'Stop'
$kbProject = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $kbProject
if (-not (Get-Command ngrok -ErrorAction SilentlyContinue)) { throw 'Install the Windows ngrok agent and configure your own account first. See docs\REMOTE.md.' }
if ($Url -notmatch '^https://[a-zA-Z0-9.-]+/?$') { throw 'Provide your assigned ngrok HTTPS origin, without a path.' }
$kbConfigured = Select-String -LiteralPath '.env' -Pattern '^KB_PUBLIC_BASE_URL=' | Select-Object -First 1
if (-not $kbConfigured -or $kbConfigured.Line.Split('=',2)[1].TrimEnd('/') -ne $Url.TrimEnd('/')) { throw 'Set KB_PUBLIC_BASE_URL in .env to this URL and restart the knowledge service before starting the tunnel.' }
& ngrok http 8766 --url $Url
