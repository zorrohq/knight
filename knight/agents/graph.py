from __future__ import annotations

import json

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph

from knight.agents.config import settings
from knight.agents.llm import create_agent_model
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
        "iterations": 0,
        "final_message": "",
    }


def build_system_message(state: AgentState) -> SystemMessage:
    task = state["task"]
    summary = state["workspace_summary"]
    top_level_files = ", ".join(summary.get("top_level_files", []))
    content = (
        f"{settings.agent_system_prompt}\n\n"
        f"Task type: {task.task_type}\n"
        f"Repository URL: {task.repository_url or 'not provided'}\n"
        f"Workspace root: {summary.get('root', task.workspace_path)}\n"
        f"Top-level files: {top_level_files or 'none'}\n"
        f"Maximum tool iterations: {settings.agent_max_steps}\n"
        f"Blocked command prefixes: {', '.join(settings.agent_blocked_command_prefixes)}\n"
        "When you have completed the task, respond with a concise summary and do not "
        "emit any more tool calls."
    )
    return SystemMessage(content=content)


def get_toolset(state: AgentState) -> AgentToolset:
    workspace_path = state["task"].workspace_path or settings.agent_workspace_root
    return AgentToolset(
        workspace=LocalWorkspace(workspace_path),
        command_runner=LocalCommandRunner(),
    )


def inspect_workspace(state: AgentState) -> AgentState:
    toolset = get_toolset(state)
    tools = toolset.build_tools()
    top_level_files = toolset.list_files(path=".", recursive=False)

    step = ToolResult(
        tool="list_files",
        success=True,
        output=top_level_files,
    )

    status = "ready" if state["provider_configured"] else "awaiting_provider"

    return {
        **state,
        "available_tools": [tool.name for tool in tools],
        "workspace_summary": {
            "root": str(toolset.workspace.root),
            "top_level_files": top_level_files["files"],
        },
        "steps": [*state["steps"], step],
        "status": status,
        "final_message": (
            ""
            if state["provider_configured"]
            else "Agent tools are ready, but no provider is configured."
        ),
    }


def call_model(state: AgentState) -> AgentState:
    model = create_agent_model()
    if model is None:
        return {
            **state,
            "status": "awaiting_provider",
        }

    toolset = get_toolset(state)
    bound_model = model.bind_tools(toolset.build_tools())
    response = bound_model.invoke([build_system_message(state), *state["messages"]])

    return {
        **state,
        "messages": [response],
        "iterations": state["iterations"] + 1,
        "status": "running",
    }


def execute_tools(state: AgentState) -> AgentState:
    tool_map = get_toolset(state).build_tool_map()
    last_message = state["messages"][-1]
    if not isinstance(last_message, AIMessage):
        return state

    tool_messages: list[ToolMessage] = []
    step_results = list(state["steps"])

    for tool_call in last_message.tool_calls:
        tool_name = tool_call["name"]
        tool = tool_map.get(tool_name)
        if tool is None:
            step_result = ToolResult(
                tool=tool_name,  # type: ignore[arg-type]
                success=False,
                error=f"unknown tool: {tool_name}",
            )
            tool_messages.append(
                ToolMessage(
                    content=step_result.error,
                    tool_call_id=tool_call["id"],
                    name=tool_name,
                    status="error",
                )
            )
            step_results.append(step_result)
            continue

        try:
            output = tool.invoke(tool_call["args"])
            success = bool(output.get("exit_code", 0) == 0) if tool_name == "run_command" else True
            step_result = ToolResult(
                tool=tool_name,  # type: ignore[arg-type]
                success=success,
                output=output,
                error=None if success else "command failed",
            )
            tool_messages.append(
                ToolMessage(
                    content=json.dumps(output, ensure_ascii=True),
                    tool_call_id=tool_call["id"],
                    name=tool_name,
                    status="success" if success else "error",
                )
            )
        except Exception as exc:
            step_result = ToolResult(
                tool=tool_name,  # type: ignore[arg-type]
                success=False,
                error=str(exc),
            )
            tool_messages.append(
                ToolMessage(
                    content=str(exc),
                    tool_call_id=tool_call["id"],
                    name=tool_name,
                    status="error",
                )
            )

        step_results.append(step_result)

    return {
        **state,
        "messages": tool_messages,
        "steps": step_results,
        "status": "running",
    }


def should_continue(state: AgentState) -> str:
    if not state["provider_configured"]:
        return "finalize"

    if state["iterations"] >= settings.agent_max_steps:
        return "finalize"

    last_message = state["messages"][-1]
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "execute_tools"

    return "finalize"


def finalize(state: AgentState) -> AgentState:
    final_message = state["final_message"]
    if state["messages"] and isinstance(state["messages"][-1], AIMessage):
        content = state["messages"][-1].content
        if isinstance(content, str):
            final_message = content

    if not final_message:
        if state["iterations"] >= settings.agent_max_steps:
            final_message = "Agent stopped after reaching the maximum tool iterations."
            status = "max_iterations_reached"
        elif not state["provider_configured"]:
            final_message = "Agent tools are ready, but no provider is configured."
            status = "awaiting_provider"
        else:
            final_message = "Agent run completed."
            status = "completed"
    else:
        status = state["status"] if state["status"] != "running" else "completed"

    return {
        **state,
        "status": status,
        "final_message": final_message,
    }


def build_agent_graph():
    graph = StateGraph(AgentState)
    graph.add_node("inspect_workspace", inspect_workspace)
    graph.add_node("call_model", call_model)
    graph.add_node("execute_tools", execute_tools)
    graph.add_node("finalize", finalize)
    graph.add_edge(START, "inspect_workspace")
    graph.add_conditional_edges(
        "inspect_workspace",
        lambda state: "call_model" if state["provider_configured"] else "finalize",
        {
            "call_model": "call_model",
            "finalize": "finalize",
        },
    )
    graph.add_conditional_edges(
        "call_model",
        should_continue,
        {
            "execute_tools": "execute_tools",
            "finalize": "finalize",
        },
    )
    graph.add_edge("execute_tools", "call_model")
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
            final_message=final_state["final_message"],
            iterations=final_state["iterations"],
        )
