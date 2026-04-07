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
    col.create_index([("project_id", ASCENDING), ("created_at", ASCENDING)], background=True)
    return col
