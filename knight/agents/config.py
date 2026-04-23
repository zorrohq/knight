from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    agent_name: str = "knight-coding-agent"
    agent_provider: str = ""
    agent_model_default: str = ""
    agent_model_high: str = ""
    agent_model_low: str = ""
    agent_max_steps: int = 25
    agent_workspace_root: str = "."
    agent_command_timeout_seconds: int = 300
    agent_max_command_output_chars: int = 12000
    agent_blocked_command_prefixes: list[str] = [
        "rm",
        "sudo",
        "shutdown",
        "reboot",
        "mkfs",
        "dd",
    ]
    agent_temperature: float = 0.0


settings = AgentSettings()
