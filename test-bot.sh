#!/usr/bin/env bash
# Run bot tests only (fast, no DB).
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ -f "$SCRIPT_DIR/venv/Scripts/python.exe" ]; then
    PYTHON="$SCRIPT_DIR/venv/Scripts/python.exe"
else
    PYTHON="$SCRIPT_DIR/venv/bin/python"
fi

"$PYTHON" -m pytest "$SCRIPT_DIR/tests/bot/" -v "$@"
