from typing import Any, TypedDict

from langchain_core.messages import BaseMessage

from knight.agents.models import AgentTaskRequest, ToolName, ToolResult


class AgentState(TypedDict):
    task: AgentTaskRequest
    provider_configured: bool
    available_tools: list[ToolName]
    workspace_summary: dict[str, Any]
    steps: list[ToolResult]
    messages: list[BaseMessage]
    status: str
