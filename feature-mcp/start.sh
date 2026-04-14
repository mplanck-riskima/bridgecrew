#!/usr/bin/env bash
# Start the feature-mcp MCP server.
# Equivalent of start.bat for Unix/Git Bash environments.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if [ -f ".venv/Scripts/activate" ]; then
    source ".venv/Scripts/activate"
else
    source ".venv/bin/activate"
fi

while true; do
    python server.py || EXIT_CODE=$?
    EXIT_CODE=${EXIT_CODE:-0}
    if [ $EXIT_CODE -ne 42 ]; then
        echo "feature-mcp exited with code $EXIT_CODE."
        break
    fi
    echo "feature-mcp restart requested (exit code 42). Restarting..."
done
