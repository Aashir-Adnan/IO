# IO one-time local setup. Run from repo root:
#   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
# Prerequisites you must install yourself first (GUI installers):
#   - Docker Desktop  (https://www.docker.com/products/docker-desktop/) - must be RUNNING
#   - Ollama          (https://ollama.com/download/windows)
$ErrorActionPreference = "Stop"

Write-Host "1/5  Installing uv (if missing)..."
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    $env:Path = "$HOME\.local\bin;$env:Path"
}

Write-Host "2/5  Pulling Ollama models..."
ollama pull llama3.2:3b
ollama pull nomic-embed-text

Write-Host "3/5  Starting PostgreSQL (Docker)..."
docker compose up -d

Write-Host "4/5  Waiting for PostgreSQL, then enabling pgvector..."
$deadline = (Get-Date).AddSeconds(60)
do {
    Start-Sleep -Seconds 2
    $ready = $false
    try { docker compose exec -T db pg_isready -U io | Out-Null; $ready = ($LASTEXITCODE -eq 0) } catch {}
} until ($ready -or (Get-Date) -gt $deadline)
docker compose exec -T db psql -U io -d io      -c "CREATE EXTENSION IF NOT EXISTS vector;"
docker compose exec -T db psql -U io -d io_test -c "CREATE EXTENSION IF NOT EXISTS vector;"

Write-Host "5/5  Writing .env (if missing)..."
if (-not (Test-Path .env)) { Copy-Item .env.example .env }

Write-Host "`nRunning environment check..."
& "$PSScriptRoot\check-env.ps1"
