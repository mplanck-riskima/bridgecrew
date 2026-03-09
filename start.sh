#!/usr/bin/env bash
# Start the Discord bot using the project's virtual environment.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/venv/Scripts/activate"
python "$SCRIPT_DIR/bot.py" "$@"
