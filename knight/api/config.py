from pydantic_settings import BaseSettings, SettingsConfigDict


class APISettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", ".env.example"),
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
    cors_methods: list[str] = ["*"]
    cors_headers: list[str] = ["*"]


settings = APISettings()
