#!/usr/bin/env bash
# setup-claude-pc.sh
# Installs Claude CLI slash commands and global CLAUDE.md for the feature lifecycle workflow.
# Run this on any PC running the bot, or after changes to docs/feature-lifecycle.md.
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== Claude PC Feature Lifecycle Setup ==="
echo ""

# ── Check Claude CLI ──────────────────────────────────────────────────────────
if command -v claude &>/dev/null; then
    CLAUDE_VERSION="$(claude --version 2>/dev/null || echo 'unknown')"
    echo "Claude CLI: $CLAUDE_VERSION"
else
    echo "WARNING: Claude CLI not found in PATH."
    echo "  Install from: https://docs.anthropic.com/claude-code"
    echo "  Commands will still be generated, but won't work until Claude CLI is installed."
    echo ""
fi

# ── Check Python ──────────────────────────────────────────────────────────────
if ! command -v python3 &>/dev/null && ! command -v python &>/dev/null; then
    echo "ERROR: Python 3 is required but not found in PATH."
    exit 1
fi
PYTHON="$(command -v python3 2>/dev/null || command -v python)"

# ── Activate venv if present ──────────────────────────────────────────────────
if [ -f "venv/Scripts/activate" ]; then
    source venv/Scripts/activate
elif [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
fi

# ── Run generator ─────────────────────────────────────────────────────────────
LIFECYCLE_DOC="$SCRIPT_DIR/docs/feature-lifecycle.md"
COMMANDS_DIR="$HOME/.claude/commands"
CLAUDE_MD="$HOME/.claude/CLAUDE.md"

echo "Generating command files from: $LIFECYCLE_DOC"
echo "Installing to: $COMMANDS_DIR"
echo ""

"$PYTHON" "$SCRIPT_DIR/scripts/generate_claude_commands.py" \
    --output-dir "$COMMANDS_DIR" \
    --lifecycle-doc "$LIFECYCLE_DOC" \
    --claude-md "$CLAUDE_MD"

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Available slash commands in Claude CLI:"
echo "  /start-feature <name>   Start a new feature (auto-completes any active)"
echo "  /complete-feature       Complete the active feature (writes summary)"
echo "  /resume-feature         Resume a previous feature"
echo "  /list-features          List all features for the current project"
echo "  /discard-feature        Remove a feature from tracking"
echo ""
echo "To update after lifecycle changes: ./setup-claude-pc.sh"
