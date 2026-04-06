"""
Migration script: rename myvillage_project_id -> bridgecrew_project_id
in all .claude-bot/state.json files across the workspace.

Usage:
    python migrate_state_keys.py
    python migrate_state_keys.py --dry-run
"""

import json
import os
import sys
import tempfile
from pathlib import Path

from dotenv import load_dotenv

for env_file in (".env.production", ".env.local", ".env"):
    if Path(env_file).exists():
        load_dotenv(env_file, override=True)
        break

DRY_RUN = "--dry-run" in sys.argv

WORKSPACE_DIR = os.getenv("WORKSPACE_DIR")
if not WORKSPACE_DIR:
    sys.exit("WORKSPACE_DIR is not set in .env")

workspace = Path(WORKSPACE_DIR)
if not workspace.exists():
    sys.exit(f"Workspace directory does not exist: {workspace}")

print(f"Scanning workspace: {workspace}")
print(f"Mode: {'dry-run' if DRY_RUN else 'live'}\n")

found = 0
updated = 0

for state_file in workspace.rglob(".claude-bot/state.json"):
    found += 1
    with open(state_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    if "myvillage_project_id" not in data:
        print(f"  SKIP  {state_file} (key not present)")
        continue

    old_value = data.pop("myvillage_project_id")
    # Don't overwrite if bridgecrew_project_id already exists
    if "bridgecrew_project_id" not in data:
        data["bridgecrew_project_id"] = old_value
        action = f"renamed -> bridgecrew_project_id = {old_value!r}"
    else:
        action = f"dropped (bridgecrew_project_id already = {data['bridgecrew_project_id']!r})"

    print(f"  UPDATE {state_file}: {action}")

    if not DRY_RUN:
        fd, tmp = tempfile.mkstemp(dir=state_file.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
                f.write("\n")
            os.replace(tmp, state_file)
        except Exception:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    updated += 1

print(f"\nDone. Scanned {found} state file(s), updated {updated}.")
if DRY_RUN and updated:
    print("Re-run without --dry-run to apply changes.")
