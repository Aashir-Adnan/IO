<#
  dev.ps1 - single on/off switch for the whole IO stack.

    .\dev.ps1 up          start Postgres + Ollama check + migrate + io service
    .\dev.ps1 up -Window  ... and also open the desktop window
    .\dev.ps1 down        stop the io service and Postgres
    .\dev.ps1 down -Wipe  ... and delete the database volume
    .\dev.ps1 restart
    .\dev.ps1 status
    .\dev.ps1 logs        tail the service log
    .\dev.ps1 app         open the desktop window (service must be up)
    .\dev.ps1 listen      voice mode (service must be up)
    .\dev.ps1 doctor      io doctor
    .\dev.ps1 test [...]  run the test suite against io_test
    .\dev.ps1 install     put an "IO" shortcut on the Desktop (double-click =
                          whole stack up + window; close window = stack down)
#>
param(
  [Parameter(Position = 0)][string]$Command = "help",
  [switch]$Window,
  [switch]$Wipe,
  [Parameter(ValueFromRemainingArguments = $true)]$Rest
)

# Continue, not Stop: native tools (psql NOTICE, docker) write to stderr on
# success and 'Stop' would abort. Critical steps check $LASTEXITCODE explicitly.
$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$Port = 8765
$StateDir = Join-Path $Root ".io-dev"
$PidFile = Join-Path $StateDir "serve.pid"
$LogFile = Join-Path $StateDir "serve.log"
$ErrFile = Join-Path $StateDir "serve.err.log"
$TestDbUrl = "postgresql+psycopg://io:io@localhost:5432/io_test"

function Info($m) { Write-Host "> $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "OK   $m" -ForegroundColor Green }
function Warn($m) { Write-Host "WARN $m" -ForegroundColor Yellow }

function Test-Listen($p) {
  $null -ne (Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue)
}

function Stop-Listen($p) {
  $c = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue
  if ($c) {
    $ids = $c.OwningProcess | Select-Object -Unique
    foreach ($id in $ids) {
      try { Stop-Process -Id $id -Force -ErrorAction Stop } catch {}
    }
  }
}

function Test-Http($url) {
  # curl.exe is reliable on Win10+; PS 5.1 Invoke-WebRequest is slow/flaky here.
  & curl.exe -s -o NUL --max-time 2 $url 2>$null
  return ($LASTEXITCODE -eq 0)
}

function Wait-Http($url, $timeoutSec = 30) {
  $deadline = (Get-Date).AddSeconds($timeoutSec)
  while ((Get-Date) -lt $deadline) {
    if (Test-Http $url) { return $true }
    Start-Sleep -Milliseconds 500
  }
  return $false
}

function Ensure-Ollama {
  if (Test-Http "http://127.0.0.1:11434/api/version") {
    Ok "Ollama reachable (embeddings)"
    return
  }

  Warn "Ollama not reachable - starting it (needed for embeddings)"
  try {
    Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden
  } catch {
    Warn "could not launch 'ollama' - install it or start it yourself"
    return
  }
  if (Wait-Http "http://localhost:11434/api/version" 15) { Ok "Ollama started" }
  else { Warn "Ollama still down - embeddings will fail until it is running" }
}

function Ensure-Postgres {
  Info "PostgreSQL (docker compose up -d)"
  docker compose up -d
  if ($LASTEXITCODE -ne 0) { throw "docker compose failed - is Docker Desktop running?" }

  Info "waiting for PostgreSQL"
  $ready = $false
  foreach ($i in 1..60) {
    if (-not $ready) {
      docker compose exec -T db pg_isready -U io *> $null
      if ($LASTEXITCODE -eq 0) { $ready = $true } else { Start-Sleep -Seconds 1 }
    }
  }
  if (-not $ready) { throw "PostgreSQL did not become ready" }
  docker compose exec -T db psql -U io -d io      -c "CREATE EXTENSION IF NOT EXISTS vector;" 2>$null | Out-Null
  docker compose exec -T db psql -U io -d io_test -c "CREATE EXTENSION IF NOT EXISTS vector;" 2>$null | Out-Null
  Ok "PostgreSQL ready (databases io, io_test)"
}

function Do-Up {
  New-Item -ItemType Directory -Force $StateDir | Out-Null
  Ensure-Postgres
  Ensure-Ollama

  Info "alembic upgrade head"
  $mig = & uv run alembic upgrade head 2>&1
  if ($LASTEXITCODE -ne 0) {
    $mig | ForEach-Object { Write-Host $_ }
    throw "migration failed"
  }
  Ok "schema at head"

  if (Test-Listen $Port) {
    Warn "port $Port busy - stopping the old listener"
    Stop-Listen $Port
    Start-Sleep 1
  }
  Info "starting io service (background)"
  $spArgs = @{
    FilePath               = "uv"
    ArgumentList           = @("run", "io", "serve")
    RedirectStandardOutput = $LogFile
    RedirectStandardError  = $ErrFile
    WindowStyle            = "Hidden"
    PassThru               = $true
  }
  $p = Start-Process @spArgs
  $p.Id | Out-File -Encoding ascii $PidFile
  if (Wait-Http "http://localhost:$Port/health" 40) {
    Ok "io service on http://localhost:$Port"
  } else {
    Warn "service did not answer /health - see $LogFile and $ErrFile"
  }

  Write-Host ""
  Ok "IO is up.  UI: http://localhost:$Port/app/"
  if ($Window) {
    Info "opening desktop window - close it to shut the whole stack down"
    uv run io run
    Write-Host ""
    Do-Down
  } else {
    Write-Host "     .\dev.ps1 app      open the desktop window"
    Write-Host "     .\dev.ps1 listen   voice mode"
    Write-Host "     .\dev.ps1 logs     tail the service log"
    Write-Host "     .\dev.ps1 down     stop everything"
  }
}

function Do-Down {
  Info "stopping io service"
  Stop-Listen $Port
  if (Test-Path $PidFile) {
    try { Stop-Process -Id ([int](Get-Content $PidFile)) -Force -ErrorAction Stop } catch {}
    Remove-Item $PidFile -ErrorAction SilentlyContinue
  }
  Info "stopping PostgreSQL"
  if ($Wipe) {
    docker compose down -v
    Warn "database volume deleted"
  } else {
    docker compose down
  }
  Ok "IO is down."
}

function Do-Status {
  if (Test-Listen $Port) {
    Write-Host "io service : up  (http://localhost:$Port)"
  } else {
    Write-Host "io service : down"
  }
  if (Test-Http "http://127.0.0.1:11434/api/version") { $ollama = "up" } else { $ollama = "down" }
  Write-Host "Ollama     : $ollama"
  Write-Host "PostgreSQL :"
  docker compose ps
}

function Do-Build {
  if (-not (Test-Path "$Root\assets\io-logo.png")) {
    Warn "assets\io-logo.png is missing - add the logo there first."; return
  }
  Info "generating icon"
  uv run python "$Root\scripts\make_icon.py"
  Info "running PyInstaller (this takes a few minutes)"
  uv run pyinstaller "$Root\packaging\io.spec" --noconfirm
  $exe = "$Root\dist\IO\IO.exe"
  if (Test-Path $exe) { Ok "built: $exe" } else { Warn "build failed - see PyInstaller output" }
}

function Do-Install {
  $exe = "$Root\dist\IO\IO.exe"
  if (-not (Test-Path $exe)) { Do-Build }
  if (-not (Test-Path $exe)) { return }
  $desktop = [Environment]::GetFolderPath("Desktop")
  $lnk = Join-Path $desktop "IO.lnk"
  $w = New-Object -ComObject WScript.Shell
  $s = $w.CreateShortcut($lnk)
  $s.TargetPath = $exe
  $s.WorkingDirectory = $Root
  $s.IconLocation = "$Root\assets\io.ico"
  $s.Description = "IO - local-first assistant"
  $s.Save()
  Ok "shortcut created: $lnk  ->  $exe"
  Write-Host "     Double-click it to launch. A second launch just opens the"
  Write-Host "     running window in your browser (single-instance)."
}

function Show-Help {
  Write-Host "dev.ps1 - IO stack on/off switch"
  Write-Host ""
  Write-Host "  .\dev.ps1 up [-Window]     start Postgres, Ollama check, migrate, io service"
  Write-Host "  .\dev.ps1 down [-Wipe]     stop the service and Postgres (-Wipe drops the DB volume)"
  Write-Host "  .\dev.ps1 restart"
  Write-Host "  .\dev.ps1 status"
  Write-Host "  .\dev.ps1 logs            tail the service log"
  Write-Host "  .\dev.ps1 app             open the desktop window"
  Write-Host "  .\dev.ps1 listen          voice mode"
  Write-Host "  .\dev.ps1 doctor"
  Write-Host "  .\dev.ps1 test [pytest args]"
  Write-Host "  .\dev.ps1 build           generate the icon + PyInstaller bundle (dist\IO\IO.exe)"
  Write-Host "  .\dev.ps1 install         Desktop 'IO' shortcut -> dist\IO\IO.exe (builds if needed)"
}

switch ($Command.ToLower()) {
  "up"      { Do-Up }
  "down"    { Do-Down }
  "restart" { Do-Down; Write-Host ""; Do-Up }
  "status"  { Do-Status }
  "logs" {
    if (Test-Path $LogFile) { Get-Content $LogFile -Tail 40 -Wait }
    else { Warn "no log yet - run .\dev.ps1 up" }
  }
  "app" {
    if (Test-Listen $Port) { Start-Process "http://localhost:$Port/app/" }
    else { Warn "service is down - run .\dev.ps1 up first" }
  }
  "listen"  { uv run io listen @Rest }
  "doctor"  { uv run io doctor }
  "build"   { Do-Build }
  "install" { Do-Install }
  "test" {
    Ensure-Postgres
    $env:IO_TEST_DATABASE_URL = $TestDbUrl
    uv run pytest @Rest
  }
  default   { Show-Help }
}
