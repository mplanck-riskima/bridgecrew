$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $ScriptDir

Write-Host "Creating virtual environment..."
python -m venv venv

Write-Host "Activating virtual environment..."
& "$ScriptDir\venv\Scripts\Activate.ps1"

Write-Host "Installing dependencies..."
pip install -r requirements.txt

# Create .env from example if it doesn't exist
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example - edit it with your bot token and settings."
} else {
    Write-Host ".env already exists, skipping."
}

Write-Host "Setup complete. Run .\start.sh or python bot.py to start the bot."
