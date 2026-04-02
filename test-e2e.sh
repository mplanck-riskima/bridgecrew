#!/usr/bin/env bash
# Run e2e security tests (requires claude CLI on PATH + valid auth).
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ -f "$SCRIPT_DIR/venv/Scripts/python.exe" ]; then
    PYTHON="$SCRIPT_DIR/venv/Scripts/python.exe"
else
    PYTHON="$SCRIPT_DIR/venv/bin/python"
fi

if ! command -v claude >/dev/null 2>&1; then
    echo "Skipping e2e tests: claude CLI not on PATH"
    exit 0
fi

"$PYTHON" -m pytest "$SCRIPT_DIR/tests/e2e/" -v --timeout=60 "$@"
