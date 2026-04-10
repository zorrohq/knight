from __future__ import annotations

from dataclasses import dataclass

from knight.agents.config import settings
from knight.worker.config_store import ConfigStore


@dataclass(slots=True)
class ResolvedAgentSettings:
    provider: str
    model: str
    temperature: float
    max_steps: int
    command_timeout_seconds: int
    max_command_output_chars: int
    blocked_command_prefixes: list[str]
    allow_run_command: bool
    allow_write_files: bool
    system_prompt: str


class AgentConfigResolver:
    def __init__(self) -> None:
        self.store = ConfigStore()

    def resolve(self) -> ResolvedAgentSettings:
        return ResolvedAgentSettings(
            provider=self.store.get_string(
                key="agent_provider",
                default=settings.agent_provider,
            ),
            model=self.store.get_string(
                key="agent_model",
                default=settings.agent_model,
            ),
            temperature=self.store.get_float(
                key="agent_temperature",
                default=settings.agent_temperature,
            ),
            max_steps=self.store.get_int(
                key="agent_max_steps",
                default=settings.agent_max_steps,
            ),
            command_timeout_seconds=self.store.get_int(
                key="agent_command_timeout_seconds",
                default=settings.agent_command_timeout_seconds,
            ),
            max_command_output_chars=self.store.get_int(
                key="agent_max_command_output_chars",
                default=settings.agent_max_command_output_chars,
            ),
            blocked_command_prefixes=self.store.get_string_list(
                key="agent_blocked_command_prefixes",
                default=list(settings.agent_blocked_command_prefixes),
            ),
            allow_run_command=self.store.get_bool(
                key="agent_allow_run_command",
                default=True,
            ),
            allow_write_files=self.store.get_bool(
                key="agent_allow_write_files",
                default=True,
            ),
            system_prompt=self.store.get_string(
                key="agent_system_prompt",
                default=settings.agent_system_prompt,
            ),
        )
