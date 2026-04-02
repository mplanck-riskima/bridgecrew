#!/usr/bin/env bash
# Unified startup — launches the dashboard (Docker) and Discord bot (venv).
# Usage:
#   ./startup.sh              # Start both dashboard and bot
#   ./startup.sh --bot-only   # Skip dashboard, just start the bot
#   ./startup.sh --dash-only  # Skip bot, just start the dashboard
#   ./startup.sh --down       # Tear down dashboard and exit
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

BOT_ONLY=false
DASH_ONLY=false

for arg in "$@"; do
    case $arg in
        --bot-only) BOT_ONLY=true; shift ;;
        --dash-only) DASH_ONLY=true; shift ;;
        --down)
            echo "Tearing down dashboard..."
            cd "$SCRIPT_DIR/dashboard" && docker compose down 2>/dev/null || true
            echo "Done."
            exit 0
            ;;
    esac
done

# ── Dashboard ─────────────────────────────────────────────────────────────────
if [ "$BOT_ONLY" = false ]; then
    echo "=== Starting Dashboard ==="
    if ! docker info >/dev/null 2>&1; then
        echo "Warning: Docker is not running. Skipping dashboard."
        echo "Start Docker Desktop and run ./dashboard/startup.sh separately."
    else
        bash "$SCRIPT_DIR/dashboard/startup.sh"
        echo "Dashboard is running (backend :8000, frontend :5173)"
    fi
    echo ""
fi

# ── Discord Bot ───────────────────────────────────────────────────────────────
if [ "$DASH_ONLY" = false ]; then
    echo "=== Starting Discord Bot ==="

    if [ -f "$SCRIPT_DIR/venv/Scripts/activate" ]; then
        source "$SCRIPT_DIR/venv/Scripts/activate"
    else
        source "$SCRIPT_DIR/venv/bin/activate"
    fi

    while true; do
        python "$SCRIPT_DIR/bot.py" "$@"
        EXIT_CODE=$?
        if [ $EXIT_CODE -ne 42 ]; then
            echo "Bot exited with code $EXIT_CODE."
            break
        fi
        echo "Bot requested restart (exit code 42). Restarting..."
    done
fi
