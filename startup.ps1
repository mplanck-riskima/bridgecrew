$ErrorActionPreference = "Stop"
# Unified startup - launches the dashboard (Docker) and Discord bot (venv).
# Usage:
#   .\startup.ps1              # Start both dashboard and bot
#   .\startup.ps1 -BotOnly    # Skip dashboard, just start the bot
#   .\startup.ps1 -DashOnly   # Skip bot, just start the dashboard
#   .\startup.ps1 -Down       # Tear down dashboard and exit

param(
    [switch]$BotOnly,
    [switch]$DashOnly,
    [switch]$Down
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $ScriptDir

if ($Down) {
    Write-Host "Tearing down dashboard..."
    Set-Location "$ScriptDir\dashboard"
    docker compose down 2>$null
    Write-Host "Done."
    exit 0
}

# -- Dashboard --
if (-not $BotOnly) {
    Write-Host "=== Starting Dashboard ==="
    try {
        docker info 2>&1 | Out-Null
        & "$ScriptDir\dashboard\startup.ps1"
        Write-Host "Dashboard is running (backend :8000, frontend :5173)"
    } catch {
        Write-Host "Warning: Docker is not running. Skipping dashboard."
        Write-Host "Start Docker Desktop and run .\dashboard\startup.ps1 separately."
    }
    Write-Host ""
}

# -- Discord Bot --
if (-not $DashOnly) {
    Write-Host "=== Starting Discord Bot ==="
    & "$ScriptDir\venv\Scripts\Activate.ps1"

    while ($true) {
        python "$ScriptDir\bot.py" @args
        if ($LASTEXITCODE -ne 42) {
            Write-Host "Bot exited with code $LASTEXITCODE."
            break
        }
        Write-Host "Bot requested restart (exit code 42). Restarting..."
    }
}
