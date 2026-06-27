<#
.SYNOPSIS
    Loomind CLI Setup — configures all CLI fleet hooks in one shot.

.DESCRIPTION
    Does three things:
      1. Writes correct CLI paths into cli-bridge/config.json
      2. Adds function wrappers (agy, codex) to PowerShell profile
      3. Adds hooks to Claude settings.json for fleet status reporting
      4. Verifies each CLI is reachable

    Run once. Safe to re-run — existing entries are not duplicated.

.EXAMPLE
    .\scripts\cli-setup.ps1
#>

$ErrorActionPreference = "SilentlyContinue"
$REPO        = (Resolve-Path "$PSScriptRoot\..")
$BRIDGE_CFG  = Join-Path $REPO "apps\cli-bridge\config.json"
$CLAUDE_CFG  = Join-Path $env:USERPROFILE ".claude\settings.json"
$HOOKS_DIR   = Join-Path $REPO "scripts\fleet-hooks"
$ENGINE      = "http://localhost:8082"

function Step($msg) { Write-Host "`n  >> $msg" -ForegroundColor Cyan }
function Ok($msg)   { Write-Host "     [OK] $msg" -ForegroundColor Green }
function Skip($msg) { Write-Host "     [--] $msg" -ForegroundColor Gray  }
function Warn($msg) { Write-Host "     [!!] $msg" -ForegroundColor Yellow }

Write-Host ""
Write-Host "  =============================================" -ForegroundColor Blue
Write-Host "   Loomind — CLI Fleet Setup"               -ForegroundColor White
Write-Host "  =============================================" -ForegroundColor Blue

# ── 1. Auto-detect CLI paths ──────────────────────────────────────────────────
Step "Detecting CLI paths..."

function Find-CLI($name, $candidates) {
    # Check PATH first
    $found = (Get-Command $name -ErrorAction SilentlyContinue)?.Source
    if ($found) { return $found }
    # Check known install locations
    foreach ($c in $candidates) {
        $expanded = [System.Environment]::ExpandEnvironmentVariables($c)
        if (Test-Path $expanded) { return $expanded }
    }
    return $null
}

$paths = @{
    claude = Find-CLI "claude" @(
        "$env:USERPROFILE\.local\bin\claude.exe",
        "$env:USERPROFILE\.local\bin\claude",
        "$env:LOCALAPPDATA\Programs\claude\claude.exe"
    )
    agy    = Find-CLI "agy" @(
        "$env:LOCALAPPDATA\agy\bin\agy.exe",
        "$env:USERPROFILE\.local\bin\agy.exe"
    )
    codex  = Find-CLI "codex" @(
        "$env:LOCALAPPDATA\Programs\OpenAI\Codex\bin\codex.exe",
        "$env:USERPROFILE\.local\bin\codex.exe"
    )
    grok   = Find-CLI "grok" @(
        "$env:USERPROFILE\.grok\bin\grok.exe",
        "$env:USERPROFILE\.grok\bin\grok"
    )
}

foreach ($cli in $paths.Keys) {
    if ($paths[$cli]) { Ok "$cli  ->  $($paths[$cli])" }
    else              { Warn "$cli not found — will be skipped in agent loop" }
}

# ── 2. Update cli-bridge/config.json ─────────────────────────────────────────
Step "Updating cli-bridge/config.json..."

$cfg = Get-Content $BRIDGE_CFG -Raw | ConvertFrom-Json
foreach ($cli in $paths.Keys) {
    if ($paths[$cli]) {
        $cfg.cli_paths.$cli = $paths[$cli]
    }
}
$cfg | ConvertTo-Json -Depth 5 | Set-Content $BRIDGE_CFG -Encoding UTF8
Ok "config.json updated with detected paths"

# ── 3. PowerShell profile — agy + codex wrappers ─────────────────────────────
Step "Configuring PowerShell profile wrappers..."

$profileContent = Get-Content $PROFILE -Raw -ErrorAction SilentlyContinue
if (-not $profileContent) { $profileContent = "" }

$agyCmdStr   = "function agy   { & `"$HOOKS_DIR\tsx-agy.ps1`"   @args }"
$codexCmdStr = "function codex { & `"$HOOKS_DIR\tsx-codex.ps1`" @args }"

$changed = $false

if ($profileContent -notmatch "tsx-agy") {
    Add-Content -Path $PROFILE -Value "`n# Loomind Fleet hook — AGY"
    Add-Content -Path $PROFILE -Value $agyCmdStr
    Ok "Added 'agy' wrapper to PowerShell profile"
    $changed = $true
} else { Skip "agy wrapper already in profile" }

if ($profileContent -notmatch "tsx-codex") {
    Add-Content -Path $PROFILE -Value "`n# Loomind Fleet hook — Codex"
    Add-Content -Path $PROFILE -Value $codexCmdStr
    Ok "Added 'codex' wrapper to PowerShell profile"
    $changed = $true
} else { Skip "codex wrapper already in profile" }

if ($changed) {
    Write-Host "     Reload profile with:  . `$PROFILE" -ForegroundColor Yellow
}

# ── 4. Claude hooks in ~/.claude/settings.json ────────────────────────────────
Step "Configuring Claude hooks..."

if (-not (Test-Path (Split-Path $CLAUDE_CFG))) {
    New-Item -ItemType Directory -Path (Split-Path $CLAUDE_CFG) -Force | Out-Null
}

$claudeSettings = if (Test-Path $CLAUDE_CFG) {
    Get-Content $CLAUDE_CFG -Raw | ConvertFrom-Json
} else {
    [PSCustomObject]@{}
}

$hookCmd = "curl -sf -X PATCH `"$ENGINE/api/agents/claude/status`" -H `"Content-Type: application/json`" -d `"{\\`"status\\`":\\`"busy\\`"}`" >nul 2>&1 || exit 0"
$stopCmd = "curl -sf -X PATCH `"$ENGINE/api/agents/claude/status`" -H `"Content-Type: application/json`" -d `"{\\`"status\\`":\\`"idle\\`"}`" >nul 2>&1 || exit 0"
$hbCmd   = "curl -sf -X POST `"$ENGINE/api/agents/heartbeat?agent_id=claude`" >nul 2>&1 || exit 0"

if (-not $claudeSettings.PSObject.Properties["hooks"]) {
    $claudeSettings | Add-Member -NotePropertyName "hooks" -NotePropertyValue @{
        UserPromptSubmit = @(@{ matcher = ""; hooks = @(@{ type = "command"; command = $hookCmd }) })
        Stop             = @(@{ matcher = ""; hooks = @(@{ type = "command"; command = $stopCmd }) })
        PreToolCall      = @(@{ matcher = ""; hooks = @(@{ type = "command"; command = $hbCmd }) })
    }
    $claudeSettings | ConvertTo-Json -Depth 10 | Set-Content $CLAUDE_CFG -Encoding UTF8
    Ok "Claude hooks written to $CLAUDE_CFG"
} else {
    Skip "Claude hooks already configured"
}

# ── 5. Verify CLIs ────────────────────────────────────────────────────────────
Step "Verifying CLI availability..."

foreach ($cli in @("claude", "agy", "codex", "grok")) {
    $p = $paths[$cli]
    if ($p -and (Test-Path $p)) {
        Ok "$cli reachable at $p"
    } elseif (Get-Command $cli -ErrorAction SilentlyContinue) {
        Ok "$cli reachable via PATH"
    } else {
        Warn "$cli not found — tasks for this CLI will be skipped"
    }
}

# ── Summary ───────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  =============================================" -ForegroundColor Blue
Write-Host "   Setup complete" -ForegroundColor Green
Write-Host "  =============================================" -ForegroundColor Blue
Write-Host ""
Write-Host "  Next steps:" -ForegroundColor White
Write-Host "    1.  . `$PROFILE               # reload PowerShell profile" -ForegroundColor Gray
Write-Host "    2.  .\start.ps1             # start full stack" -ForegroundColor Gray
Write-Host "    3.  Open http://localhost:5173/fleet  # verify all CLIs show Online" -ForegroundColor Gray
Write-Host ""
