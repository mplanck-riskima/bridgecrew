import uuid
from datetime import datetime, timezone
from pathlib import Path

from core.state import load_feature_state, save_feature_state, load_project_state, save_project_state
from models.feature import Feature


class FeatureManager:
    def start_feature(self, project_dir: Path, name: str, subdir: str | None = None) -> Feature:
        state = load_feature_state(project_dir)
        features = state.get("features", {})

        # Create the new feature — each session tracks its own active feature via session_id
        session_id = str(uuid.uuid4())
        feature = Feature(
            name=name, session_id=session_id, subdir=subdir,
            sessions=[{
                "session_id": session_id,
                "session_start": datetime.now(timezone.utc).isoformat(),
                "source": "discord",
            }],
        )
        features[name] = feature.to_dict()

        state["features"] = features
        save_feature_state(project_dir, state)
        return feature

    def resume_feature(self, project_dir: Path, name: str) -> Feature | None:
        state = load_feature_state(project_dir)
        features = state.get("features", {})

        if name not in features:
            return None

        # Give it a fresh session ID — each Discord session gets its own session entry
        features[name]["session_id"] = str(uuid.uuid4())
        features[name]["status"] = "active"

        # Record the session
        features[name].setdefault("sessions", []).append({
            "session_id": features[name]["session_id"],
            "session_start": datetime.now(timezone.utc).isoformat(),
            "source": "discord",
        })

        state["features"] = features
        save_feature_state(project_dir, state)
        return Feature.from_dict(name, features[name])

    def complete_feature(
        self, project_dir: Path, name: str | None = None, session_id: str | None = None
    ) -> Feature | None:
        """Mark a feature as completed. If name is None, find it by session_id or current_feature fallback."""
        state = load_feature_state(project_dir)
        features = state.get("features", {})

        if not name:
            if session_id:
                current = self.get_current_feature(project_dir, session_id=session_id)
                if current:
                    name = current.name
            # Backward compat: current_feature key
            if not name:
                name = state.get("current_feature")
        if not name or name not in features:
            return None

        features[name]["status"] = "completed"
        features[name]["completed_at"] = datetime.now(timezone.utc).isoformat()

        state["features"] = features
        save_feature_state(project_dir, state)
        return Feature.from_dict(name, features[name])

    def get_current_feature(self, project_dir: Path, session_id: str | None = None) -> Feature | None:
        state = load_feature_state(project_dir)
        features = state.get("features", {})

        if session_id:
            # Find the feature whose session matches — check sessions array and top-level session_id
            for name, data in features.items():
                if data.get("status") != "active":
                    continue
                for sess in data.get("sessions", []):
                    if sess.get("session_id") == session_id:
                        return Feature.from_dict(name, data)
                if data.get("session_id") == session_id:
                    return Feature.from_dict(name, data)

        # Backward compat: current_feature key
        current = state.get("current_feature")
        if current and current in features and features[current].get("status") == "active":
            return Feature.from_dict(current, features[current])

        # Fallback: if exactly one active feature exists, return it
        active = [(n, d) for n, d in features.items() if d.get("status") == "active"]
        if len(active) == 1:
            name, data = active[0]
            return Feature.from_dict(name, data)

        return None

    def list_features(self, project_dir: Path) -> list[Feature]:
        state = load_feature_state(project_dir)
        return [
            Feature.from_dict(name, data)
            for name, data in state.get("features", {}).items()
        ]

    def accumulate_tokens(
        self,
        project_dir: Path,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        feature_name: str | None = None,
    ) -> dict:
        """Add token usage to a feature or the project session. Returns updated totals."""
        if feature_name:
            feat_state = load_feature_state(project_dir)
            if feature_name in feat_state.get("features", {}):
                feat = feat_state["features"][feature_name]
                feat["total_input_tokens"] = feat.get("total_input_tokens", 0) + input_tokens
                feat["total_output_tokens"] = feat.get("total_output_tokens", 0) + output_tokens
                feat["total_cost_usd"] = feat.get("total_cost_usd", 0.0) + cost_usd
                feat["prompt_count"] = feat.get("prompt_count", 0) + 1
                save_feature_state(project_dir, feat_state)
                return {
                    "total_input_tokens": feat["total_input_tokens"],
                    "total_output_tokens": feat["total_output_tokens"],
                    "total_cost_usd": feat["total_cost_usd"],
                    "prompt_count": feat["prompt_count"],
                }

        # No active feature — accumulate at project level (bot state)
        state = load_project_state(project_dir)
        session = state.setdefault("session_usage", {
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_cost_usd": 0.0,
            "prompt_count": 0,
        })
        session["total_input_tokens"] += input_tokens
        session["total_output_tokens"] += output_tokens
        session["total_cost_usd"] += cost_usd
        session["prompt_count"] += 1
        save_project_state(project_dir, state)
        return dict(session)

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
