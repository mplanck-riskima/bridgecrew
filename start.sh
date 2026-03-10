#!/usr/bin/env bash
# Start the Discord bot using the project's virtual environment.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ -f "$SCRIPT_DIR/venv/Scripts/activate" ]; then
    source "$SCRIPT_DIR/venv/Scripts/activate"
else
    source "$SCRIPT_DIR/venv/bin/activate"
fi

python "$SCRIPT_DIR/bot.py" "$@"
