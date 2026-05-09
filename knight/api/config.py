from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class APISettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_prefix="API_",
    )

    title: str = "Knight"
    description: str = "Autonomous Background Agents"
    version: str = "0.1.0"

    host: str = "0.0.0.0"
    port: int = 8000
    reload: bool = False
    log_level: str = "info"

    api_base_prefix: str = "/api"
    cors_origins: list[str] = []
    cors_allow_credentials: bool = False
    cors_methods: list[str] = ["*"]
    cors_headers: list[str] = ["*"]

    # Shared secret for the generic /api/webhooks endpoint.
    webhook_secret: str = ""

    # GitHub secrets — env vars only, never in config.json.
    # These deliberately bypass the API_ prefix so the same env vars work
    # for both the API and worker containers.
    github_token: str = Field(default="", validation_alias=AliasChoices("GITHUB_TOKEN"))
    github_webhook_secret: str = Field(default="", validation_alias=AliasChoices("GITHUB_WEBHOOK_SECRET"))
    github_app_id: str = Field(default="", validation_alias=AliasChoices("GITHUB_APP_ID"))
    github_app_private_key: str = Field(default="", validation_alias=AliasChoices("GITHUB_APP_PRIVATE_KEY"))


settings = APISettings()
