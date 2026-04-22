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
    "http_request",
    "fetch_url",
]


class AgentTaskRequest(BaseModel):
    repository_url: str = ""
    repository_local_path: str = ""
    issue_id: str = ""
    base_branch: str = ""
    branch_name: str = ""
    push_remote: str = ""
    commit_changes: bool = True
    push_changes: bool = True
    cleanup_worktree: bool = True
    workspace_path: str = "."
    task_type: str = "repository_task"
    instructions: str = ""
    github_token: str = ""
    author_name: str = ""
    author_email: str = ""
    trigger_comment_id: int | None = None


class ToolResult(BaseModel):
    tool: str
    success: bool
    output: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class AgentRunResult(BaseModel):
    status: str
    provider_configured: bool
    task: AgentTaskRequest
    available_tools: list[str]
    sandbox: dict[str, Any] = Field(default_factory=dict)
    workspace_summary: dict[str, Any] = Field(default_factory=dict)
    steps: list[ToolResult] = Field(default_factory=list)
    final_message: str = ""
    iterations: int = 0
    pr_url: str = ""
