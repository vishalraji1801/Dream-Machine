# Registers the scheduled headless-Claude agents as Windows Task Scheduler jobs.
# All three run OFFLINE via run_ai_agent.py, which strips ANTHROPIC_API_KEY so
# they draw from your Claude subscription, never pay-as-you-go API billing.
#
# Prerequisites:
#   - Claude Code installed and signed in with your subscription:  claude login
#   - Run this script from the trading-bot folder.
#
# Usage:
#   .\setup_ai_agents.ps1            # register all three agents
#   .\setup_ai_agents.ps1 -Remove    # remove them
param([switch]$Remove)

$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$runner = Join-Path $PSScriptRoot "run_ai_agent.py"

$jobs = @(
    @{ Name = "TradingBot_AI_PostMarket";  Agent = "postmarket"; Time = "16:00"; Days = "MON,TUE,WED,THU,FRI" },
    @{ Name = "TradingBot_AI_PreMarket";   Agent = "premarket";  Time = "08:30"; Days = "MON,TUE,WED,THU,FRI" },
    @{ Name = "TradingBot_AI_Weekly";      Agent = "weekly";     Time = "18:00"; Days = "SUN" }
)

if ($Remove) {
    foreach ($j in $jobs) { schtasks /Delete /TN $j.Name /F }
    Write-Host "AI agent tasks removed."
    exit
}

if (-not (Test-Path $py)) { Write-Host "ERROR: venv python not found at $py"; exit 1 }
if (-not (Test-Path $runner)) { Write-Host "ERROR: run_ai_agent.py not found"; exit 1 }

foreach ($j in $jobs) {
    $action = "`"$py`" `"$runner`" $($j.Agent)"
    schtasks /Create /F /SC WEEKLY /D $j.Days /TN $j.Name /TR $action /ST $j.Time
    if ($LASTEXITCODE -eq 0) {
        Write-Host "Registered $($j.Name): $($j.Days) at $($j.Time) -> $($j.Agent) agent"
    } else {
        Write-Host "FAILED to register $($j.Name) (try an elevated PowerShell)"
    }
}

Write-Host ""
Write-Host "Done. Verify Claude is signed in with your subscription: claude login"
Write-Host "Ensure ANTHROPIC_API_KEY is NOT set system-wide (the runner strips it per-run anyway)."
