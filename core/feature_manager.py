import uuid
from datetime import datetime, timezone
from pathlib import Path

from core.state import load_project_state, save_project_state
from models.feature import Feature


class FeatureManager:
    def start_feature(self, project_dir: Path, name: str) -> Feature:
        state = load_project_state(project_dir)
        features = state.get("features", {})

        # Pause the currently active feature
        current = state.get("current_feature")
        if current and current in features:
            features[current]["status"] = "paused"

        # Create the new feature
        session_id = str(uuid.uuid4())
        feature = Feature(name=name, session_id=session_id)
        features[name] = feature.to_dict()

        state["features"] = features
        state["current_feature"] = name
        save_project_state(project_dir, state)
        return feature

    def switch_feature(self, project_dir: Path, name: str) -> Feature | None:
        state = load_project_state(project_dir)
        features = state.get("features", {})

        if name not in features:
            return None

        # Pause current
        current = state.get("current_feature")
        if current and current in features:
            features[current]["status"] = "paused"

        # Activate target
        features[name]["status"] = "active"
        state["current_feature"] = name
        state["features"] = features
        save_project_state(project_dir, state)
        return Feature.from_dict(name, features[name])

    def complete_feature(self, project_dir: Path, name: str | None = None) -> Feature | None:
        """Mark a feature as completed. If name is None, complete the current feature."""
        state = load_project_state(project_dir)
        features = state.get("features", {})

        if not name:
            name = state.get("current_feature")
        if not name or name not in features:
            return None

        features[name]["status"] = "completed"
        features[name]["completed_at"] = datetime.now(timezone.utc).isoformat()

        # Clear current feature if it's the one being completed
        if state.get("current_feature") == name:
            state["current_feature"] = None

        state["features"] = features
        save_project_state(project_dir, state)
        return Feature.from_dict(name, features[name])

    def get_current_feature(self, project_dir: Path) -> Feature | None:
        state = load_project_state(project_dir)
        current = state.get("current_feature")
        if current and current in state.get("features", {}):
            return Feature.from_dict(current, state["features"][current])
        return None

    def list_features(self, project_dir: Path) -> list[Feature]:
        state = load_project_state(project_dir)
        return [
            Feature.from_dict(name, data)
            for name, data in state.get("features", {}).items()
        ]

    def add_history(
        self, project_dir: Path, user: str, prompt_summary: str, feature_name: str | None
    ) -> None:
        state = load_project_state(project_dir)
        state.setdefault("history", [])
        state["history"].append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "user": user,
            "prompt_summary": prompt_summary[:200],
            "feature": feature_name,
        })
        # Keep last 100 history entries
        state["history"] = state["history"][-100:]
        save_project_state(project_dir, state)
