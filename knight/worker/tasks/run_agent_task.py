from collections.abc import Mapping
from typing import Any

from knight.agents.models import AgentTaskRequest
from knight.agents.service import CodingAgentService
from knight.runtime.logging_config import get_logger, setup_logging
from knight.runtime.repository_identity import normalize_repository_identity
from knight.worker.celery_app import celery_app
from knight.worker.git_ops import WorkerGitOpsService
from knight.worker.runtime import WorkerRuntimeService

logger = get_logger(__name__)


@celery_app.task(
    bind=True,
    name="knight.worker.tasks.run_agent_task",
)
def run_agent_task(
    self, payload: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    log_config = setup_logging()
    task = AgentTaskRequest.model_validate(payload or {})
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
