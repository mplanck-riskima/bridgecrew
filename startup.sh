#!/usr/bin/env bash
# Unified startup — launches the Discord bot and optionally the local dashboard.
# Usage:
#   ./startup.sh              # Start bot only (default)
#   ./startup.sh --with-dash  # Start bot + local dashboard (Docker)
#   ./startup.sh --dash-only  # Skip bot, just start the local dashboard
#   ./startup.sh --down       # Tear down all services and exit
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# ── Helpers ───────────────────────────────────────────────────────────────────

# Kill the process listening on a given port (cross-platform: Windows + Linux).
_kill_port() {
    local port=$1
    local pid
    pid=$(netstat -ano 2>/dev/null | grep ":${port}[[:space:]]" | grep -i "listen" | awk '{print $NF}' | grep -E '^[0-9]+$' | head -1)
    if [ -n "$pid" ] && [ "$pid" != "0" ]; then
        echo "  Stopping PID $pid (port $port)..."
        if command -v taskkill >/dev/null 2>&1; then
            taskkill //PID "$pid" //F >/dev/null 2>&1 || true
        else
            kill "$pid" 2>/dev/null || true
        fi
    fi
}

# Full teardown of all managed services.
_teardown() {
    echo "=== Teardown: stopping existing services ==="

    # Kill bot
    local bot_pid_file="$SCRIPT_DIR/.claude-bot/bot.pid"
    if [ -f "$bot_pid_file" ]; then
        local bpid
        bpid=$(cat "$bot_pid_file" 2>/dev/null)
        if [ -n "$bpid" ] && [ "$bpid" != "0" ]; then
            echo "  bot (PID $bpid)..."
            if command -v taskkill >/dev/null 2>&1; then
                taskkill //PID "$bpid" //F >/dev/null 2>&1 || true
            else
                kill "$bpid" 2>/dev/null || true
            fi
        fi
        rm -f "$bot_pid_file"
    fi
    _kill_port 8766

    # Kill watchdog
    local watchdog_pid_file="$SCRIPT_DIR/.claude-bot/watchdog.pid"
    if [ -f "$watchdog_pid_file" ]; then
        local wpid
        wpid=$(cat "$watchdog_pid_file" 2>/dev/null)
        if [ -n "$wpid" ] && [ "$wpid" != "0" ]; then
            echo "  watchdog (PID $wpid)..."
            if command -v taskkill >/dev/null 2>&1; then
                taskkill //PID "$wpid" //F >/dev/null 2>&1 || true
            else
                kill "$wpid" 2>/dev/null || true
            fi
        fi
        rm -f "$watchdog_pid_file"
    fi

    echo "  feature-mcp (port 8765)..."
    local fmcp_pid_file="$SCRIPT_DIR/.claude-bot/feature-mcp.pid"
    if [ -f "$fmcp_pid_file" ]; then
        local fmcp_pid
        fmcp_pid=$(cat "$fmcp_pid_file" 2>/dev/null)
        if [ -n "$fmcp_pid" ] && [ "$fmcp_pid" != "0" ]; then
            if command -v taskkill >/dev/null 2>&1; then
                taskkill //PID "$fmcp_pid" //F >/dev/null 2>&1 || true
            else
                kill "$fmcp_pid" 2>/dev/null || true
            fi
        fi
        rm -f "$fmcp_pid_file"
    fi
    _kill_port 8765

    if docker info >/dev/null 2>&1; then
        echo "  dashboard (Docker)..."
        cd "$SCRIPT_DIR/dashboard" && docker compose down --remove-orphans 2>/dev/null || true
        cd "$SCRIPT_DIR"
    fi

    echo "Teardown complete."
    echo ""
}

# ── Argument parsing ──────────────────────────────────────────────────────────

WITH_DASH=false
DASH_ONLY=false

for arg in "$@"; do
    case $arg in
        --with-dash) WITH_DASH=true; shift ;;
        --dash-only) DASH_ONLY=true; shift ;;
        --down)
            _teardown
            exit 0
            ;;
    esac
done

# ── Full teardown before starting ─────────────────────────────────────────────
_teardown

# ── Feature MCP Server ────────────────────────────────────────────────────────
FEATURE_MCP_DIR="$SCRIPT_DIR/feature-mcp"
FEATURE_MCP_SCRIPT="$FEATURE_MCP_DIR/start.sh"

if [ -f "$FEATURE_MCP_SCRIPT" ]; then
    echo "=== Starting Feature MCP Server ==="
    CLAUDE_BOT_DIR="$SCRIPT_DIR/.claude-bot"
    mkdir -p "$CLAUDE_BOT_DIR"
    bash "$FEATURE_MCP_SCRIPT" &
    FEATURE_MCP_PID=$!
    echo "$FEATURE_MCP_PID" > "$CLAUDE_BOT_DIR/feature-mcp.pid"
    echo "Feature MCP server started (PID $FEATURE_MCP_PID, port 8765)"
    # Wait until port 8765 is accepting connections (up to 10s)
    for i in $(seq 1 20); do
        if netstat -ano 2>/dev/null | grep -q ":8765[[:space:]].*LISTEN"; then
            echo "Feature MCP server ready."
            break
        fi
        sleep 0.5
    done
    echo ""
else
    echo "Warning: Feature MCP start script not found at $FEATURE_MCP_SCRIPT — skipping."
fi

# ── Env + Venv (shared by watchdog and bot) ───────────────────────────────────
if [ "$DASH_ONLY" = false ]; then
    # Load env file early so the watchdog process inherits DISCORD_TOKEN etc.
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

    if [ -f "$SCRIPT_DIR/venv/Scripts/activate" ]; then
        source "$SCRIPT_DIR/venv/Scripts/activate"
    else
        source "$SCRIPT_DIR/venv/bin/activate"
    fi
fi

# ── Watchdog ──────────────────────────────────────────────────────────────────
if [ "$DASH_ONLY" = false ]; then
    echo "=== Starting Watchdog ==="
    CLAUDE_BOT_DIR="$SCRIPT_DIR/.claude-bot"
    mkdir -p "$CLAUDE_BOT_DIR"
    PYTHONUTF8=1 python "$SCRIPT_DIR/watchdog.py" &
    WATCHDOG_PID=$!
    echo "$WATCHDOG_PID" > "$CLAUDE_BOT_DIR/watchdog.pid"
    echo "Watchdog started (PID $WATCHDOG_PID)"
    echo ""
fi

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
    # Env and venv already loaded above in the shared block.

    while true; do
        # `|| EXIT_CODE=$?` keeps `set -e` from aborting the script on non-zero exits
        EXIT_CODE=0
        PYTHONUTF8=1 python "$SCRIPT_DIR/bot.py" "$@" || EXIT_CODE=$?
        if [ $EXIT_CODE -eq 0 ]; then
            echo "Bot exited cleanly (code 0)."
            break
        fi
        if [ $EXIT_CODE -eq 42 ]; then
            echo "Bot requested restart (exit code 42). Restarting..."
        else
            echo "Bot exited with code $EXIT_CODE — restarting (watchdog kill or crash)..."
        fi
    done
fi
