# Registers a Windows Task Scheduler job that launches the trading bot
# every weekday at 09:00 in an interactive console window (the TOTP prompt
# appears on screen — you must be logged in for it to run).
#
# Usage:
#   .\setup_autostart.ps1           # register the task
#   .\setup_autostart.ps1 -Remove   # remove the task
param([switch]$Remove)

$taskName = "TradingBotV1"

if ($Remove) {
    schtasks /Delete /TN $taskName /F
    Write-Host "Scheduled task '$taskName' removed."
    exit
}

$bat = Join-Path $PSScriptRoot "start_bot.bat"
if (-not (Test-Path $bat)) {
    Write-Host "ERROR: start_bot.bat not found next to this script."
    exit 1
}

schtasks /Create /F /SC WEEKLY /D MON,TUE,WED,THU,FRI /TN $taskName /TR "`"$bat`"" /ST 09:00
if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "Scheduled task '$taskName' registered: weekdays 09:00."
    Write-Host "A console window will open at 09:00 asking for your TOTP."
    Write-Host "Note: the task runs only while you are logged in."
} else {
    Write-Host "ERROR: task registration failed (try an elevated PowerShell)."
}
