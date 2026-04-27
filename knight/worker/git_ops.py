from __future__ import annotations

import re
from pathlib import Path
import subprocess

from knight.agents.models import AgentTaskRequest
from knight.runtime.authorship import (
    KNIGHT_BOT_EMAIL,
    KNIGHT_BOT_NAME,
    CollaboratorIdentity,
    add_coauthor_trailer,
    add_pr_collaboration_note,
    make_identity,
)
from knight.runtime.github import create_github_pr, get_github_default_branch, post_issue_comment, post_pr_comment
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
                    "repository": repository_identity,
                    "issue_id": task.issue_id,
                    "branch_name": sandbox["branch_name"],
                    "remote": task.push_remote or "origin",
                },
            )

        # GitHub PR creation — worker creates PR if agent didn't already
        if push_completed and not pr_url:
            github_token = task.github_token or settings.github_token
            pr_url = self._create_pr(
                task=task,
                sandbox=sandbox,
                repository_identity=repository_identity,
                github_token=github_token,
                identity_name=identity.display_name if identity else "",
                identity_email=identity.commit_email if identity else "",
                diff_text=diff_text,
                commit_sha=commit_sha,
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

    def _create_pr(
        self,
        *,
        task: AgentTaskRequest,
        sandbox: dict[str, str],
        repository_identity: str,
        github_token: str,
        identity_name: str,
        identity_email: str,
        diff_text: str = "",
        commit_sha: str = "",
    ) -> str:
        if not github_token:
            return ""
        if "/" not in repository_identity:
            logger.warning(
                "cannot create PR: repository identity not in owner/repo format: %s",
                repository_identity,
            )
            return ""

        repo_owner, repo_name = repository_identity.split("/", 1)
        title = f"feat: {task.task_type} for {task.issue_id}" if task.issue_id else f"feat: {task.task_type}"
        changelog = self._cached_changelog or self.changelog.generate(task=task, diff_text=diff_text)
        body = self.changelog._issue_ref(task)
        body = f"{changelog}\n\n---\n\n{body}" if body else changelog

        # Add collaboration note if we have user identity
        identity = (
            CollaboratorIdentity(
                display_name=identity_name,
                commit_name=identity_name,
                commit_email=identity_email,
            )
            if identity_name and identity_email
            else None
        )
        body = add_pr_collaboration_note(body, identity)

        try:
            base_branch = get_github_default_branch(
                repo_owner=repo_owner,
                repo_name=repo_name,
                github_token=github_token,
            )
            pr_url, pr_number, pr_existing = create_github_pr(
                repo_owner=repo_owner,
                repo_name=repo_name,
                github_token=github_token,
                title=title,
                head_branch=sandbox["branch_name"],
                base_branch=base_branch,
                body=body,
            )
            if pr_url:
                logger.info(
                    "worker PR %s: %s",
                    "found existing" if pr_existing else "created",
                    pr_url,
                    extra={
                        "repository": repository_identity,
                        "issue_id": task.issue_id,
                        "pr_url": pr_url,
                        "pr_existing": pr_existing,
                    },
                )
                if pr_existing and pr_number and diff_text:
                    update_comment = self._cached_changelog or self.changelog.generate(task=task, diff_text=diff_text)
                    post_pr_comment(
                        repo_owner=repo_owner,
                        repo_name=repo_name,
                        pr_number=pr_number,
                        github_token=github_token,
                        body=update_comment,
                    )
                self._post_pr_notification(
                    task=task,
                    repo_owner=repo_owner,
                    repo_name=repo_name,
                    github_token=github_token,
                    pr_url=pr_url,
                    pr_existing=pr_existing,
                    commit_sha=commit_sha,
                )
                return pr_url
        except Exception:
            logger.exception(
                "worker PR creation failed",
                extra={"repository": repository_identity, "issue_id": task.issue_id},
            )
        return ""

    def _post_pr_notification(
        self,
        *,
        task: AgentTaskRequest,
        repo_owner: str,
        repo_name: str,
        github_token: str,
        pr_url: str,
        pr_existing: bool = False,
        commit_sha: str = "",
    ) -> None:
        if not task.issue_id or "#" not in task.issue_id:
            return
        number = task.issue_id.split("#", 1)[-1]
        if not number.isdigit():
            return
        mention = f"@{task.author_name}" if task.author_name else "Hey"
        sha_line = f"\n\n<!-- knight -->\nCommit: `{commit_sha}`" if commit_sha else ""
        if pr_existing:
            comment = f"Hey {mention}! I've pushed updates to the existing PR: {pr_url}{sha_line}"
        else:
            comment = f"Hey {mention}! I've opened a PR for your review: {pr_url}{sha_line}"
        post_issue_comment(
            repo_owner=repo_owner,
            repo_name=repo_name,
            issue_number=int(number),
            github_token=github_token,
            body=comment,
        )

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
