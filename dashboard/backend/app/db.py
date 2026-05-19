"""MongoDB client and collection accessors."""

from __future__ import annotations

from pymongo import ASCENDING, MongoClient
from pymongo.collection import Collection
from pymongo.errors import OperationFailure

from app.config import settings

_client: MongoClient | None = None


def get_client() -> MongoClient:
    global _client
    if _client is None:
        _client = MongoClient(settings.MONGODB_URI)
    return _client


def get_db():
    return get_client()[settings.MONGODB_DATABASE]


def features_col() -> Collection:
    col = get_db()["features"]
    col.create_index([("feature_id", ASCENDING)], unique=True, background=True)
    return col


def prompt_templates_col() -> Collection:
    return get_db()["prompt_templates"]


def scheduled_tasks_col() -> Collection:
    return get_db()["scheduled_tasks"]


def cost_log_col() -> Collection:
    col = get_db()["cost_log"]
    col.create_index([("feature_id", ASCENDING)], background=True)
    return col


def projects_col() -> Collection:
    return get_db()["projects"]


def activity_col() -> Collection:
    col = get_db()["activity"]
    try:
        col.create_index([("created_at", ASCENDING)], expireAfterSeconds=604800, background=True)
    except OperationFailure:
        # TTL changed — drop and recreate the index with the new expiry
        col.drop_index("created_at_1")
        col.create_index([("created_at", ASCENDING)], expireAfterSeconds=604800, background=True)
    _ensure_activity_expires_at_index()
    return col


def project_maintainers_col() -> Collection:
    return get_db()["project_maintainers"]


def _ensure_activity_expires_at_index() -> None:
    """Sparse TTL index on expires_at for per-maintainer-run retention."""
    col = get_db()["activity"]
    try:
        col.create_index(
            [("expires_at", ASCENDING)],
            expireAfterSeconds=0,
            sparse=True,
            background=True,
        )
    except OperationFailure:
        pass  # Index already exists with same options — no action needed
