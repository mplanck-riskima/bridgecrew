"""
Cleanup script: remove DB records for projects not connected to the workspace.

A project is "connected" if a .claude-bot/state.json in the workspace has
a bridgecrew_project_id pointing to it. Any project_id in the DB that isn't
in that set gets purged from projects, features, cost_log, and activity.

Usage:
    python cleanup_db.py            # dry-run (shows what would be deleted)
    python cleanup_db.py --live     # actually delete
"""

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from pymongo import MongoClient

# Load env
for env_file in (".env.production", ".env.local", ".env"):
    if Path(env_file).exists():
        load_dotenv(env_file, override=True)
        break

LIVE = "--live" in sys.argv
WORKSPACE_DIR = os.getenv("WORKSPACE_DIR")
MONGODB_URI = os.getenv("MONGODB_URI")
MONGODB_DATABASE = os.getenv("MONGODB_DATABASE", "bridgecrew_dev")

if not WORKSPACE_DIR:
    sys.exit("WORKSPACE_DIR is not set")
if not MONGODB_URI:
    sys.exit("MONGODB_URI is not set")

print(f"Workspace : {WORKSPACE_DIR}")
print(f"Database  : {MONGODB_DATABASE}")
print(f"Mode      : {'LIVE — will delete' if LIVE else 'dry-run (pass --live to delete)'}\n")

# ── Collect connected project IDs from workspace state files ──────────────────
connected_ids: set[str] = set()
workspace = Path(WORKSPACE_DIR)
for state_file in workspace.rglob(".claude-bot/state.json"):
    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
        pid = data.get("bridgecrew_project_id", "")
        if pid:
            connected_ids.add(pid)
            print(f"  connected: {pid}  ({state_file.parent.parent.name})")
    except Exception as e:
        print(f"  WARN: could not read {state_file}: {e}")

print(f"\n{len(connected_ids)} connected project(s)\n")

# ── Connect to MongoDB ────────────────────────────────────────────────────────
client = MongoClient(MONGODB_URI)
db = client[MONGODB_DATABASE]

COLLECTIONS_WITH_PROJECT_ID = ["projects", "features", "cost_log", "activity"]

total_deleted = 0

for col_name in COLLECTIONS_WITH_PROJECT_ID:
    col = db[col_name]

    if connected_ids:
        query = {"project_id": {"$nin": list(connected_ids)}}
    else:
        # Nothing connected — would delete everything; be safe and skip
        print(f"  SKIP {col_name}: no connected projects found, refusing to delete all records")
        continue

    count = col.count_documents(query)
    if count == 0:
        print(f"  OK    {col_name}: nothing to remove")
        continue

    # Show a sample of what would be removed
    sample = list(col.find(query, {"project_id": 1, "_id": 0}).limit(5))
    sample_ids = list({d.get("project_id") for d in sample})
    print(f"  {'DELETE' if LIVE else 'WOULD DELETE'}  {col_name}: {count} record(s)  (project_ids: {sample_ids[:3]}{'...' if len(sample_ids) > 3 else ''})")

    if LIVE:
        result = col.delete_many(query)
        total_deleted += result.deleted_count

if LIVE:
    print(f"\nDone. Deleted {total_deleted} record(s) total.")
else:
    print("\nDry-run complete. Re-run with --live to apply.")
