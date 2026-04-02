#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== Bot Setup ==="
echo "Creating virtual environment..."
python -m venv venv

echo "Activating virtual environment..."
# Detect OS for correct activate path
if [ -f "venv/Scripts/activate" ]; then
    source venv/Scripts/activate
else
    source venv/bin/activate
fi

echo "Installing bot dependencies..."
pip install -r requirements.txt

# Install dashboard backend deps into venv (for running tests locally)
if [ -f "dashboard/backend/requirements.txt" ]; then
    echo "Installing dashboard backend dependencies..."
    pip install -r dashboard/backend/requirements.txt
fi

# Install test dependencies if available
if [ -f "requirements-test.txt" ]; then
    echo "Installing test dependencies..."
    pip install -r requirements-test.txt
fi

# Create .env from example if it doesn't exist
if [ ! -f .env ]; then
    cp .env.example .env
    echo "Created .env from .env.example — edit it with your bot token, MongoDB URI, and settings."
else
    echo ".env already exists, skipping."
fi

echo ""
echo "=== Dashboard Setup ==="
if docker info >/dev/null 2>&1; then
    echo "Docker is available. Dashboard will start via Docker Compose."
    echo "Run: ./dashboard/startup.sh"
else
    echo "Docker not detected. Install Docker Desktop to run the dashboard."
fi

echo ""
echo "Setup complete!"
echo "  Bot only:      ./start.sh"
echo "  Dashboard only: ./dashboard/startup.sh"
echo "  Both:          ./startup.sh"
