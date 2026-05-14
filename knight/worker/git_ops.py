from __future__ import annotations

import re
from pathlib import Path
import subprocess

from knight.agents.models import AgentTaskRequest
from knight.runtime.authorship import (
    add_coauthor_trailer,
    make_identity,
)
from knight.worker.github_notifications import create_pr, post_no_changes_notification
from knight.runtime.logging_config import get_logger
from knight.runtime.repository_identity import normalize_repository_identity
from knight.runtime.worktree import WorktreeProvisioner
from knight.utils.local.state_store import BranchStateStore
from knight.worker.commit_message import CommitMessageService
from knight.worker.pr_description import ChangelogService
from knight.worker.config import settings

logger = get_logger(__name__)

_GIT_TIMEOUT = 120

_CREDENTIAL_RE = re.compile(r"(https?://)([^@\s]+@)", re.IGNORECASE)


def _scrub_credentials(text: str) -> str:
    """Remove userinfo (credentials) from any URLs in an error string."""
    return _CREDENTIAL_RE.sub(r"\1<redacted>@", text)


class WorkerGitOpsService:
    def __init__(self) -> None:
        self.commit_messages = CommitMessageService()
        self.changelog = ChangelogService()
        self.provisioner = WorktreeProvisioner()
        self.state_store = BranchStateStore()
        self._cached_changelog: str = ""

    def finalize_task(
        self,
        *,
        task: AgentTaskRequest,
        sandbox: dict[str, str],
        agent_pr_url: str = "",
    ) -> dict[str, object]:
        worktree_path = Path(sandbox["worktree_path"])
        repo_path = Path(sandbox["repo_path"])
        repository_identity = normalize_repository_identity(
            repository_url=task.repository_url,
            repository_local_path=task.repository_local_path,
        )

        diff_text = self._run(["git", "diff", "--", "."], cwd=worktree_path).stdout
        status_text = self._run(["git", "status", "--short"], cwd=worktree_path).stdout
        has_changes = bool(status_text.strip())

        # Plan mode: agent only read the codebase — skip all git operations
        if task.execution_mode == "plan":
            if task.cleanup_worktree:
                self.provisioner.remove_worktree(
                    repo_path=repo_path,
                    worktree_path=worktree_path,
                    branch_name=sandbox["branch_name"],
                )
            return {
                "has_changes": False,
                "commit_created": False,
                "commit_message": "",
                "push_attempted": False,
                "push_completed": False,
                "cleanup_completed": task.cleanup_worktree,
                "pr_url": "",
                "status": "",
                "diff": "",
            }

        logger.info(
            "worker post-run diff evaluated",
            extra={
                "repository": repository_identity,
                "issue_id": task.issue_id,
                "branch_name": sandbox["branch_name"],
                "has_changes": has_changes,
                "agent_pr_url": agent_pr_url,
            },
        )

        commit_message = ""
        commit_created = False
        commit_sha = ""
        push_attempted = False
        push_completed = False
        pr_url = agent_pr_url

        # Build commit attribution
        identity = make_identity(name=task.author_name, email=task.author_email)

        if not has_changes:
            post_no_changes_notification(
                task=task,
                repository_identity=repository_identity,
                sandbox=sandbox,
                github_token=task.github_token or settings.github_token,
            )

        if has_changes and task.commit_changes:
            raw_message, self._cached_changelog = self.commit_messages.generate_both(task=task, diff_text=diff_text)
            commit_message = add_coauthor_trailer(raw_message, identity)

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
            try:
                sha_result = self._run(["git", "rev-parse", "--short", "HEAD"], cwd=worktree_path)
                commit_sha = sha_result.stdout.strip()
            except Exception:
                commit_sha = ""
            logger.info(
                "worker commit created",
                extra={
                    "repository": repository_identity,
                    "issue_id": task.issue_id,
                    "branch_name": sandbox["branch_name"],
                    "commit_sha": commit_sha,
                },
            )

        if commit_created and task.push_changes:
            push_attempted = True
            push_remote = task.push_remote or "origin"
            if task.github_token and task.repository_url:
                authed_url = WorktreeProvisioner._inject_token_into_url(task.repository_url, task.github_token)
                self._run(["git", "remote", "set-url", push_remote, authed_url], cwd=worktree_path)
            self._run(
                ["git", "push", "--set-upstream", push_remote, sandbox["branch_name"]],
                cwd=worktree_path,
            )
            push_completed = True
            logger.info(
                "worker branch pushed",
                extra={
                    "repository": repository_identity,
                    "issue_id": task.issue_id,
                    "branch_name": sandbox["branch_name"],
                    "remote": task.push_remote or "origin",
                },
            )

        # GitHub PR creation — worker creates PR if agent didn't already
        if push_completed and not pr_url:
            github_token = task.github_token or settings.github_token
            pr_url = create_pr(
                task=task,
                sandbox=sandbox,
                repository_identity=repository_identity,
                github_token=github_token,
                identity_name=identity.display_name if identity else "",
                identity_email=identity.commit_email if identity else "",
                diff_text=diff_text,
                commit_sha=commit_sha,
                cached_changelog=self._cached_changelog,
                changelog_service=self.changelog,
            )

        if task.cleanup_worktree:
            self.provisioner.remove_worktree(
                repo_path=repo_path,
                worktree_path=worktree_path,
                branch_name=sandbox["branch_name"],
            )
            logger.info(
                "worker worktree cleaned up",
                extra={
                    "repository": repository_identity,
                    "issue_id": task.issue_id,
                    "branch_name": sandbox["branch_name"],
                    "worktree_path": str(worktree_path),
                },
            )

        if repository_identity and task.issue_id:
            branch_status = "pushed" if push_completed else "open"
            self.state_store.mark_branch_status(
                repository=repository_identity,
                issue_id=task.issue_id,
                agent_branch=sandbox["branch_name"],
                status=branch_status,
            )

        return {
            "has_changes": has_changes,
            "commit_created": commit_created,
            "commit_message": commit_message,
            "push_attempted": push_attempted,
            "push_completed": push_completed,
            "cleanup_completed": task.cleanup_worktree,
            "pr_url": pr_url,
            "status": status_text,
            "diff": diff_text[: settings.worker_commit_max_diff_chars],
        }

    def _run(self, command: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
        completed = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            capture_output=True,
            timeout=_GIT_TIMEOUT,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                _scrub_credentials(completed.stderr.strip())
                or _scrub_credentials(completed.stdout.strip())
                or f"command failed: {' '.join(command)}"
            )
        return completed
