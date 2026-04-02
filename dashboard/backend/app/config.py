"""Dashboard configuration loaded from environment variables."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class BridgeCrewSettings(BaseSettings):
    """Environment variables for the monitoring dashboard."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    MONGODB_URI: str
    MONGODB_DATABASE: str = "bridgecrew_dev"

    # Shared secret used to authenticate bot → webapp API calls
    BRIDGECREW_API_KEY: str = ""

    # Discord bot token for posting scheduled prompts
    DISCORD_BOT_TOKEN: str = ""
    DISCORD_GUILD_ID: str = ""

    # Comma-separated list of origins allowed by CORS.
    # In production (single Railway service) the frontend is same-origin so this
    # only matters for local dev. Set to your Railway URL if you ever split services.
    ALLOWED_ORIGINS: str = "http://localhost:5173"

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]


settings = BridgeCrewSettings()  # type: ignore[call-arg]
