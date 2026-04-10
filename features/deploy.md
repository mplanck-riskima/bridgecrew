# Deploy Feature

## What it does / problem it solves

Prepares the repo for public sharing and makes it easy to set up and run the full stack (Discord bot + dashboard) from a clean clone. Before this feature, startup and setup were undocumented and tied to local dev assumptions.

## Key files changed or created

- `setup.sh` / `setup.ps1` — one-shot setup: creates the Python venv, installs all dependencies (bot, dashboard backend, tests), and scaffolds `.env` from `.env.example`
- `startup.sh` — unified launcher with `--bot-only`, `--dash-only`, and `--down` flags; handles the bot's restart loop (exit code 42) and gracefully skips Docker if not running
- `dashboard/startup.sh` — standalone dashboard launcher via Docker Compose; detects LAN IP and prints access URLs for mobile access
- `start.ps1` — Windows PowerShell equivalent of the legacy `start.sh`
- `.env.example` — updated with all required keys
- `README.md` — expanded with setup instructions and manual setup section
- `.gitignore` — cleaned up to exclude IDE configs, local state, and personal workflow docs
- `cogs/` renamed to `discord_cogs/` for clarity

## Design decisions and tradeoffs

- **Single `startup.sh` entry point**: Combines bot and dashboard launch rather than requiring two terminals. The bot's restart loop (exit code 42 for `/restart`) is handled here so `bot.py` stays clean.
- **Docker for dashboard, venv for bot**: Dashboard stack (FastAPI + React + MongoDB) runs in Docker Compose; the bot runs in a local venv to keep Claude CLI access straightforward.
- **Cross-platform scripts**: Both `setup.sh`/`startup.sh` (bash) and `setup.ps1`/`start.ps1` (PowerShell) provided for Windows users who may not have WSL.
- **Repo cleanup scope**: IDE configs, local `.claude` state, and personal planning docs were removed from tracking — not deleted, just untracked — to avoid leaking personal context in a public repo.

## Known limitations / follow-up items

- `startup.sh` does not wait for the dashboard to be healthy before starting the bot; if the bot tries to report costs immediately on startup it may hit a not-yet-ready backend.
- No health-check or retry logic in `dashboard/startup.sh` after `docker compose up`.
- Windows users still need bash (Git Bash / WSL) to run `startup.sh`; `start.ps1` only covers the bot.
