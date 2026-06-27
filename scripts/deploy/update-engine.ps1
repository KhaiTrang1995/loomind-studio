<#
.SYNOPSIS
    Hot-patch the running engine container without full rebuild.
    Use this to push Python code changes in seconds, not minutes.

.DESCRIPTION
    Copies changed source files into the running container, then sends
    a SIGHUP-equivalent (restart uvicorn inside container) so the new
    code is loaded. Volumes and SQLite data are untouched.

    For structural changes (new deps, env vars, Dockerfile changes)
    use deploy-docker.ps1 instead.

.PARAMETER Restart
    Full container restart instead of in-place file copy (slower but cleaner).

.EXAMPLE
    .\scripts\deploy\update-engine.ps1
    .\scripts\deploy\update-engine.ps1 -Restart
#>

param([switch]$Restart)

$REPO      = (Resolve-Path "$PSScriptRoot\..\..")
$SRC       = Join-Path $REPO "core\loomind-engine\src"
$CONTAINER = "loomind-engine"

function Step($msg) { Write-Host "`n  >> $msg" -ForegroundColor Cyan }
function Ok($msg)   { Write-Host "     $msg" -ForegroundColor Green }

Write-Host ""
Write-Host "  Loomind Engine — Hot Patch" -ForegroundColor Blue
Write-Host ""

# Check container is running
$state = docker inspect --format "{{.State.Status}}" $CONTAINER 2>$null
if ($state -ne "running") {
    Write-Host "  [ERROR] Container '$CONTAINER' is not running. Start with: docker compose up -d" -ForegroundColor Red
    exit 1
}

if ($Restart) {
    Step "Full container restart (preserving volumes)..."
    docker restart $CONTAINER
    Ok "Container restarted"
} else {
    Step "Copying src/ into container..."
    # Docker cp copies the contents of src/ to /app/src/ inside container
    docker cp "$SRC\." "${CONTAINER}:/app/src/"
    Ok "Source files updated"

    Step "Reloading uvicorn (graceful restart)..."
    # Send SIGTERM to uvicorn worker — it gracefully restarts and reloads code
    docker exec $CONTAINER sh -c "kill -HUP \$(pgrep -f 'uvicorn') 2>/dev/null || true"
    Start-Sleep 3
    Ok "Uvicorn reloaded"
}

Step "Verifying health..."
$waited = 0
while ($waited -lt 30) {
    try {
        $r = Invoke-WebRequest -Uri "http://localhost:8082/health" -TimeoutSec 2 -UseBasicParsing -ErrorAction Stop
        if ($r.StatusCode -eq 200) {
            $body = $r.Content | ConvertFrom-Json
            Ok "Engine healthy — version $($body.version)"
            break
        }
    } catch { }
    Start-Sleep 2
    $waited += 2
}

Write-Host ""
Write-Host "  Patch applied. View logs:" -ForegroundColor Green
Write-Host "    docker logs -f $CONTAINER --tail 50" -ForegroundColor Gray
Write-Host ""
