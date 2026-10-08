$ErrorActionPreference = 'Stop'
Push-Location (Join-Path (Split-Path $PSScriptRoot -Parent) 'backend')
try {
    & '.venv\Scripts\python.exe' -c 'from langgraph.graph import StateGraph; print("LangGraph import verified")'
    if ($LASTEXITCODE -ne 0) { throw 'LangGraph is not installed correctly.' }
    & '.venv\Scripts\python.exe' -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw 'Backend tests failed.' }
} finally { Pop-Location }
Push-Location (Join-Path (Split-Path $PSScriptRoot -Parent) 'frontend')
try {
    npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
} finally { Pop-Location }
