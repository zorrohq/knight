from pathlib import Path

from knight.agents.models import AgentTaskRequest
from knight.runtime.github import post_issue_comment
from knight.runtime.logging_config import get_logger
from knight.utils.local.config_store import ConfigStore

logger = get_logger(__name__)


def read_plan_file(sandbox: dict) -> str:
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


def post_plan_comment(task: AgentTaskRequest, plan_text: str) -> None:
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


def resolve_execution_mode(
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
