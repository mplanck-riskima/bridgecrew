#!/usr/bin/env bash
# Unified startup — launches the Discord bot and optionally the local dashboard.
# Usage:
#   ./startup.sh              # Start bot only (default)
#   ./startup.sh --with-dash  # Start bot + local dashboard (Docker)
#   ./startup.sh --dash-only  # Skip bot, just start the local dashboard
#   ./startup.sh --down       # Tear down local dashboard and exit
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

WITH_DASH=false
DASH_ONLY=false

for arg in "$@"; do
    case $arg in
        --with-dash) WITH_DASH=true; shift ;;
        --dash-only) DASH_ONLY=true; shift ;;
        --down)
            echo "Tearing down local dashboard..."
            cd "$SCRIPT_DIR/dashboard" && docker compose down 2>/dev/null || true
            echo "Done."
            exit 0
            ;;
    esac
done

# ── Local Dashboard ────────────────────────────────────────────────────────────
if [ "$WITH_DASH" = true ] || [ "$DASH_ONLY" = true ]; then
    echo "=== Starting Local Dashboard ==="
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

    # Load env: .env.local when running with local dashboard, .env.production otherwise
    if [ "$WITH_DASH" = true ]; then
        ENV_FILE="$SCRIPT_DIR/.env.local"
    else
        ENV_FILE="$SCRIPT_DIR/.env.production"
    fi

    if [ ! -f "$ENV_FILE" ]; then
        echo "Error: $ENV_FILE not found."
        exit 1
    fi

    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a

    while true; do
        python "$SCRIPT_DIR/bot.py" "$@" || EXIT_CODE=$?
        EXIT_CODE=${EXIT_CODE:-0}
        if [ $EXIT_CODE -ne 42 ]; then
            echo "Bot exited with code $EXIT_CODE."
            break
        fi
        echo "Bot requested restart (exit code 42). Restarting..."
    done
fi
