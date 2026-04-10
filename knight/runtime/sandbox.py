from __future__ import annotations

import shlex

from knight.agents.config import settings


class SandboxPolicyError(ValueError):
    """Raised when a command violates sandbox policy."""


class SandboxPolicy:
    readonly_git_subcommands = {"status", "diff"}

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

        if parts[0] == "git":
            subcommand = parts[1] if len(parts) > 1 else ""
            if subcommand not in self.readonly_git_subcommands:
                raise SandboxPolicyError(
                    "git commands are restricted to read-only status and diff operations"
                )
