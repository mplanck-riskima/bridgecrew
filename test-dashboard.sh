#!/usr/bin/env bash
# Run dashboard tests only (mongomock sandbox).
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ -f "$SCRIPT_DIR/venv/Scripts/python.exe" ]; then
    PYTHON="$SCRIPT_DIR/venv/Scripts/python.exe"
else
    PYTHON="$SCRIPT_DIR/venv/bin/python"
fi

PYTHONPATH="$SCRIPT_DIR/dashboard/backend" "$PYTHON" -m pytest "$SCRIPT_DIR/tests/dashboard/" -v "$@"
