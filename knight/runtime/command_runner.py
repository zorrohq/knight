from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess


@dataclass(slots=True)
class CommandResult:
    command: str
    cwd: str
    exit_code: int
    stdout: str
    stderr: str


class LocalCommandRunner:
    def run(
        self,
        command: str,
        *,
        cwd: str | Path,
        timeout_seconds: int = 300,
    ) -> CommandResult:
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
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
