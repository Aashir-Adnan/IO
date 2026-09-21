<#
  update.ps1 - apply an IO update. Started detached by the service
  (POST /update/apply), which then exits: a running process can't replace its
  own venv or exe.

    1. wait for IO to exit
    2. snapshot the database (keep the last 3)
    3. move any config.toml edits into config.local.toml
    4. git pull --ff-only          (aborts if tracked files are dirty/diverged)
    5. uv sync
    6. rebuild the exe            (only if dist\IO\IO.exe exists)
    7. relaunch IO                (always - the old version if the update failed)

  Migrations apply on the next launch. On a failure in 4-6 the checkout is
  reset to the commit it started on (safe: the tree was verified clean, so only
  the pulled commits are discarded). Log: ~\.local\share\io\update.log
#>
param(
  [Parameter(Mandatory = $true)][string]$Root,
  [int]$ProcessId = 0,
  [ValidateSet("exe", "dev")][string]$Relaunch = "dev",
  [switch]$NoRelaunch   # verification aid: do everything except relaunch
)

$ErrorActionPreference = "Continue"
Set-Location $Root

$DataDir = Join-Path $HOME ".local\share\io"
$Backups = Join-Path $DataDir "backups"
$Log = Join-Path $DataDir "update.log"
New-Item -ItemType Directory -Force $Backups | Out-Null

function Log($m) {
  "$(Get-Date -Format s)  $m" | Add-Content -Path $Log
  Write-Host $m
}

function Step($what, [scriptblock]$cmd) {
  & $cmd
  if ($LASTEXITCODE -ne 0) { throw "$what failed (exit $LASTEXITCODE)" }
}

if ($ProcessId -gt 0) {
  try { Wait-Process -Id $ProcessId -Timeout 30 -ErrorAction Stop } catch { }
}

$old = (git rev-parse HEAD).Trim()
$ok = $false
try {
  # 2. snapshot. cmd /c keeps the SQL as raw bytes (PowerShell 5.1's > re-encodes).
  $dump = Join-Path $Backups ("pre-update-" + $old.Substring(0, 7) + ".sql")
  $compose = Join-Path $Root "docker-compose.yml"
  cmd /c "docker compose -p io -f `"$compose`" exec -T db pg_dump -U io io > `"$dump`" 2>nul"
  if ($LASTEXITCODE -ne 0 -or -not (Test-Path $dump) -or (Get-Item $dump).Length -lt 100) {
    throw "couldn't snapshot the database (is the IO database container running?)"
  }
  Get-ChildItem $Backups -Filter "pre-update-*.sql" | Sort-Object LastWriteTime -Descending |
    Select-Object -Skip 3 | Remove-Item -Force
  Log "snapshot: $dump"

  # 3. keep user settings out of the tracked file
  if (-not (Test-Path (Join-Path $Root "config.local.toml"))) {
    uv run io update --localize | Out-Null
  }

  # 4. pull (fast-forward only, clean tree only)
  if (git status --porcelain --untracked-files=no) {
    throw "local changes to tracked files - commit or discard them, then update again"
  }
  Step "git pull --ff-only" { git pull --ff-only }
  Step "uv sync" { uv sync }

  # 6. rebuild the packaged app if one is in use
  if (Test-Path (Join-Path $Root "dist\IO\IO.exe")) {
    & (Join-Path $Root "dev.ps1") build
  }
  $ok = $true
  Log "updated $($old.Substring(0, 7)) -> $((git rev-parse --short HEAD).Trim())"
} catch {
  Log "update failed: $_"
  # only if the pull actually moved HEAD; otherwise there is nothing to undo
  if ((git rev-parse HEAD).Trim() -ne $old) {
    git reset --hard $old | Out-Null
    Log "rolled back to $($old.Substring(0, 7))"
  }
}

if ($NoRelaunch) { Log "relaunch skipped (-NoRelaunch)"; return }

# 7. relaunch (the old version if the update failed)
$exe = Join-Path $Root "dist\IO\IO.exe"
if ($Relaunch -eq "exe" -and (Test-Path $exe)) {
  Start-Process -FilePath $exe -WorkingDirectory $Root
} else {
  Start-Process -FilePath "powershell" -WorkingDirectory $Root `
    -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $Root "dev.ps1"), "up"
}
