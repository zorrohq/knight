from __future__ import annotations

import shlex

from knight.agents.config import settings


class SandboxPolicyError(ValueError):
    """Raised when a command violates sandbox policy."""


class SandboxPolicy:
    def __init__(
        self,
        blocked_command_prefixes: list[str] | None = None,
    ) -> None:
        self.blocked_command_prefixes = blocked_command_prefixes or list(
            settings.agent_blocked_command_prefixes
        )

    def validate_command(self, command: str) -> None:
        parts = shlex.split(command)
        if not parts:
            raise SandboxPolicyError("command cannot be empty")

        for prefix in self.blocked_command_prefixes:
            if parts[0] == prefix:
                raise SandboxPolicyError(
                    f"command prefix `{prefix}` is blocked by sandbox policy"
                )
