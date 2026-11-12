param([int]$Port = 8765, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$pythonExe = Join-Path $projectRoot '.venv312/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) { throw 'Run .\scripts\setup.ps1 first.' }
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot 'frontend/dist/index.html'))) { throw 'The frontend build is missing. First run .\scripts\setup.ps1.' }
if (-not $NoBrowser) { Start-Process "http://127.0.0.1:$Port" }
& $pythonExe -m uvicorn backend.main:app --host 127.0.0.1 --port $Port
