import traceback
from collections.abc import Mapping
from pathlib import Path
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


def _read_plan_file(sandbox: dict) -> str:
    """Read PLAN.md written by the planning agent from the worktree."""
    worktree_path = sandbox.get("worktree_path", "")
    if not worktree_path:
        return ""
    try:
        plan_path = Path(worktree_path) / "PLAN.md"
        if plan_path.is_file():
            return plan_path.read_text(encoding="utf-8").strip()
    except OSError:
        logger.warning("failed to read PLAN.md from worktree", exc_info=True)
    return ""


def _post_plan_comment(task: AgentTaskRequest, plan_text: str) -> None:
    """Post the agent's plan as a GitHub issue comment."""
    if not (task.github_token and task.issue_id and "#" in task.issue_id):
        return
    try:
        repo, number_str = task.issue_id.rsplit("#", 1)
        if not number_str.isdigit() or "/" not in repo:
            return
        repo_owner, repo_name = repo.split("/", 1)
        body = (
            f"<!-- knight-plan -->\n\n"
            f"{plan_text}\n\n"
            f"---\n\n"
            f"Reply with `@knight CONFIRM` to start implementation."
        )
        post_issue_comment(
            repo_owner=repo_owner,
            repo_name=repo_name,
            issue_number=int(number_str),
            github_token=task.github_token,
            body=body,
        )
    except Exception:
        logger.exception("failed to post plan comment to GitHub")


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


def _resolve_execution_mode(
    task: AgentTaskRequest,
    cfg: ConfigStore,
) -> AgentTaskRequest:
    """Detect PLAN / NO-PLAN / CONFIRM keywords in task instructions and set execution_mode.

    Called for issue_comment tasks when the cloud dispatcher hasn't already set
    execution_mode (it always defaults to 'implement').

    Priority order:
      1. CONFIRM with a pending plan → implement with plan context
      2. NO-PLAN / NOPLAN → force implement (escapes sticky plan mode)
      3. Pending plan exists (no CONFIRM) → stay in plan mode (refine)
      4. Explicit PLAN keyword or config → enter plan mode
      5. Otherwise → implement (default)
    """
    instructions = task.instructions or ""

    # Helper: look up a pending plan for this issue.
    def _get_pending() -> "BranchRecord | None":
        if not (task.issue_id and "#" in task.issue_id):
            return None
        from knight.utils.local.state_store import BranchStateStore
        repo = task.issue_id.rsplit("#", 1)[0]
        return BranchStateStore().get_pending_plan(
            repository=repo, issue_id=task.issue_id
        )

    # 1. CONFIRM — implement the pending plan.
    if "CONFIRM" in instructions:
        pending = _get_pending()
        if pending:
            return task.model_copy(update={
                "execution_mode": "implement",
                "plan_context": pending.plan_text,
                "branch_name": task.branch_name or pending.agent_branch,
            })
        # No pending plan — fall through to normal detection

    # 2. NO-PLAN / NOPLAN → force implement, escapes sticky plan mode.
    if "NO-PLAN" in instructions or "NOPLAN" in instructions:
        return task

    # 3. Sticky plan mode — a pending plan exists, so any non-CONFIRM reply
    #    stays in plan mode and refines the existing plan.
    pending = _get_pending()
    if pending:
        return task.model_copy(update={
            "execution_mode": "plan",
            "plan_context": pending.plan_text,
            "branch_name": task.branch_name or pending.agent_branch,
        })

    # 4. Explicit PLAN keyword or config-based plan mode → enter plan mode.
    if "PLAN" in instructions or cfg.get_bool(key="plan_mode", default=False):
        return task.model_copy(update={"execution_mode": "plan"})

    return task


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

    # Resolve plan mode from instructions when the cloud dispatched the task
    # without execution_mode set (cloud webhook handler doesn't know about it).
    if task.execution_mode == "implement":
        task = _resolve_execution_mode(task, cfg)

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
            "execution_mode": task.execution_mode,
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

        # Plan mode: clear any prior session so the agent starts fresh.
        # If refining an existing plan, seed PLAN.md in the worktree so the
        # agent can read/edit it directly instead of receiving it in the prompt.
        if prepared_task.execution_mode == "plan":
            from knight.utils.local.session_store import AgentSessionStore
            AgentSessionStore().delete(prepared_task.issue_id)
            if prepared_task.plan_context and sandbox.get("worktree_path"):
                plan_path = Path(sandbox["worktree_path"]) / "PLAN.md"
                try:
                    plan_path.write_text(prepared_task.plan_context, encoding="utf-8")
                except OSError:
                    logger.warning("failed to seed PLAN.md in worktree", exc_info=True)

        agent = CodingAgentService()
        result = agent.run(prepared_task, sandbox=sandbox, log_config=log_config)

        # Plan mode: read PLAN.md NOW, before finalize_task removes the worktree.
        # If PLAN.md is missing the agent didn't follow instructions — retry once.
        plan_text_for_comment = ""
        if prepared_task.execution_mode == "plan":
            plan_text_for_comment = _read_plan_file(result.sandbox)
            if not plan_text_for_comment:
                logger.warning(
                    "plan mode: PLAN.md missing after agent run, retrying",
                    extra={"issue_id": prepared_task.issue_id},
                )
                result = agent.run(prepared_task, sandbox=sandbox, log_config=log_config)
                plan_text_for_comment = _read_plan_file(result.sandbox)
            if not plan_text_for_comment:
                plan_text_for_comment = result.final_message

        git_ops = WorkerGitOpsService()
        post_run = git_ops.finalize_task(
            task=prepared_task,
            sandbox=result.sandbox,
            agent_pr_url=result.pr_url,
        )

        # Plan mode: post the plan comment and save pending_confirmation state.
        if prepared_task.execution_mode == "plan":
            _post_plan_comment(prepared_task, plan_text_for_comment)
            if repository_identity and prepared_task.issue_id:
                from knight.utils.local.state_store import BranchRecord, BranchStateStore
                BranchStateStore().upsert_branch(BranchRecord(
                    repository=repository_identity,
                    issue_id=prepared_task.issue_id,
                    base_branch=prepared_task.base_branch,
                    agent_branch=prepared_task.branch_name,
                    status="pending_confirmation",
                    plan_text=plan_text_for_comment,
                ))

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
                "error_traceback": traceback.format_exc(),
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
