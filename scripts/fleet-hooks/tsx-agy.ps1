# tsx-agy.ps1 — AGY CLI wrapper for Loomind Fleet Monitor
# Wraps `agy` to report status to the engine so Fleet Monitor tracks it.
#
# SETUP:
#   Add to PowerShell profile (notepad $PROFILE):
#     function agy { & "D:\GitHub\loomind-studio\scripts\fleet-hooks\tsx-agy.ps1" @args }
#
# Or copy/symlink tsx-agy.ps1 to a directory on PATH and rename to agy.ps1

param([Parameter(ValueFromRemainingArguments=$true)][string[]]$CliArgs)

$ENGINE = "http://localhost:8082"
$CLI    = "agy"

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

# Determine task description from args
$taskDesc = if ($CliArgs.Count -gt 0) { $CliArgs[0] } else { "interactive session" }

# Mark busy
Notify "busy" $taskDesc

try {
    # Run actual agy with all passed arguments
    & agy.exe @CliArgs
    $exitCode = $LASTEXITCODE
} finally {
    # Mark idle regardless of exit code
    Notify "idle"
}

exit $exitCode
