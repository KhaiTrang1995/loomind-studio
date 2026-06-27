# Add these lines to your PowerShell profile.
# Open profile: notepad $PROFILE
# Reload after adding: . $PROFILE

# ── Loomind Fleet Monitor — CLI wrappers ─────────────────────────────────
# Replace path below with your actual clone location.
# Replace with your actual clone path
$TSX = "$env:USERPROFILE\GitHub\loomind-studio\scripts\fleet-hooks"
function agy   { & "$TSX\tsx-agy.ps1"   @args }
function codex { & "$TSX\tsx-codex.ps1" @args }
# ─────────────────────────────────────────────────────────────────────────────
