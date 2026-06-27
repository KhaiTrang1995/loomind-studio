# tsx-codex.ps1 — Codex CLI wrapper for Loomind Fleet Monitor
# Wraps `codex` to report status to the engine so Fleet Monitor tracks it.
#
# SETUP:
#   Add to PowerShell profile (notepad $PROFILE):
#     function codex { & "D:\GitHub\loomind-studio\scripts\fleet-hooks\tsx-codex.ps1" @args }

param([Parameter(ValueFromRemainingArguments=$true)][string[]]$CliArgs)

$ENGINE = "http://localhost:8082"
$CLI    = "codex"

function Notify($status, $task = "") {
    $body = if ($task) {
        '{"status":"' + $status + '","task":"' + ($task -replace '"','\"') + '"}'
    } else {
        '{"status":"' + $status + '"}'
    }
    try {
        Invoke-RestMethod -Uri "$ENGINE/api/agents/$CLI/status" `
            -Method Patch `
            -ContentType "application/json" `
            -Body $body `
            -TimeoutSec 2 | Out-Null
    } catch { <# engine offline — ignore #> }
}

# Task description: if running `codex exec "prompt"`, capture the prompt
$taskDesc = if ($CliArgs.Count -ge 2 -and $CliArgs[0] -in @("exec","e","review")) {
    "$($CliArgs[0]): $($CliArgs[1])"
} elseif ($CliArgs.Count -gt 0) {
    $CliArgs[0]
} else {
    "interactive session"
}

Notify "busy" $taskDesc

try {
    & codex.exe @CliArgs
    $exitCode = $LASTEXITCODE
} finally {
    Notify "idle"
}

exit $exitCode
