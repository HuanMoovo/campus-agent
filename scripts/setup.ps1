param([switch]$FullRag)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
function Assert-Exit([string]$step) { if ($LASTEXITCODE -ne 0) { throw "$step failed (exit $LASTEXITCODE)" } }

Push-Location (Join-Path $projectRoot 'backend')
try {
    if (-not (Test-Path '.venv\Scripts\python.exe')) {
        python -m venv .venv
        Assert-Exit 'Create virtual environment'
    }
    $requirementsFile = if ($FullRag) { 'requirements-ai.txt' } else { 'requirements.txt' }
    & '.venv\Scripts\python.exe' -m pip install -r $requirementsFile
    Assert-Exit 'Install backend dependencies'
    if (-not (Test-Path '.env')) {
        $tokenBytes = New-Object byte[] 32
        $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
        try { $rng.GetBytes($tokenBytes) } finally { $rng.Dispose() }
        $token = [Convert]::ToBase64String($tokenBytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
        $configuration = (Get-Content '.env.example' -Raw).Replace('change-this-before-deployment', $token)
        if ($FullRag) { $configuration = $configuration.Replace('ENABLE_RAG=false', 'ENABLE_RAG=true') }
        [System.IO.File]::WriteAllText((Join-Path (Get-Location) '.env'), $configuration, [System.Text.UTF8Encoding]::new($false))
        Write-Host 'Created backend/.env with a random admin token. Copy its ADMIN_TOKEN value into the app Settings page.'
    }
} finally { Pop-Location }

Push-Location (Join-Path $projectRoot 'frontend')
try {
    npm.cmd install --cache .npm-cache
    Assert-Exit 'Install frontend dependencies'
    npm.cmd run build
    Assert-Exit 'Build frontend'
} finally { Pop-Location }
Write-Host 'Setup finished. Run start-backend.ps1 and start-frontend.ps1 in two terminals.'
