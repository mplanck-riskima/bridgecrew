import uuid
from datetime import datetime, timezone
from pathlib import Path

from core.state import (
    load_feature_index, save_feature_index,
    load_feature_file, save_feature_file, delete_feature_file,
    list_feature_names,
    load_project_state, save_project_state,
)
from models.feature import Feature


class FeatureManager:
    def auto_complete_active_features(self, project_dir: Path, exclude_name: str | None = None) -> list[Feature]:
        """Complete any active features except exclude_name. Returns list of completed features.
        No 'paused' state — active features are completed when displaced."""
        completed = []
        for fname in list_feature_names(project_dir):
            if fname == exclude_name:
                continue
            fdata = load_feature_file(project_dir, fname)
            if not fdata or fdata.get("status") != "active":
                continue
            fdata["status"] = "completed"
            fdata["completed_at"] = datetime.now(timezone.utc).isoformat()
            fdata["name"] = fname
            save_feature_file(project_dir, fname, fdata)
            completed.append(Feature.from_dict(fname, fdata))

        # Clean completed features' sessions from the index
        if completed:
            index = load_feature_index(project_dir)
            sessions = index.get("sessions", {})
            completed_names = {f.name for f in completed}
            to_remove = [sid for sid, sdata in sessions.items() if sdata.get("feature") in completed_names]
            for sid in to_remove:
                del sessions[sid]
            save_feature_index(project_dir, index)

        return completed

    def discard_feature(self, project_dir: Path, name: str) -> Feature | None:
        """Remove a feature entirely. Deletes per-feature file, removes sessions from index."""
        fdata = load_feature_file(project_dir, name)
        if fdata is None:
            return None

        feat = Feature.from_dict(name, fdata)

        # Remove from index
        index = load_feature_index(project_dir)
        sessions = index.get("sessions", {})
        to_remove = [sid for sid, sdata in sessions.items() if sdata.get("feature") == name]
        for sid in to_remove:
            del sessions[sid]
        if index.get("current_feature") == name:
            index["current_feature"] = None
        save_feature_index(project_dir, index)

        # Delete per-feature file
        delete_feature_file(project_dir, name)

        # Clear default_session_id if it pointed to this feature
        state = load_project_state(project_dir)
        if state.get("default_session_id") in to_remove:
            state["default_session_id"] = None
            save_project_state(project_dir, state)

        return feat

    def start_feature(self, project_dir: Path, name: str, subdir: str | None = None) -> Feature:
        index = load_feature_index(project_dir)

        session_id = str(uuid.uuid4())
        feature = Feature(
            name=name, session_id=session_id, subdir=subdir,
            sessions=[{
                "session_id": session_id,
                "session_start": datetime.now(timezone.utc).isoformat(),
                "source": "discord",
            }],
        )

        # Save per-feature file
        feat_data = feature.to_dict()
        feat_data["name"] = name
        save_feature_file(project_dir, name, feat_data)

        # Update index: register session + set current_feature
        index.setdefault("sessions", {})[session_id] = {
            "feature": name,
            "source": "discord",
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        index["current_feature"] = name
        save_feature_index(project_dir, index)

        # Save default_session_id to bot state so complete_feature can find it
        state = load_project_state(project_dir)
        state["default_session_id"] = session_id
        save_project_state(project_dir, state)

        return feature

    def resume_feature(self, project_dir: Path, name: str) -> Feature | None:
        feat_data = load_feature_file(project_dir, name)
        if feat_data is None:
            return None

        session_id = str(uuid.uuid4())
        feat_data["session_id"] = session_id
        feat_data["status"] = "active"
        feat_data.setdefault("sessions", []).append({
            "session_id": session_id,
            "session_start": datetime.now(timezone.utc).isoformat(),
            "source": "discord",
        })
        feat_data["name"] = name
        save_feature_file(project_dir, name, feat_data)

        # Update index
        index = load_feature_index(project_dir)
        index.setdefault("sessions", {})[session_id] = {
            "feature": name,
            "source": "discord",
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        index["current_feature"] = name
        save_feature_index(project_dir, index)

        # Save default_session_id to bot state
        state = load_project_state(project_dir)
        state["default_session_id"] = session_id
        save_project_state(project_dir, state)

        return Feature.from_dict(name, feat_data)

    def complete_feature(
        self, project_dir: Path, name: str | None = None, session_id: str | None = None
    ) -> Feature | None:
        """Mark a feature as completed. If name is None, find it by session_id."""
        index = load_feature_index(project_dir)

        if not name:
            if session_id:
                current = self.get_current_feature(project_dir, session_id=session_id)
                if current:
                    name = current.name
            if not name:
                name = index.get("current_feature")
        if not name:
            return None

        feat_data = load_feature_file(project_dir, name)
        if feat_data is None:
            return None

        feat_data["status"] = "completed"
        feat_data["completed_at"] = datetime.now(timezone.utc).isoformat()
        feat_data["name"] = name
        save_feature_file(project_dir, name, feat_data)

        # Remove this feature's sessions from the index
        sessions = index.get("sessions", {})
        to_remove = [sid for sid, sdata in sessions.items() if sdata.get("feature") == name]
        for sid in to_remove:
            del sessions[sid]
        if index.get("current_feature") == name:
            index["current_feature"] = None
        save_feature_index(project_dir, index)

        # Clear default_session_id if it pointed to this feature
        state = load_project_state(project_dir)
        if state.get("default_session_id") in to_remove or not to_remove:
            state["default_session_id"] = None
            save_project_state(project_dir, state)

        return Feature.from_dict(name, feat_data)

    def get_current_feature(self, project_dir: Path, session_id: str | None = None) -> Feature | None:
        index = load_feature_index(project_dir)

        # Look up session in the index routing table
        if session_id:
            session_entry = index.get("sessions", {}).get(session_id)
            if session_entry:
                feat_name = session_entry.get("feature")
                if feat_name:
                    feat_data = load_feature_file(project_dir, feat_name)
                    if feat_data and feat_data.get("status") != "completed":
                        feat = Feature.from_dict(feat_name, feat_data)
                        feat.session_id = session_id
                        return feat

            # Also check per-feature files for session_id match (legacy sessions array)
            for fname in list_feature_names(project_dir):
                fdata = load_feature_file(project_dir, fname)
                if not fdata or fdata.get("status") != "active":
                    continue
                if fdata.get("session_id") == session_id:
                    feat = Feature.from_dict(fname, fdata)
                    feat.session_id = session_id
                    return feat
                for sess in fdata.get("sessions", []):
                    if sess.get("session_id") == session_id:
                        feat = Feature.from_dict(fname, fdata)
                        feat.session_id = session_id
                        return feat

        # Fallback: current_feature from index
        current = index.get("current_feature")
        if current:
            fdata = load_feature_file(project_dir, current)
            if fdata and fdata.get("status") == "active":
                return Feature.from_dict(current, fdata)

        return None

    def register_cli_session(self, project_dir: Path, cli_session_id: str, feature_name: str) -> Feature | None:
        """Wire a real CLI session ID into a feature. Used by /resume-session."""
        fdata = load_feature_file(project_dir, feature_name)
        if fdata is None:
            return None

        # Add to per-feature sessions array
        fdata.setdefault("sessions", []).append({
            "session_id": cli_session_id,
            "session_start": datetime.now(timezone.utc).isoformat(),
            "source": "cli",
        })
        fdata["name"] = feature_name
        save_feature_file(project_dir, feature_name, fdata)

        # Add to index routing table
        index = load_feature_index(project_dir)
        index.setdefault("sessions", {})[cli_session_id] = {
            "feature": feature_name,
            "source": "cli",
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        save_feature_index(project_dir, index)

        # Set as default session for the bot to resume
        state = load_project_state(project_dir)
        state["default_session_id"] = cli_session_id
        save_project_state(project_dir, state)

        return Feature.from_dict(feature_name, fdata)

    def list_features(self, project_dir: Path) -> list[Feature]:
        features = []
        for name in list_feature_names(project_dir):
            fdata = load_feature_file(project_dir, name)
            if fdata:
                features.append(Feature.from_dict(name, fdata))
        return features

    def accumulate_tokens(
        self,
        project_dir: Path,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        feature_name: str | None = None,
    ) -> dict:
        """Add token usage to a feature or the project session. Returns updated totals.
        Only touches the per-feature file — never the index."""
        if feature_name:
            feat_data = load_feature_file(project_dir, feature_name)
            if feat_data:
                feat_data["total_input_tokens"] = feat_data.get("total_input_tokens", 0) + input_tokens
                feat_data["total_output_tokens"] = feat_data.get("total_output_tokens", 0) + output_tokens
                feat_data["total_cost_usd"] = feat_data.get("total_cost_usd", 0.0) + cost_usd
                feat_data["prompt_count"] = feat_data.get("prompt_count", 0) + 1
                feat_data["name"] = feature_name
                save_feature_file(project_dir, feature_name, feat_data)
                return {
                    "total_input_tokens": feat_data["total_input_tokens"],
                    "total_output_tokens": feat_data["total_output_tokens"],
                    "total_cost_usd": feat_data["total_cost_usd"],
                    "prompt_count": feat_data["prompt_count"],
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
