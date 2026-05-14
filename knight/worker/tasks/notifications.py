import httpx

from knight.agents.models import AgentTaskRequest
from knight.runtime.github import post_issue_comment
from knight.runtime.logging_config import get_logger

logger = get_logger(__name__)


def report_job_result(
    job_id: str,
    *,
    cloud_url: str,
    token: str,
    status: str,
    result_status: str = "",
    block_reason: str = "",
    pr_url: str = "",
    final_message: str = "",
    iterations: int = 0,
) -> None:
    """POST job result back to the cloud coordination server."""
    if not job_id or not token:
        return
    try:
        with httpx.Client(base_url=cloud_url, headers={"Authorization": f"Bearer {token}"}, timeout=15) as client:
            client.post(
                f"/api/knight/daemon/jobs/{job_id}/result",
                json={
                    "status": status,
                    "result_status": result_status or None,
                    "block_reason": block_reason or None,
                    "pr_url": pr_url or None,
                    "final_message": final_message or None,
                    "iterations": iterations or None,
                },
            )
        logger.info("job result reported to cloud", extra={"job_id": job_id, "status": status})
    except Exception:
        logger.exception("failed to report job result to cloud", extra={"job_id": job_id})


def post_error_comment(task: AgentTaskRequest, message: str) -> None:
    """Post an error comment to the issue if we have enough context to do so."""
    if not (task.github_token and task.issue_id and "#" in task.issue_id):
        return
    try:
        repo, number_str = task.issue_id.rsplit("#", 1)
        if not number_str.isdigit() or "/" not in repo:
            return
        repo_owner, repo_name = repo.split("/", 1)
        post_issue_comment(
            repo_owner=repo_owner,
            repo_name=repo_name,
            issue_number=int(number_str),
            github_token=task.github_token,
            body=message,
        )
    except Exception:
        logger.exception("failed to post error comment to GitHub")
