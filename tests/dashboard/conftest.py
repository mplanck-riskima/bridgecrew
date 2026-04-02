"""Dashboard test fixtures — patches MongoDB with mongomock for each test."""
import sys
from pathlib import Path

import mongomock
import pytest

# Add the dashboard backend to the path
_backend_dir = str(Path(__file__).resolve().parent.parent.parent / "dashboard" / "backend")
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

# Pre-import the db module and settings so we can patch them
import app.db as _db_module
import app.config as _config_module

from unittest.mock import patch

_mock_client = mongomock.MongoClient()


@pytest.fixture(autouse=True)
def sandbox_mongodb():
    """Fresh empty DB for every test."""
    _mock_client.drop_database("test_bridgecrew")
    with patch.object(_db_module, "_client", _mock_client), \
         patch.object(_db_module, "get_client", return_value=_mock_client), \
         patch.object(_config_module.settings, "MONGODB_DATABASE", "test_bridgecrew"), \
         patch.object(_config_module.settings, "BRIDGECREW_API_KEY", "test-key"):
        yield


@pytest.fixture
def client():
    """FastAPI TestClient with mongomock backing."""
    from starlette.testclient import TestClient
    from app.main import app
    return TestClient(app)


@pytest.fixture
def auth_headers():
    """Headers with valid API key."""
    return {"Authorization": "Bearer test-key"}
