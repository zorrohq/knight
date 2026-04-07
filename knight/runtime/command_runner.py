from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess

from knight.agents.config import settings
from knight.runtime.sandbox import SandboxPolicy


@dataclass(slots=True)
class CommandResult:
    command: str
    cwd: str
    exit_code: int
    stdout: str
    stderr: str


class LocalCommandRunner:
    def __init__(self, policy: SandboxPolicy | None = None) -> None:
        self.policy = policy or SandboxPolicy()

    def run(
        self,
        command: str,
        *,
        cwd: str | Path,
        timeout_seconds: int = 300,
    ) -> CommandResult:
        self.policy.validate_command(command)
        completed = subprocess.run(
            command,
            shell=True,
            cwd=Path(cwd),
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
        return CommandResult(
            command=command,
            cwd=str(Path(cwd)),
            exit_code=completed.returncode,
            stdout=completed.stdout[: settings.agent_max_command_output_chars],
            stderr=completed.stderr[: settings.agent_max_command_output_chars],
        )
