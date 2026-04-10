from pathlib import Path
import subprocess

from knight.agents.models import AgentTaskRequest
from knight.runtime.logging_config import get_logger
from knight.runtime.repository_identity import normalize_repository_identity
from knight.runtime.worktree import WorktreeProvisioner
from knight.worker.commit_message import CommitMessageService
from knight.worker.config import settings
from knight.worker.state_store import BranchStateStore

logger = get_logger(__name__)


class WorkerGitOpsService:
    def __init__(self) -> None:
        self.commit_messages = CommitMessageService()
        self.provisioner = WorktreeProvisioner()
        self.state_store = BranchStateStore()

    def finalize_task(
        self,
        *,
        task: AgentTaskRequest,
        sandbox: dict[str, str],
    ) -> dict[str, object]:
        worktree_path = Path(sandbox["worktree_path"])
        repo_path = Path(sandbox["repo_path"])

        diff_text = self._run(["git", "diff", "--", "."], cwd=worktree_path).stdout
        status_text = self._run(["git", "status", "--short"], cwd=worktree_path).stdout
        has_changes = bool(status_text.strip())
        logger.info(
            "worker post-run diff evaluated",
            extra={
                "repository": normalize_repository_identity(
                    repository_url=task.repository_url,
                    repository_local_path=task.repository_local_path,
                ),
                "issue_id": task.issue_id,
                "branch_name": sandbox["branch_name"],
                "has_changes": has_changes,
            },
        )

        commit_message = ""
        commit_created = False
        push_attempted = False
        push_completed = False

        if has_changes and task.commit_changes:
            commit_message = self.commit_messages.generate(task=task, diff_text=diff_text)
            self._run(
                ["git", "config", "user.name", settings.worker_git_user_name],
                cwd=worktree_path,
            )
            self._run(
                ["git", "config", "user.email", settings.worker_git_user_email],
                cwd=worktree_path,
            )
            self._run(["git", "add", "--all"], cwd=worktree_path)
            self._run(["git", "commit", "-m", commit_message], cwd=worktree_path)
            commit_created = True
            logger.info(
                "worker commit created",
                extra={
                    "repository": normalize_repository_identity(
                        repository_url=task.repository_url,
                        repository_local_path=task.repository_local_path,
                    ),
                    "issue_id": task.issue_id,
                    "branch_name": sandbox["branch_name"],
                },
            )

        if commit_created and task.push_changes:
            push_attempted = True
            self._run(
                [
                    "git",
                    "push",
                    "--set-upstream",
                    task.push_remote or "origin",
                    sandbox["branch_name"],
                ],
                cwd=worktree_path,
            )
            push_completed = True
            logger.info(
                "worker branch pushed",
                extra={
                    "repository": normalize_repository_identity(
                        repository_url=task.repository_url,
                        repository_local_path=task.repository_local_path,
                    ),
                    "issue_id": task.issue_id,
                    "branch_name": sandbox["branch_name"],
                    "remote": task.push_remote or "origin",
                },
            )

        if task.cleanup_worktree:
            self.provisioner.remove_worktree(
                repo_path=repo_path,
                worktree_path=worktree_path,
            )
            logger.info(
                "worker worktree cleaned up",
                extra={
                    "repository": normalize_repository_identity(
                        repository_url=task.repository_url,
                        repository_local_path=task.repository_local_path,
                    ),
                    "issue_id": task.issue_id,
                    "branch_name": sandbox["branch_name"],
                    "worktree_path": str(worktree_path),
                },
            )

        repository_identity = normalize_repository_identity(
            repository_url=task.repository_url,
            repository_local_path=task.repository_local_path,
        )
        if repository_identity and task.issue_id:
            self.state_store.mark_branch_status(
                repository=repository_identity,
                issue_id=task.issue_id,
                agent_branch=sandbox["branch_name"],
                status="open",
            )

        return {
            "has_changes": has_changes,
            "commit_created": commit_created,
            "commit_message": commit_message,
            "push_attempted": push_attempted,
            "push_completed": push_completed,
            "cleanup_completed": task.cleanup_worktree,
            "status": status_text,
            "diff": diff_text[: settings.worker_commit_max_diff_chars],
        }

    def _run(self, command: list[str], *, cwd: Path):
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
        return completed
