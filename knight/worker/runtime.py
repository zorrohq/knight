from typing import Any

from knight.agents.models import AgentTaskRequest
from knight.runtime.logging_config import get_logger
from knight.runtime.repository_identity import normalize_repository_identity
from knight.runtime.worktree import WorktreeProvisioner
from knight.utils.db.state_store import BranchRecord, BranchStateStore

logger = get_logger(__name__)


class WorkerRuntimeService:
    def __init__(self) -> None:
        self.provisioner = WorktreeProvisioner()
        self.state_store = BranchStateStore()

    def prepare_task(
        self,
        task: AgentTaskRequest,
    ) -> tuple[AgentTaskRequest, dict[str, Any]]:
        repository_identity = normalize_repository_identity(
            repository_url=task.repository_url,
            repository_local_path=task.repository_local_path,
        )
        existing_record = None
        if repository_identity and task.issue_id:
            existing_record = self.state_store.get_open_branch(
                repository=repository_identity,
                issue_id=task.issue_id,
            )

        resolved_branch_name = task.branch_name or (
            existing_record.agent_branch if existing_record else ""
        )
        logger.info(
            "preparing worker sandbox",
            extra={
                "repository": repository_identity,
                "issue_id": task.issue_id,
                "requested_branch_name": task.branch_name,
                "resolved_branch_name": resolved_branch_name,
                "existing_branch_record": bool(existing_record),
            },
        )
        sandbox = self.provisioner.prepare_worktree(
            repository_url=task.repository_url,
            repository_local_path=task.repository_local_path,
            issue_id=task.issue_id or "default",
            base_branch=task.base_branch,
            branch_name=resolved_branch_name,
        )
        prepared_task = task.model_copy(
            update={
                "workspace_path": str(sandbox.worktree_path),
                "branch_name": sandbox.branch_name,
                "base_branch": sandbox.base_branch,
            }
        )
        if repository_identity and task.issue_id:
            self.state_store.upsert_branch(
                BranchRecord(
                    repository=repository_identity,
                    issue_id=task.issue_id,
                    base_branch=sandbox.base_branch,
                    agent_branch=sandbox.branch_name,
                    status="open",
                )
            )
        sandbox_metadata = {
            "repository_key": sandbox.repository_key,
            "issue_key": sandbox.issue_key,
            "branch_name": sandbox.branch_name,
            "sandbox_root": str(sandbox.sandbox_root),
            "repo_path": str(sandbox.repo_path),
            "worktree_path": str(sandbox.worktree_path),
        }
        logger.info(
            "worker sandbox prepared",
            extra={
                "repository": repository_identity,
                "issue_id": task.issue_id,
                "branch_name": sandbox.branch_name,
                "base_branch": sandbox.base_branch,
                "repo_path": str(sandbox.repo_path),
                "worktree_path": str(sandbox.worktree_path),
            },
        )
        return prepared_task, sandbox_metadata
