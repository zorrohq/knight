from collections.abc import Mapping
from typing import Any

import httpx
from billiard.exceptions import SoftTimeLimitExceeded

from knight.agents.models import AgentTaskRequest
from knight.agents.service import CodingAgentService
from knight.runtime.github import post_issue_comment, react_to_comment
from knight.runtime.logging_config import get_logger, setup_logging
from knight.runtime.repository_identity import normalize_repository_identity
from knight.utils.local.config_store import ConfigStore
from knight.worker.celery_app import _DLQ_QUEUE, celery_app
from knight.worker.git_ops import WorkerGitOpsService
from knight.worker.runtime import WorkerRuntimeService

logger = get_logger(__name__)


def _report_job_result(
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


def _post_error_comment(task: AgentTaskRequest, message: str) -> None:
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


@celery_app.task(
    bind=True,
    name="knight.worker.tasks.run_agent_task",
    # Hard safety net above pi's own timeout (25 steps * 300s = 7500s).
    # soft_time_limit raises SoftTimeLimitExceeded for graceful cleanup;
    # time_limit is the absolute kill, preventing zombie worker slots.
    soft_time_limit=8400,  # 140 min
    time_limit=9000,        # 150 min
    acks_late=True,
    reject_on_worker_lost=True,
    # One retry for transient infra failures (DB down, clone error, etc.).
    # SoftTimeLimitExceeded is excluded — no point consuming another slot.
    max_retries=1,
    default_retry_delay=90,
)
def run_agent_task(
    self, payload: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    log_config = setup_logging()
    task = AgentTaskRequest.model_validate(payload or {})
    cfg = ConfigStore()
    _cloud_url = cfg.get_string(key="cloud_url", default="https://knight.zorro.works")
    _daemon_token = cfg.get_string(key="daemon_token")
    repository_identity = normalize_repository_identity(
        repository_url=task.repository_url,
        repository_local_path=task.repository_local_path,
    )
    logger.info(
        "worker task started",
        extra={
            "task_id": self.request.id,
            "repository": repository_identity,
            "issue_id": task.issue_id,
            "task_type": task.task_type,
        },
    )

    if task.trigger_comment_id and task.github_token and "/" in (task.issue_id or ""):
        repo_owner, repo_name = repository_identity.split("/", 1)
        react_to_comment(
            repo_owner=repo_owner,
            repo_name=repo_name,
            comment_id=task.trigger_comment_id,
            github_token=task.github_token,
        )

    try:
        runtime = WorkerRuntimeService()
        prepared_task, sandbox = runtime.prepare_task(task)
        logger.info(
            "workspace prepared",
            extra={
                "task_id": self.request.id,
                "repository": repository_identity,
                "issue_id": prepared_task.issue_id,
                "branch_name": prepared_task.branch_name,
                "base_branch": prepared_task.base_branch,
                "workspace_path": prepared_task.workspace_path,
            },
        )

        agent = CodingAgentService()
        result = agent.run(prepared_task, sandbox=sandbox, log_config=log_config)

        git_ops = WorkerGitOpsService()
        post_run = git_ops.finalize_task(
            task=prepared_task,
            sandbox=result.sandbox,
            agent_pr_url=result.pr_url,
        )

    except SoftTimeLimitExceeded:
        logger.error(
            "worker task hit soft time limit",
            extra={"task_id": self.request.id, "repository": repository_identity, "issue_id": task.issue_id},
        )
        _post_error_comment(
            task,
            "I ran out of time working on this and had to stop. "
            "You can trigger me again and I'll pick up where I left off.",
        )
        _report_job_result(task.cloud_job_id, cloud_url=_cloud_url, token=_daemon_token, status="failed", result_status="timeout")
        raise

    except Exception as exc:
        logger.exception(
            "worker task failed with unhandled exception",
            extra={"task_id": self.request.id, "repository": repository_identity, "issue_id": task.issue_id},
        )
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)

        # Retries exhausted — post error comment and report failure to cloud
        # (cloud tracks attempt count and transitions to blocked once MAX_JOB_ATTEMPTS is reached).
        _post_error_comment(
            task,
            "I hit an unexpected error while working on this. "
            "Check the logs for details, or trigger me again to retry.",
        )
        _report_job_result(
            task.cloud_job_id,
            cloud_url=_cloud_url,
            token=_daemon_token,
            status="failed",
            result_status="error",
            final_message=str(exc),
        )
        from knight.worker.tasks.dlq_task import record_dlq_entry
        record_dlq_entry.apply_async(
            kwargs={
                "original_task_id": self.request.id or "",
                "payload": dict(payload or {}),
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
            queue=_DLQ_QUEUE,
        )
        raise

    logger.info(
        "worker task completed",
        extra={
            "task_id": self.request.id,
            "repository": repository_identity,
            "issue_id": prepared_task.issue_id,
            "branch_name": prepared_task.branch_name,
            "status": result.status,
            "iterations": result.iterations,
            "post_run_has_changes": post_run["has_changes"],
            "post_run_commit_created": post_run["commit_created"],
            "post_run_push_completed": post_run["push_completed"],
            "post_run_pr_url": post_run.get("pr_url") or result.pr_url,
        },
    )

    _report_job_result(
        task.cloud_job_id,
        cloud_url=_cloud_url,
        token=_daemon_token,
        status="completed",
        result_status=result.status,
        pr_url=post_run.get("pr_url") or result.pr_url,
        final_message=result.final_message,
        iterations=result.iterations,
    )

    task_dump = result.task.model_dump()
    task_dump["github_token"] = "<redacted>"
    return {
        "task_id": self.request.id,
        "status": result.status,
        "provider_configured": result.provider_configured,
        "final_message": result.final_message,
        "iterations": result.iterations,
        "task": task_dump,
        "available_tools": result.available_tools,
        "sandbox": result.sandbox,
        "workspace_summary": result.workspace_summary,
        "steps": [step.model_dump() for step in result.steps],
        "pr_url": post_run.get("pr_url") or result.pr_url,
        "post_run": post_run,
    }
