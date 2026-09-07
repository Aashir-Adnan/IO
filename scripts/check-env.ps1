# IO environment check. Run from repo root:  powershell -ExecutionPolicy Bypass -File scripts\check-env.ps1
# Windows PowerShell 5.1 compatible (does not require pwsh).
$ErrorActionPreference = "Stop"
$script:ok = $true

function Check($name, $script) {
    try { & $script | Out-Null; Write-Host "OK   $name" -ForegroundColor Green }
    catch { Write-Host ("FAIL $name -- {0}" -f $_.Exception.Message) -ForegroundColor Red; $script:ok = $false }
}

Check "uv on PATH" { uv --version }
Check "Docker daemon" { docker info }
Check "Ollama reachable" {
    if ((Invoke-WebRequest http://localhost:11434/api/version -UseBasicParsing).StatusCode -ne 200) { throw "no 200" }
}
Check "model llama3.2:3b pulled" {
    if (-not (ollama list | Select-String "llama3.2:3b")) { throw "not pulled" }
}
Check "model nomic-embed-text pulled" {
    if (-not (ollama list | Select-String "nomic-embed-text")) { throw "not pulled" }
}
Check "Postgres db 'io' reachable" { docker compose exec -T db psql -U io -d io -c "SELECT 1" }
Check "Postgres db 'io_test' reachable" { docker compose exec -T db psql -U io -d io_test -c "SELECT 1" }
Check "pgvector in 'io'" {
    if (-not (docker compose exec -T db psql -U io -d io -c "\dx" | Select-String "vector")) { throw "extension missing" }
}
Check "pgvector in 'io_test'" {
    if (-not (docker compose exec -T db psql -U io -d io_test -c "\dx" | Select-String "vector")) { throw "extension missing" }
}

if (-not $script:ok) { Write-Host "`nEnvironment NOT ready." -ForegroundColor Red; exit 1 }
Write-Host "`nEnvironment ready." -ForegroundColor Green
