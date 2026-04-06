from typing import Any, Literal

from pydantic import BaseModel, Field


ToolName = Literal[
    "list_files",
    "read_file",
    "write_file",
    "replace_in_file",
    "search_files",
    "run_command",
]


class AgentTaskRequest(BaseModel):
    repository_url: str = ""
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
    workspace_summary: dict[str, Any] = Field(default_factory=dict)
    steps: list[ToolResult] = Field(default_factory=list)
    final_message: str = ""
    iterations: int = 0
