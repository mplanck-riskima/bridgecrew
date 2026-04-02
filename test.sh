#!/usr/bin/env bash
# Run the full test suite (bot + dashboard).
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ -f "$SCRIPT_DIR/venv/Scripts/python.exe" ]; then
    PYTHON="$SCRIPT_DIR/venv/Scripts/python.exe"
else
    PYTHON="$SCRIPT_DIR/venv/bin/python"
fi

echo "=== Bot Tests ==="
"$PYTHON" -m pytest "$SCRIPT_DIR/tests/bot/" -v "$@"

echo ""
echo "=== Dashboard Tests ==="
PYTHONPATH="$SCRIPT_DIR/dashboard/backend" "$PYTHON" -m pytest "$SCRIPT_DIR/tests/dashboard/" -v "$@"
