#!/usr/bin/env bash
# Start the BridgeCrew dashboard (backend + frontend) via Docker Compose.
# Usage:
#   ./dashboard/startup.sh          # Start dashboard
#   ./dashboard/startup.sh --logs   # Start and tail logs
#   ./dashboard/startup.sh --down   # Tear down only
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Check Docker is running
if ! docker info >/dev/null 2>&1; then
    echo "Error: Docker is not running. Start Docker Desktop first."
    exit 1
fi

# Check .env exists in parent (bridgecrew root)
if [ ! -f "../.env" ]; then
    echo "Error: ../.env not found. Run setup.sh from the bridgecrew root first."
    exit 1
fi

# Print LAN IP for mobile access
if command -v ipconfig >/dev/null 2>&1; then
    LAN_IP=$(ipconfig | grep -A 5 "Wi-Fi\|Ethernet" | grep "IPv4" | head -1 | awk '{print $NF}' | tr -d '\r')
elif command -v hostname >/dev/null 2>&1; then
    LAN_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
fi
if [ -n "$LAN_IP" ]; then
    echo ""
    echo "Dashboard available on your local network at:"
    echo "  Frontend: http://${LAN_IP}:5173"
    echo "  Backend:  http://${LAN_IP}:8000"
    echo ""
fi

if [ "$1" = "--down" ]; then
    echo "Tearing down dashboard..."
    docker compose down
    exit 0
fi

echo "Starting dashboard..."
docker compose down 2>/dev/null || true
docker compose up --build -d

if [ "$1" = "--logs" ]; then
    docker compose logs -f
fi
