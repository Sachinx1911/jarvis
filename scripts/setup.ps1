# Jarvis setup for Windows. Run from the repo root:  powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

if (-not (Test-Path .venv)) {
    py -3.12 -m venv .venv
}
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\jarvis.exe init

Write-Host ""
Write-Host "Next:"
Write-Host "  .\.venv\Scripts\jarvis.exe secret set anthropic_api_key   # stored in Windows Credential Manager"
Write-Host "  .\.venv\Scripts\python.exe -m pytest"
Write-Host "  .\.venv\Scripts\jarvis.exe chat"
