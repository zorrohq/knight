from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    agent_name: str = "knight-coding-agent"
    agent_provider: str = ""
    agent_model: str = ""
    agent_max_steps: int = 12
    agent_workspace_root: str = "."
    agent_command_timeout_seconds: int = 300


settings = AgentSettings()
