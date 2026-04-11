from typing import Annotated, Any, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

from knight.agents.models import AgentTaskRequest, ToolName, ToolResult


class AgentState(TypedDict):
    task: AgentTaskRequest
    sandbox: dict[str, Any]
    runtime_config: dict[str, Any]
    provider_configured: bool
    available_tools: list[ToolName]
    workspace_summary: dict[str, Any]
    steps: list[ToolResult]
    messages: Annotated[list[BaseMessage], add_messages]
    status: str
    iterations: int
    final_message: str
