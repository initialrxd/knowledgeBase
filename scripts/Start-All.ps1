$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'Start-Knowledge.ps1') -Background
& (Join-Path $PSScriptRoot 'Start-OpenWebUI.ps1') -Background
