from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, START, StateGraph

from knight.agents.config import settings
from knight.agents.models import AgentRunResult, AgentTaskRequest, ToolResult
from knight.agents.state import AgentState
from knight.agents.tools import AgentToolset
from knight.runtime.command_runner import LocalCommandRunner
from knight.runtime.filesystem import LocalWorkspace


def build_initial_state(task: AgentTaskRequest) -> AgentState:
    provider_configured = bool(settings.agent_provider and settings.agent_model)
    return {
        "task": task,
        "provider_configured": provider_configured,
        "available_tools": [],
        "workspace_summary": {},
        "steps": [],
        "messages": [HumanMessage(content=task.instructions)],
        "status": "pending",
    }


def inspect_workspace(state: AgentState) -> AgentState:
    workspace = LocalWorkspace(state["task"].workspace_path)
    toolset = AgentToolset(
        workspace=workspace,
        command_runner=LocalCommandRunner(),
    )
    tools = toolset.build_tools()
    top_level_files = toolset.list_files(path=".", recursive=False)

    step = ToolResult(
        tool="list_files",
        success=True,
        output=top_level_files,
    )

    return {
        **state,
        "available_tools": [tool.name for tool in tools],
        "workspace_summary": {
            "root": str(workspace.root),
            "top_level_files": top_level_files["files"],
        },
        "steps": [*state["steps"], step],
        "messages": [
            *state["messages"],
            AIMessage(
                content=(
                    "Workspace inspection completed. Provider-driven planning is not "
                    "wired yet; tools and workspace context are ready."
                )
            ),
        ],
        "status": "ready" if state["provider_configured"] else "awaiting_provider",
    }


def finalize(state: AgentState) -> AgentState:
    return state


def build_agent_graph():
    graph = StateGraph(AgentState)
    graph.add_node("inspect_workspace", inspect_workspace)
    graph.add_node("finalize", finalize)
    graph.add_edge(START, "inspect_workspace")
    graph.add_edge("inspect_workspace", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile()


class AgentGraphRunner:
    def __init__(self) -> None:
        self.graph = build_agent_graph()

    def run(self, task: AgentTaskRequest) -> AgentRunResult:
        final_state = self.graph.invoke(build_initial_state(task))
        return AgentRunResult(
            status=final_state["status"],
            provider_configured=final_state["provider_configured"],
            task=final_state["task"],
            available_tools=final_state["available_tools"],
            workspace_summary=final_state["workspace_summary"],
            steps=final_state["steps"],
        )
