# feature-stuff-on-pc

**Status:** Completed
**Started:** 2026-04-05
**Completed:** 2026-04-05

## Goal

Bring the Discord bot's feature tracking workflow to Claude CLI on any PC. When working directly in a terminal, Claude should enforce the same lifecycle discipline as bot sessions — tracking features, auto-completing displaced ones, and writing summaries on completion — with a one-command setup that stays in sync as the lifecycle rules evolve.

## What Was Built

A canonical lifecycle rules doc (`docs/feature-lifecycle.md`) serves as the single source of truth. A pure-Python generator script (`scripts/generate_claude_commands.py`) reads that doc and renders five Claude slash commands into `~/.claude/commands/`. A setup script (`setup-claude-pc.sh`) runs the generator, installs the commands, and merges the lifecycle rules into `~/.claude/CLAUDE.md`. Re-running the setup script on any PC regenerates everything from the current bot repo state.

Two bot bugs were also fixed: queued messages during feature summary runs now show a human-readable label explaining the delay, and a `NameError` (`thread_id` undefined) in the feature gate was corrected to use `message.channel.id`.

## Key Files

| File | Purpose |
|---|---|
| `docs/feature-lifecycle.md` | Canonical lifecycle rules — source of truth for generator |
| `scripts/generate_claude_commands.py` | Renders 5 CLI command `.md` files from the lifecycle doc |
| `setup-claude-pc.sh` | One-command setup: generates commands + merges `~/.claude/CLAUDE.md` |
| `tests/bot/test_generate_claude_commands.py` | 19 tests covering the generator (TDD) |
| `conftest.py` | Root conftest adding `scripts/` to Python path for tests |
| `docs/superpowers/specs/2026-04-05-pc-feature-lifecycle-design.md` | Design spec |
| `docs/superpowers/plans/2026-04-05-pc-feature-lifecycle.md` | Implementation plan |

**Bot fixes:**
- `discord_cogs/claude_prompt.py` — system run labels for queue messages; feature gate `NameError` fix
- `dashboard/Dockerfile` — multi-stage production build (Node → Python)
- `railway.toml` — Railway deployment config

## Design Decisions

- **Bot repo as source of truth.** Rather than hand-maintaining separate CLI commands, the generator reads `docs/feature-lifecycle.md` and injects the lifecycle rules (especially the summary format) into each command's instruction text. Lifecycle changes propagate by re-running `setup-claude-pc.sh`.
- **Shared state, no sync.** Feature state already lived in `<project>/.claude/features/` — both the bot and CLI commands read/write the same files. No migration or sync mechanism was needed.
- **Pure stdlib generator.** No third-party dependencies; the generator is a single importable Python module, making it easy to test and portable across machines.
- **CLAUDE.md merge via marked block.** The setup script writes a `# BEGIN: feature-lifecycle ... # END: feature-lifecycle` block into `~/.claude/CLAUDE.md`, preserving any existing user content outside the block.

## Known Limitations / Follow-up

- The CLI slash commands tell Claude what to do via markdown instructions — they rely on Claude's judgment to execute the steps correctly (read/write JSON, run git commands). There is no programmatic enforcement; a badly-worded prompt or a confused Claude could deviate.
- `setup-claude-pc.sh` requires the bot repo to be cloned on the PC. If the repo is not present, the commands cannot be regenerated.
- The `python3` alias on Windows may intercept `command -v python3` before the real interpreter (Windows Store stub). A workaround shim was added during setup; a future improvement could detect and skip the Store stub more robustly.
