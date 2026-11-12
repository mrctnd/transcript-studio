$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$pythonExe = Join-Path $projectRoot '.venv312/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) {
    & py -3.12 -m venv .venv312
    if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.12 and try again.' }
}
& $pythonExe -m pip install -r requirements-lock.txt
if ($LASTEXITCODE -ne 0) { throw 'Python dependencies could not be installed.' }
Push-Location -LiteralPath (Join-Path $projectRoot 'frontend')
try {
    & npm.cmd ci
    if ($LASTEXITCODE -ne 0) { throw 'Frontend dependencies could not be installed.' }
    & npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'The frontend build failed.' }
} finally { Pop-Location }
Write-Host 'Setup complete. Start the app with .\scripts\start.ps1'
