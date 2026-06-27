<#
.SYNOPSIS
    Deploy / redeploy Loomind Engine to Docker.

.DESCRIPTION
    Builds the Docker image from source, then restarts the engine container
    with zero data loss (volumes are preserved).

.PARAMETER Pull
    Pull latest git changes before building.

.PARAMETER Force
    Rebuild image without Docker layer cache.

.EXAMPLE
    .\scripts\deploy\deploy-docker.ps1
    .\scripts\deploy\deploy-docker.ps1 -Pull
    .\scripts\deploy\deploy-docker.ps1 -Pull -Force
#>

param(
    [switch]$Pull,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$REPO    = (Resolve-Path "$PSScriptRoot\..\..")
$COMPOSE = Join-Path $REPO "apps\docker-deployment"

function Step($msg) { Write-Host "`n  >> $msg" -ForegroundColor Cyan }
function Ok($msg)   { Write-Host "     $msg" -ForegroundColor Green }
function Info($msg) { Write-Host "     $msg" -ForegroundColor Gray  }

Write-Host ""
Write-Host "  =============================================" -ForegroundColor Blue
Write-Host "   Loomind Engine  —  Docker Deploy"        -ForegroundColor White
Write-Host "  =============================================" -ForegroundColor Blue

# ── 0. Git pull ───────────────────────────────────────────────────────────────
if ($Pull) {
    Step "Pulling latest from git..."
    Push-Location $REPO
    git pull --ff-only
    Pop-Location
    Ok "Git up to date"
}

# ── 1. Build image ────────────────────────────────────────────────────────────
Step "Building Docker image..."
Push-Location $COMPOSE

$buildArgs = @("compose", "build")
if ($Force) { $buildArgs += "--no-cache" }

& docker @buildArgs
if ($LASTEXITCODE -ne 0) { Write-Host "  [ERROR] Build failed" -ForegroundColor Red; exit 1 }
Ok "Image built"

# ── 2. Restart container (rolling — zero data loss) ───────────────────────────
Step "Restarting engine container..."
docker compose up -d --force-recreate engine
if ($LASTEXITCODE -ne 0) { Write-Host "  [ERROR] Container restart failed" -ForegroundColor Red; exit 1 }

Pop-Location

# ── 3. Wait for health ────────────────────────────────────────────────────────
Step "Waiting for health check..."
$waited = 0
while ($waited -lt 90) {
    try {
        $r = Invoke-WebRequest -Uri "http://localhost:8082/health" -TimeoutSec 2 -UseBasicParsing -ErrorAction Stop
        if ($r.StatusCode -eq 200) {
            $body = $r.Content | ConvertFrom-Json
            Ok "Engine healthy — version $($body.version) — uptime $([math]::Round($body.uptime_seconds))s"
            break
        }
    } catch { }
    Start-Sleep 3
    $waited += 3
    Info "  ... $($waited)s elapsed"
}
if ($waited -ge 90) {
    Write-Host "  [WARN] Engine not responding after 90s — check: docker logs loomind-engine" -ForegroundColor Yellow
}

# ── 4. Quick smoke test ───────────────────────────────────────────────────────
Step "Smoke test..."
try {
    $stats = Invoke-RestMethod -Uri "http://localhost:8082/api/stats" -ErrorAction Stop
    Ok "Stats OK — experiences: $($stats.total_experiences)"
} catch {
    Write-Host "     [WARN] /api/stats failed — engine may still be loading" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "  =============================================" -ForegroundColor Blue
Write-Host "   Deploy complete" -ForegroundColor Green
Write-Host "  =============================================" -ForegroundColor Blue
Write-Host ""
Write-Host "  Engine  : http://localhost:8082" -ForegroundColor White
Write-Host "  Docs    : http://localhost:8082/docs" -ForegroundColor Gray
Write-Host "  Logs    : docker logs -f loomind-engine" -ForegroundColor Gray
Write-Host "  Rollback: git revert HEAD && .\scripts\deploy\deploy-docker.ps1" -ForegroundColor Gray
Write-Host ""
