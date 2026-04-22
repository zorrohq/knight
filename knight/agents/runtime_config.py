from __future__ import annotations

from dataclasses import dataclass

from knight.agents.config import settings
from knight.utils.db.config_store import ConfigStore


@dataclass(slots=True)
class ResolvedAgentSettings:
    provider: str
    model_default: str
    model_high: str
    model_low: str
    temperature: float
    max_steps: int
    command_timeout_seconds: int
    max_command_output_chars: int
    blocked_command_prefixes: list[str]
    allow_run_command: bool
    allow_write_files: bool
    allow_commit_and_push: bool
    system_prompt: str


class AgentConfigResolver:
    def __init__(self) -> None:
        self.store = ConfigStore()

    def resolve(self, *, repository: str | None = None) -> ResolvedAgentSettings:
        return ResolvedAgentSettings(
            provider=self.store.get_string(
                key="agent_provider",
                repository=repository,
                default=settings.agent_provider,
            ),
            model_default=self.store.get_string(
                key="agent_model_default",
                repository=repository,
                default=settings.agent_model_default,
            ),
            model_high=self.store.get_string(
                key="agent_model_high",
                repository=repository,
                default=settings.agent_model_high,
            ),
            model_low=self.store.get_string(
                key="agent_model_low",
                repository=repository,
                default=settings.agent_model_low,
            ),
            temperature=self.store.get_float(
                key="agent_temperature",
                repository=repository,
                default=settings.agent_temperature,
            ),
            max_steps=self.store.get_int(
                key="agent_max_steps",
                repository=repository,
                default=settings.agent_max_steps,
            ),
            command_timeout_seconds=self.store.get_int(
                key="agent_command_timeout_seconds",
                repository=repository,
                default=settings.agent_command_timeout_seconds,
            ),
            max_command_output_chars=self.store.get_int(
                key="agent_max_command_output_chars",
                repository=repository,
                default=settings.agent_max_command_output_chars,
            ),
            blocked_command_prefixes=self.store.get_string_list(
                key="agent_blocked_command_prefixes",
                repository=repository,
                default=list(settings.agent_blocked_command_prefixes),
            ),
            allow_run_command=self.store.get_bool(
                key="agent_allow_run_command",
                repository=repository,
                default=True,
            ),
            allow_write_files=self.store.get_bool(
                key="agent_allow_write_files",
                repository=repository,
                default=True,
            ),
            allow_commit_and_push=self.store.get_bool(
                key="agent_allow_commit_and_push",
                repository=repository,
                default=True,
            ),
            system_prompt=self.store.get_string(
                key="agent_system_prompt",
                repository=repository,
                default=settings.agent_system_prompt,
            ),
        )
