from pathlib import Path
import subprocess

from knight.agents.models import AgentTaskRequest
from knight.runtime.worktree import WorktreeProvisioner
from knight.worker.commit_message import CommitMessageService
from knight.worker.config import settings


class WorkerGitOpsService:
    def __init__(self) -> None:
        self.commit_messages = CommitMessageService()
        self.provisioner = WorktreeProvisioner()

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

        if commit_created and task.push_changes:
            push_attempted = True
            self._run(
                [
                    "git",
                    "push",
                    "--set-upstream",
                    task.push_remote,
                    sandbox["branch_name"],
                ],
                cwd=worktree_path,
            )
            push_completed = True

        if task.cleanup_worktree:
            self.provisioner.remove_worktree(
                repo_path=repo_path,
                worktree_path=worktree_path,
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
