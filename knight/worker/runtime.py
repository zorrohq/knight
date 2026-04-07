from typing import Any

from knight.agents.models import AgentTaskRequest
from knight.runtime.worktree import WorktreeProvisioner


class WorkerRuntimeService:
    def __init__(self) -> None:
        self.provisioner = WorktreeProvisioner()

    def prepare_task(
        self,
        task: AgentTaskRequest,
    ) -> tuple[AgentTaskRequest, dict[str, Any]]:
        sandbox = self.provisioner.prepare_worktree(
            repository_url=task.repository_url,
            repository_local_path=task.repository_local_path,
            issue_id=task.issue_id or "default",
            base_branch=task.base_branch,
            branch_name=task.branch_name,
        )
        prepared_task = task.model_copy(
            update={"workspace_path": str(sandbox.worktree_path)}
        )
        sandbox_metadata = {
            "repository_key": sandbox.repository_key,
            "issue_key": sandbox.issue_key,
            "branch_name": sandbox.branch_name,
            "sandbox_root": str(sandbox.sandbox_root),
            "repo_path": str(sandbox.repo_path),
            "worktree_path": str(sandbox.worktree_path),
        }
        return prepared_task, sandbox_metadata
