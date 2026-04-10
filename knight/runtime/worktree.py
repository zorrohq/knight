from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import shutil
import subprocess

from knight.runtime.locking import RepositoryLockManager
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
    base_branch: str
    sandbox_root: Path
    repo_path: Path
    worktree_path: Path


class WorktreeProvisioner:
    def __init__(self, sandbox_root: str | Path | None = None) -> None:
        self.sandbox_root = Path(sandbox_root or settings.worker_sandbox_root).resolve()
        self.sandbox_root.mkdir(parents=True, exist_ok=True)
        self.lock_manager = RepositoryLockManager()

    def prepare_repository(
        self,
        *,
        repository_url: str,
        repository_local_path: str,
        base_branch: str,
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
        else:
            self.refresh_repository(repo_path=repo_path, base_branch=base_branch)

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
        repository_key = _repository_key(repository_url, repository_local_path)
        lock_path = self.sandbox_root / repository_key / ".repo.lock"
        with self.lock_manager.acquire(lock_path):
            repository = self.prepare_repository(
                repository_url=repository_url,
                repository_local_path=repository_local_path,
                base_branch=base_branch or settings.worker_default_base_branch,
            )
            issue_key = _slugify(issue_id)
            resolved_branch = branch_name or f"knight/{issue_key}"
            worktree_path = repository.worktrees_root / issue_key
            branch_ref = self.sync_branch_reference(
                repo_path=repository.repo_path,
                branch_name=resolved_branch,
                base_branch=base_branch or settings.worker_default_base_branch,
            )

            self.prepare_branch_worktree(
                repo_path=repository.repo_path,
                worktree_path=worktree_path,
                branch_name=resolved_branch,
                branch_ref=branch_ref,
                base_branch=base_branch or settings.worker_default_base_branch,
            )

        return WorktreeSandbox(
            repository_key=repository.repository_key,
            issue_key=issue_key,
            branch_name=resolved_branch,
            base_branch=base_branch or settings.worker_default_base_branch,
            sandbox_root=repository.sandbox_root,
            repo_path=repository.repo_path,
            worktree_path=worktree_path,
        )

    def refresh_repository(self, *, repo_path: Path, base_branch: str) -> None:
        resolved_base = base_branch or settings.worker_default_base_branch
        self._run(["git", "fetch", "--all", "--prune"], cwd=repo_path)
        reset_target = self._resolve_remote_branch(repo_path, resolved_base)
        self._run(["git", "checkout", "-B", resolved_base, reset_target], cwd=repo_path)
        self._run(["git", "reset", "--hard", reset_target], cwd=repo_path)
        self._run(["git", "clean", "-fd"], cwd=repo_path)

    def prepare_branch_worktree(
        self,
        *,
        repo_path: Path,
        worktree_path: Path,
        branch_name: str,
        branch_ref: str | None,
        base_branch: str,
    ) -> None:
        start_point = branch_ref or self._resolve_remote_branch(repo_path, base_branch)
        if worktree_path.exists():
            self._checkout_existing_worktree_branch(
                worktree_path=worktree_path,
                branch_name=branch_name,
                branch_ref=branch_ref,
                start_point=start_point,
            )
            self._run(["git", "reset", "--hard", start_point], cwd=worktree_path)
            self._run(["git", "clean", "-fd"], cwd=worktree_path)
            return

        self._create_worktree(
            repo_path=repo_path,
            worktree_path=worktree_path,
            branch_name=branch_name,
            start_point=start_point,
            branch_ref=branch_ref,
        )

    def remove_worktree(self, *, repo_path: Path, worktree_path: Path) -> None:
        if not worktree_path.exists():
            return
        lock_path = repo_path.parent / ".repo.lock"
        with self.lock_manager.acquire(lock_path):
            completed = subprocess.run(
                ["git", "worktree", "remove", "--force", str(worktree_path)],
                cwd=repo_path,
                text=True,
                capture_output=True,
                check=False,
            )
            if completed.returncode != 0 and worktree_path.exists():
                shutil.rmtree(worktree_path, ignore_errors=True)

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
        start_point: str,
        branch_ref: str | None,
    ) -> None:
        worktree_path.parent.mkdir(parents=True, exist_ok=True)
        if branch_ref == branch_name:
            command = ["git", "worktree", "add", str(worktree_path), branch_name]
        elif branch_ref:
            command = [
                "git",
                "worktree",
                "add",
                "-b",
                branch_name,
                str(worktree_path),
                branch_ref,
            ]
        else:
            command = [
                "git",
                "worktree",
                "add",
                "-B",
                branch_name,
                str(worktree_path),
                start_point,
            ]
        self._run(command, cwd=repo_path)

    def sync_branch_reference(
        self,
        *,
        repo_path: Path,
        branch_name: str,
        base_branch: str,
    ) -> str | None:
        remote_branch = self._resolve_remote_branch_ref(repo_path, branch_name)
        if remote_branch:
            return remote_branch

        return None

    def _checkout_existing_worktree_branch(
        self,
        *,
        worktree_path: Path,
        branch_name: str,
        branch_ref: str | None,
        start_point: str,
    ) -> None:
        if branch_ref == branch_name:
            self._run(["git", "checkout", branch_name], cwd=worktree_path)
            return

        self._run(
            ["git", "checkout", "-B", branch_name, start_point],
            cwd=worktree_path,
        )

    def _resolve_remote_branch_ref(self, repo_path: Path, branch_name: str) -> str | None:
        completed = subprocess.run(
            ["git", "rev-parse", "--verify", f"origin/{branch_name}"],
            cwd=repo_path,
            text=True,
            capture_output=True,
            check=False,
        )
        return f"origin/{branch_name}" if completed.returncode == 0 else None

    def _resolve_remote_branch(self, repo_path: Path, base_branch: str) -> str:
        remote_branch = self._resolve_remote_branch_ref(repo_path, base_branch)
        return remote_branch or base_branch

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
