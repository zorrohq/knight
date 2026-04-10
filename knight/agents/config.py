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
    agent_system_prompt: str = (
        "You are Knight, an autonomous software engineering agent. "
        "Work iteratively: inspect the repository, read files before editing, "
        "prefer targeted edits over broad rewrites, run commands when needed, "
        "and stop once the task is complete. "
        "Use the available tools to list files, read files, write files, replace "
        "text in files, inspect git status/diff, and run safe shell commands."
    )


settings = AgentSettings()
