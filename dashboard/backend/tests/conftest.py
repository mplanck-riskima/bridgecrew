import os

# Set env vars before any app module is imported by test collection
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-unit-tests")
os.environ.setdefault("ALLOWED_EMAILS", "allowed@example.com")
os.environ.setdefault("GOOGLE_CLIENT_ID", "fake-client-id.apps.googleusercontent.com")
os.environ.setdefault("BRIDGECREW_API_KEY", "test-api-key-12345")
os.environ.setdefault("MONGODB_URI", "mongodb://localhost:27017/?serverSelectionTimeoutMS=100")
