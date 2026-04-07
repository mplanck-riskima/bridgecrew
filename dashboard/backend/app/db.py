"""MongoDB client and collection accessors."""

from __future__ import annotations

from pymongo import ASCENDING, MongoClient
from pymongo.collection import Collection

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
    return get_db()["features"]


def prompt_templates_col() -> Collection:
    return get_db()["prompt_templates"]


def scheduled_tasks_col() -> Collection:
    return get_db()["scheduled_tasks"]


def cost_log_col() -> Collection:
    return get_db()["cost_log"]


def projects_col() -> Collection:
    return get_db()["projects"]


def activity_col() -> Collection:
    col = get_db()["activity"]
    # TTL index — documents expire automatically after 24 hours
    col.create_index([("created_at", ASCENDING)], expireAfterSeconds=86400, background=True)
    return col
