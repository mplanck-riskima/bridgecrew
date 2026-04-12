import json
import os
import time
import tempfile
from pathlib import Path
from typing import Any

from models.project import Project


BOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BOT_DIR / "config.json"

DEFAULT_CONFIG = {
    "projects": {},
}


def load_config() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    return dict(DEFAULT_CONFIG)


def save_config(config: dict) -> None:
    _atomic_write(CONFIG_PATH, config)


def get_projects(config: dict) -> dict[str, Project]:
    projects = {}
    for name, data in config.get("projects", {}).items():
        projects[name] = Project.from_dict(name, data)
    return projects


def set_project(config: dict, project: Project) -> dict:
    config.setdefault("projects", {})
    config["projects"][project.name] = project.to_dict()
    return config


def remove_project(config: dict, name: str) -> dict:
    config.get("projects", {}).pop(name, None)
    return config


def load_project_state(project_dir: Path) -> dict:
    state_path = project_dir / ".claude-bot" / "state.json"
    if state_path.exists():
        with open(state_path, "r") as f:
            return json.load(f)
    return {"history": []}


def save_project_state(project_dir: Path, state: dict) -> None:
    bot_dir = project_dir / ".claude-bot"
    bot_dir.mkdir(exist_ok=True)
    _atomic_write(bot_dir / "state.json", state)


# ── Atomic write with Windows retry ─────────────────────────────────────────

def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        # Retry with backoff for Windows file locking (WinError 5)
        for attempt in range(5):
            try:
                if path.exists():
                    os.replace(tmp_path, path)
                else:
                    os.rename(tmp_path, path)
                return
            except OSError:
                if attempt == 4:
                    raise
                time.sleep(0.1 * (2 ** attempt))
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise
