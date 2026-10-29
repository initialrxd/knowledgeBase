$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'Start-Manager.ps1') -Background
& (Join-Path $PSScriptRoot 'Start-OpenWebUI.ps1') -Background
