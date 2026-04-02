import json
import os
import re
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


# ── Split Feature Storage ────────────────────────────────────────────────────
# features.json  = index only: {current_feature, sessions}
# features/<snake_case_name>.json = per-feature metadata


def feature_name_to_filename(name: str) -> str:
    """Convert a feature name to a safe snake_case filename (without extension).

    Examples:
        "Bugs & Fixes"         -> "bugs_and_fixes"
        "feature-closure"      -> "feature_closure"
        "long-message-support" -> "long_message_support"
        "Star-trek-personas"   -> "star_trek_personas"
    """
    s = name.lower()
    s = s.replace("&", "and")
    s = re.sub(r"[\s\-]+", "_", s)
    s = re.sub(r"[^a-z0-9_]", "", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "unnamed"


def load_feature_index(project_dir: Path) -> dict:
    """Load the feature index (current_feature + sessions routing table).
    Auto-migrates from old monolithic features.json on first read."""
    feature_path = project_dir / ".claude" / "features.json"
    if feature_path.exists():
        with open(feature_path, "r") as f:
            data = json.load(f)

        # Detect old monolithic format: has a "features" dict with feature data
        if "features" in data and isinstance(data["features"], dict):
            _migrate_monolithic_to_split(project_dir, data)
            # Re-read the now-migrated index
            with open(feature_path, "r") as f:
                data = json.load(f)

        return data

    # Migrate from ancient .claude-bot/state.json if present
    old_state_path = project_dir / ".claude-bot" / "state.json"
    if old_state_path.exists():
        with open(old_state_path, "r") as f:
            old_state = json.load(f)
        if "features" in old_state or "current_feature" in old_state:
            migrated_full = {
                "current_feature": old_state.pop("current_feature", None),
                "features": old_state.pop("features", {}),
            }
            # Write as monolithic first, then migrate to split
            claude_dir = project_dir / ".claude"
            claude_dir.mkdir(exist_ok=True)
            _atomic_write(claude_dir / "features.json", migrated_full)
            _migrate_monolithic_to_split(project_dir, migrated_full)
            # Clean old state
            _atomic_write(old_state_path, old_state)
            with open(feature_path, "r") as f:
                return json.load(f)

    return {"current_feature": None, "sessions": {}}


def save_feature_index(project_dir: Path, index: dict) -> None:
    """Save the feature index (current_feature + sessions only)."""
    claude_dir = project_dir / ".claude"
    claude_dir.mkdir(exist_ok=True)
    _atomic_write(claude_dir / "features.json", index)


def load_feature_file(project_dir: Path, name: str) -> dict | None:
    """Load a per-feature JSON file. Returns None if it doesn't exist."""
    filename = feature_name_to_filename(name)
    feature_path = project_dir / ".claude" / "features" / f"{filename}.json"
    if feature_path.exists():
        with open(feature_path, "r") as f:
            return json.load(f)
    return None


def save_feature_file(project_dir: Path, name: str, data: dict) -> None:
    """Save a per-feature JSON file."""
    features_dir = project_dir / ".claude" / "features"
    features_dir.mkdir(parents=True, exist_ok=True)
    filename = feature_name_to_filename(name)
    _atomic_write(features_dir / f"{filename}.json", data)


def delete_feature_file(project_dir: Path, name: str) -> bool:
    """Delete a per-feature JSON file. Returns True if it existed."""
    filename = feature_name_to_filename(name)
    feature_path = project_dir / ".claude" / "features" / f"{filename}.json"
    if feature_path.exists():
        feature_path.unlink()
        return True
    return False


def list_feature_names(project_dir: Path) -> list[str]:
    """List all feature names by scanning the per-feature directory.
    Returns the canonical names stored inside each JSON file."""
    features_dir = project_dir / ".claude" / "features"
    if not features_dir.exists():
        return []
    names = []
    for f in features_dir.glob("*.json"):
        try:
            with open(f, "r") as fh:
                data = json.load(fh)
            # Prefer canonical name stored in the file
            names.append(data.get("name", f.stem))
        except (json.JSONDecodeError, OSError):
            continue
    return names


def _migrate_monolithic_to_split(project_dir: Path, data: dict) -> None:
    """Migrate old monolithic features.json to split format."""
    features = data.get("features", {})
    sessions = data.get("sessions", {})
    current_feature = data.get("current_feature")

    features_dir = project_dir / ".claude" / "features"
    features_dir.mkdir(parents=True, exist_ok=True)

    for name, feat_data in features.items():
        feat_data["name"] = name
        filename = feature_name_to_filename(name)
        _atomic_write(features_dir / f"{filename}.json", feat_data)

    # Write the minimal index
    index = {
        "current_feature": current_feature,
        "sessions": sessions,
    }
    _atomic_write(project_dir / ".claude" / "features.json", index)


def migrate_all_projects(workspace_dir: str) -> None:
    """Run migration for all known projects at bot startup."""
    config = load_config()
    for name in config.get("projects", {}):
        project_dir = Path(workspace_dir) / name
        if project_dir.exists():
            try:
                load_feature_index(project_dir)  # triggers lazy migration
            except Exception as e:
                print(f"Warning: migration failed for {name}: {e}")


# ── Legacy shims (temporary — callers being migrated) ────────────────────────

def load_feature_state(project_dir: Path) -> dict:
    """Legacy shim: loads all feature data into old monolithic format.
    Prefer load_feature_index + load_feature_file instead."""
    index = load_feature_index(project_dir)
    features = {}
    for name in list_feature_names(project_dir):
        fdata = load_feature_file(project_dir, name)
        if fdata:
            features[name] = fdata
    return {
        "current_feature": index.get("current_feature"),
        "sessions": index.get("sessions", {}),
        "features": features,
    }


def save_feature_state(project_dir: Path, state: dict) -> None:
    """Legacy shim: saves monolithic state back to split format.
    Prefer save_feature_index + save_feature_file instead."""
    index = {
        "current_feature": state.get("current_feature"),
        "sessions": state.get("sessions", {}),
    }
    save_feature_index(project_dir, index)
    for name, fdata in state.get("features", {}).items():
        fdata["name"] = name
        save_feature_file(project_dir, name, fdata)


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
