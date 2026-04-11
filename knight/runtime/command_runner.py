from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess

from knight.runtime.sandbox import SandboxPolicy


@dataclass(slots=True)
class CommandResult:
    command: str
    cwd: str
    exit_code: int
    stdout: str
    stderr: str


class LocalCommandRunner:
    def __init__(
        self,
        policy: SandboxPolicy | None = None,
        *,
        max_output_chars: int = 12000,
    ) -> None:
        self.policy = policy or SandboxPolicy()
        self.max_output_chars = max_output_chars

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
            stdout=completed.stdout[: self.max_output_chars],
            stderr=completed.stderr[: self.max_output_chars],
        )
