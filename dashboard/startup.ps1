$ErrorActionPreference = "Stop"
# Start the BridgeCrew dashboard (backend + frontend) via Docker Compose.
# Usage:
#   .\dashboard\startup.ps1          # Start dashboard
#   .\dashboard\startup.ps1 -Logs    # Start and tail logs
#   .\dashboard\startup.ps1 -Down    # Tear down only

param(
    [switch]$Logs,
    [switch]$Down
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $ScriptDir

# Check Docker is running
try {
    docker info 2>&1 | Out-Null
} catch {
    Write-Error "Docker is not running. Start Docker Desktop first."
    exit 1
}

# Check .env exists in parent
if (-not (Test-Path "../.env")) {
    Write-Error "../.env not found. Run setup.ps1 from the bridgecrew root first."
    exit 1
}

# Print LAN IP
$LanIP = (Get-NetIPAddress -AddressFamily IPv4 -InterfaceAlias "Wi-Fi", "Ethernet" -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -notlike "169.*" } |
    Select-Object -First 1).IPAddress
if ($LanIP) {
    Write-Host ""
    Write-Host "Dashboard available on your local network at:"
    Write-Host "  Frontend: http://${LanIP}:5173"
    Write-Host "  Backend:  http://${LanIP}:8000"
    Write-Host ""
}

if ($Down) {
    Write-Host "Tearing down dashboard..."
    docker compose down
    exit 0
}

Write-Host "Starting dashboard..."
docker compose down 2>$null
docker compose up --build -d

if ($Logs) {
    docker compose logs -f
}
