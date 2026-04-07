from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import shutil
import subprocess

from knight.worker.config import settings


def _slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip())
    return cleaned.strip("-._") or "default"


def _repository_key(repository_url: str, repository_local_path: str) -> str:
    if repository_local_path:
        return _slugify(Path(repository_local_path).resolve().name)

    if repository_url:
        trimmed = repository_url.rstrip("/").removesuffix(".git")
        parts = [part for part in trimmed.split("/") if part]
        if len(parts) >= 2:
            return _slugify("-".join(parts[-2:]))
        return _slugify(parts[-1])

    return "default"


@dataclass(slots=True)
class RepositorySandbox:
    repository_key: str
    sandbox_root: Path
    repo_path: Path
    worktrees_root: Path


@dataclass(slots=True)
class WorktreeSandbox:
    repository_key: str
    issue_key: str
    branch_name: str
    sandbox_root: Path
    repo_path: Path
    worktree_path: Path


class WorktreeProvisioner:
    def __init__(self, sandbox_root: str | Path | None = None) -> None:
        self.sandbox_root = Path(sandbox_root or settings.worker_sandbox_root).resolve()
        self.sandbox_root.mkdir(parents=True, exist_ok=True)

    def prepare_repository(
        self,
        *,
        repository_url: str,
        repository_local_path: str,
    ) -> RepositorySandbox:
        repository_key = _repository_key(repository_url, repository_local_path)
        sandbox_root = self.sandbox_root / repository_key
        repo_path = sandbox_root / "repo"
        worktrees_root = sandbox_root / "worktrees"
        sandbox_root.mkdir(parents=True, exist_ok=True)
        worktrees_root.mkdir(parents=True, exist_ok=True)

        if not repo_path.exists():
            self._clone_repository(
                repository_url=repository_url,
                repository_local_path=repository_local_path,
                destination=repo_path,
            )

        return RepositorySandbox(
            repository_key=repository_key,
            sandbox_root=sandbox_root,
            repo_path=repo_path,
            worktrees_root=worktrees_root,
        )

    def prepare_worktree(
        self,
        *,
        repository_url: str,
        repository_local_path: str,
        issue_id: str,
        base_branch: str,
        branch_name: str = "",
    ) -> WorktreeSandbox:
        repository = self.prepare_repository(
            repository_url=repository_url,
            repository_local_path=repository_local_path,
        )
        issue_key = _slugify(issue_id)
        resolved_branch = branch_name or f"knight/{issue_key}"
        worktree_path = repository.worktrees_root / issue_key

        if not worktree_path.exists():
            self._create_worktree(
                repo_path=repository.repo_path,
                worktree_path=worktree_path,
                branch_name=resolved_branch,
                base_branch=base_branch or settings.worker_default_base_branch,
            )

        return WorktreeSandbox(
            repository_key=repository.repository_key,
            issue_key=issue_key,
            branch_name=resolved_branch,
            sandbox_root=repository.sandbox_root,
            repo_path=repository.repo_path,
            worktree_path=worktree_path,
        )

    def _clone_repository(
        self,
        *,
        repository_url: str,
        repository_local_path: str,
        destination: Path,
    ) -> None:
        if repository_local_path:
            source_path = Path(repository_local_path).resolve()
            if not source_path.exists():
                raise FileNotFoundError(
                    f"repository_local_path does not exist: {repository_local_path}"
                )
            command = ["git", "clone", "--no-hardlinks", str(source_path), str(destination)]
        elif repository_url:
            command = ["git", "clone", repository_url, str(destination)]
        else:
            raise ValueError("either repository_url or repository_local_path must be set")

        try:
            self._run(command, cwd=self.sandbox_root)
        except Exception:
            if destination.exists():
                shutil.rmtree(destination, ignore_errors=True)
            raise

    def _create_worktree(
        self,
        *,
        repo_path: Path,
        worktree_path: Path,
        branch_name: str,
        base_branch: str,
    ) -> None:
        worktree_path.parent.mkdir(parents=True, exist_ok=True)
        self._run(
            [
                "git",
                "-C",
                str(repo_path),
                "worktree",
                "add",
                "-b",
                branch_name,
                str(worktree_path),
                base_branch,
            ],
            cwd=repo_path,
        )

    def _run(self, command: list[str], cwd: Path) -> None:
        completed = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                completed.stderr.strip()
                or completed.stdout.strip()
                or f"command failed: {' '.join(command)}"
            )
