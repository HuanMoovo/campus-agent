$ErrorActionPreference = 'Stop'
Push-Location (Join-Path $PSScriptRoot 'frontend')
try {
    npm.cmd run dev
    if ($LASTEXITCODE -ne 0) { throw 'Frontend process exited with an error.' }
} finally { Pop-Location }
