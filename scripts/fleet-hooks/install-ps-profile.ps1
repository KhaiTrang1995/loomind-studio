# install-ps-profile.ps1
# Adds AGY and Codex fleet-monitor wrappers to PowerShell profile.
# Run once: powershell -ExecutionPolicy Bypass -File install-ps-profile.ps1

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$AgyWrapper   = Join-Path $ScriptDir "tsx-agy.ps1"
$CodexWrapper = Join-Path $ScriptDir "tsx-codex.ps1"

$profileContent = @"

# ── Loomind Fleet Monitor — CLI wrappers ─────────────────────────────────
# Added by scripts/fleet-hooks/install-ps-profile.ps1
# Wraps AGY and Codex to report live status to Fleet Monitor (/fleet).
function agy   { & "$AgyWrapper" @args }
function codex { & "$CodexWrapper" @args }
# ─────────────────────────────────────────────────────────────────────────────
"@

# Check if already installed
if (Test-Path $PROFILE) {
    $existing = Get-Content $PROFILE -Raw -ErrorAction SilentlyContinue
    if ($existing -match "Loomind Fleet Monitor") {
        Write-Host "Fleet Monitor wrappers already installed in profile." -ForegroundColor Yellow
        exit 0
    }
}

# Create profile dir if needed
$profileDir = Split-Path $PROFILE
if (-not (Test-Path $profileDir)) {
    New-Item -ItemType Directory -Path $profileDir -Force | Out-Null
}

# Append to profile
Add-Content -Path $PROFILE -Value $profileContent
Write-Host "Fleet Monitor wrappers added to: $PROFILE" -ForegroundColor Green
Write-Host "Reload profile with: . `$PROFILE" -ForegroundColor Cyan
