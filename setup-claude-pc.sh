#!/usr/bin/env bash
# setup-claude-pc.sh
# Sets up the feature-mcp workflow for Claude CLI on this machine:
#   - Generates slash command files in ~/.claude/commands/
#   - Merges the feature-mcp block into ~/.claude/CLAUDE.md
#   - Registers the feature-mcp server in ~/.claude/.mcp.json
#
# Run this on any PC that runs Claude CLI, or after changes to this repo.
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== Claude PC Feature MCP Setup ==="
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
COMMANDS_DIR="$HOME/.claude/commands"
CLAUDE_MD="$HOME/.claude/CLAUDE.md"
MCP_JSON="$HOME/.claude/.mcp.json"

echo "Installing command files to: $COMMANDS_DIR"
echo "Updating CLAUDE.md at:       $CLAUDE_MD"
echo "Registering MCP server in:   $MCP_JSON"
echo ""

"$PYTHON" "$SCRIPT_DIR/scripts/generate_claude_commands.py" \
    --output-dir "$COMMANDS_DIR" \
    --claude-md "$CLAUDE_MD" \
    --mcp-json "$MCP_JSON"

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Available slash commands in Claude CLI:"
echo "  /start-feature <name>   Start a new feature"
echo "  /complete-feature       Complete the active feature (writes summary)"
echo "  /resume-feature         Resume a previous feature"
echo "  /list-features          List all features for the current project"
echo "  /discard-feature        Remove a feature from tracking"
echo ""
echo "NOTE: The feature-mcp server must be running for these commands to work."
echo "  Start it with: M:/feature-mcp/start.bat"
echo ""
echo "To update after repo changes: ./setup-claude-pc.sh"
