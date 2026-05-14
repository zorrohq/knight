from __future__ import annotations

from knight.agents.models import AgentTaskRequest
from knight.runtime.authorship import CollaboratorIdentity, add_pr_collaboration_note
from knight.runtime.github import find_existing_pr, create_github_pr, get_github_default_branch, post_issue_comment, post_pr_comment
from knight.runtime.logging_config import get_logger
from knight.worker.pr_description import ChangelogService

logger = get_logger(__name__)


def create_pr(
    *,
    task: AgentTaskRequest,
    sandbox: dict[str, str],
    repository_identity: str,
    github_token: str,
    identity_name: str,
    identity_email: str,
    diff_text: str = "",
    commit_sha: str = "",
    cached_changelog: str = "",
    changelog_service: ChangelogService,
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
    changelog = cached_changelog or changelog_service.generate(task=task, diff_text=diff_text)
    body = changelog_service._issue_ref(task)
    body = f"{changelog}\n\n---\n\n{body}" if body else changelog

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
                update_comment = cached_changelog or changelog_service.generate(task=task, diff_text=diff_text)
                post_pr_comment(
                    repo_owner=repo_owner,
                    repo_name=repo_name,
                    pr_number=pr_number,
                    github_token=github_token,
                    body=update_comment,
                )
            post_pr_notification(
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


def post_pr_notification(
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
    greeting = f"Hey @{task.author_name}!" if task.author_name else "Hey!"
    sha_line = f"\n\n<!-- knight -->\nCommit: `{commit_sha}`" if commit_sha else ""
    if pr_existing:
        comment = f"{greeting} I've pushed updates to the existing PR: {pr_url}{sha_line}"
    else:
        comment = f"{greeting} I've opened a PR for your review: {pr_url}{sha_line}"
    post_issue_comment(
        repo_owner=repo_owner,
        repo_name=repo_name,
        issue_number=int(number),
        github_token=github_token,
        body=comment,
    )


def post_no_changes_notification(
    *,
    task: AgentTaskRequest,
    repository_identity: str,
    sandbox: dict[str, str],
    github_token: str,
) -> None:
    if not task.issue_id or "#" not in task.issue_id or "/" not in repository_identity:
        return
    if not github_token:
        return
    number = task.issue_id.split("#", 1)[-1]
    if not number.isdigit():
        return
    repo_owner, repo_name = repository_identity.split("/", 1)
    mention = f"@{task.author_name}" if task.author_name else "Hey"
    try:
        pr_url, _ = find_existing_pr(
            repo_owner=repo_owner,
            repo_name=repo_name,
            github_token=github_token,
            head_branch=sandbox["branch_name"],
        )
        if pr_url:
            comment = (
                f"Hey {mention}! Looks like I already worked on this — "
                f"there's a PR with my changes here: {pr_url}\n\n"
                f"Tag me with `@knight` if you'd like me to make any adjustments."
            )
        else:
            comment = (
                f"Hey {mention}! I reviewed the codebase but didn't find anything to change.\n\n"
                f"Tag me with `@knight` if I missed something or you'd like me to try a different approach."
            )
        post_issue_comment(
            repo_owner=repo_owner,
            repo_name=repo_name,
            issue_number=int(number),
            github_token=github_token,
            body=comment,
        )
    except Exception:
        logger.exception(
            "failed to post no-changes notification",
            extra={"repository": repository_identity, "issue_id": task.issue_id},
        )
