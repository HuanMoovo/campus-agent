$ErrorActionPreference = 'Stop'
Push-Location (Join-Path $PSScriptRoot 'backend')
try {
    if (-not (Test-Path '.venv\Scripts\python.exe')) { throw 'Run setup.ps1 first.' }
    & '.venv\Scripts\python.exe' -m uvicorn app.main:app --host 127.0.0.1 --port 8000
    if ($LASTEXITCODE -ne 0) { throw 'Backend process exited with an error.' }
} finally { Pop-Location }
