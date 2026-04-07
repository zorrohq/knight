from typing import Any, Literal

from pydantic import BaseModel, Field


ToolName = Literal[
    "list_files",
    "read_file",
    "write_file",
    "replace_in_file",
    "search_files",
    "git_status",
    "git_diff",
    "run_command",
]


class AgentTaskRequest(BaseModel):
    repository_url: str = ""
    repository_local_path: str = ""
    issue_id: str = ""
    base_branch: str = "main"
    branch_name: str = ""
    push_remote: str = "origin"
    commit_changes: bool = True
    push_changes: bool = True
    cleanup_worktree: bool = True
    workspace_path: str = "."
    task_type: str = "repository_task"
    instructions: str = ""


class ToolResult(BaseModel):
    tool: ToolName
    success: bool
    output: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class AgentRunResult(BaseModel):
    status: str
    provider_configured: bool
    task: AgentTaskRequest
    available_tools: list[ToolName]
    sandbox: dict[str, Any] = Field(default_factory=dict)
    workspace_summary: dict[str, Any] = Field(default_factory=dict)
    steps: list[ToolResult] = Field(default_factory=list)
    final_message: str = ""
    iterations: int = 0
