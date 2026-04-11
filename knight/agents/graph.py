from __future__ import annotations

import json
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from knight.agents.llm import create_agent_model
from knight.agents.models import AgentRunResult, AgentTaskRequest, ToolResult
from knight.agents.prompt import build_system_prompt
from knight.agents.runtime_config import AgentConfigResolver, ResolvedAgentSettings
from knight.agents.state import AgentState
from knight.agents.tools import AgentToolset
from knight.runtime.command_runner import LocalCommandRunner
from knight.runtime.filesystem import LocalWorkspace
from knight.runtime.logging_config import (
    ResolvedLoggingSettings as RuntimeLogSettings,
    get_logger,
    setup_logging,
)
from knight.runtime.repository_identity import normalize_repository_identity
from knight.runtime.sandbox import SandboxPolicy

logger = get_logger(__name__)

_AGENTS_MD_FILENAME = "AGENTS.md"


def _read_agents_md(workspace_path: str) -> str:
    """Read AGENTS.md from the workspace root, returning content or empty string."""
    try:
        path = Path(workspace_path) / _AGENTS_MD_FILENAME
        if path.is_file():
            content = path.read_text(encoding="utf-8").strip()
            logger.info("AGENTS.md loaded from workspace", extra={"workspace": workspace_path})
            return content
    except OSError:
        logger.warning("could not read AGENTS.md", extra={"workspace": workspace_path})
    return ""


def build_initial_state(
    task: AgentTaskRequest,
    sandbox: dict[str, object] | None = None,
    log_config: RuntimeLogSettings | None = None,
) -> AgentState:
    repository_identity = normalize_repository_identity(
        repository_url=task.repository_url,
        repository_local_path=task.repository_local_path,
    ) or None
    runtime_config = AgentConfigResolver().resolve(repository=repository_identity)
    provider_configured = bool(runtime_config.provider and runtime_config.model)
    return {
        "task": task,
        "sandbox": dict(sandbox or {}),
        "runtime_config": {
            "provider": runtime_config.provider,
            "model": runtime_config.model,
            "temperature": runtime_config.temperature,
            "max_steps": runtime_config.max_steps,
            "command_timeout_seconds": runtime_config.command_timeout_seconds,
            "max_command_output_chars": runtime_config.max_command_output_chars,
            "blocked_command_prefixes": list(runtime_config.blocked_command_prefixes),
            "allow_run_command": runtime_config.allow_run_command,
            "allow_write_files": runtime_config.allow_write_files,
            "allow_commit_and_push": runtime_config.allow_commit_and_push,
            "system_prompt": runtime_config.system_prompt,
        },
        "provider_configured": provider_configured,
        "available_tools": [],
        "workspace_summary": {},
        "steps": [],
        "messages": [HumanMessage(content=task.instructions)],
        "status": "pending",
        "iterations": 0,
        "final_message": "",
        "termination_warned": False,
        "pr_url": "",
    }


def build_system_message(state: AgentState) -> SystemMessage:
    task = state["task"]
    summary = state["workspace_summary"]
    runtime_config = ResolvedAgentSettings(**state["runtime_config"])
    repository = normalize_repository_identity(
        repository_url=task.repository_url,
        repository_local_path=task.repository_local_path,
    )

    content = build_system_prompt(
        workspace_root=summary.get("root", task.workspace_path),
        branch_name=state["sandbox"].get("branch_name", "unknown"),
        base_branch=task.base_branch or "main",
        repository=repository,
        max_steps=runtime_config.max_steps,
        command_timeout_seconds=runtime_config.command_timeout_seconds,
        blocked_prefixes=runtime_config.blocked_command_prefixes,
        agents_md_content=summary.get("agents_md", ""),
    )
    return SystemMessage(content=content)


def get_toolset(state: AgentState) -> AgentToolset:
    workspace_path = state["task"].workspace_path or "."
    runtime_config = ResolvedAgentSettings(**state["runtime_config"])
    return AgentToolset(
        workspace=LocalWorkspace(workspace_path),
        command_runner=LocalCommandRunner(
            policy=SandboxPolicy(
                blocked_command_prefixes=runtime_config.blocked_command_prefixes,
            ),
            max_output_chars=runtime_config.max_command_output_chars,
        ),
        runtime_config=runtime_config,
        task=state["task"],
        sandbox=state["sandbox"],
    )


def inspect_workspace(state: AgentState) -> AgentState:
    toolset = get_toolset(state)
    tools = toolset.build_tools()
    top_level_files = toolset.list_files(path=".", recursive=False)

    workspace_root = str(toolset.workspace.root)
    agents_md = _read_agents_md(workspace_root)

    step = ToolResult(
        tool="list_files",
        success=True,
        output=top_level_files,
    )

    status = "ready" if state["provider_configured"] else "awaiting_provider"
    logger.info(
        "agent workspace inspected",
        extra={
            "repository": normalize_repository_identity(
                repository_url=state["task"].repository_url,
                repository_local_path=state["task"].repository_local_path,
            ),
            "issue_id": state["task"].issue_id,
            "branch_name": state["sandbox"].get("branch_name"),
            "provider_configured": state["provider_configured"],
            "agents_md_present": bool(agents_md),
            "available_tools": [tool.name for tool in tools],
        },
    )

    return {
        **state,
        "available_tools": [tool.name for tool in tools],
        "workspace_summary": {
            "root": workspace_root,
            "top_level_files": top_level_files["files"],
            "agents_md": agents_md,
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
    runtime_config = ResolvedAgentSettings(**state["runtime_config"])
    model = create_agent_model(runtime_config)
    if model is None:
        return {
            **state,
            "status": "awaiting_provider",
        }

    toolset = get_toolset(state)
    bound_model = model.bind_tools(toolset.build_tools())
    response = bound_model.invoke([build_system_message(state), *state["messages"]])
    logger.info(
        "agent model invoked",
        extra={
            "repository": normalize_repository_identity(
                repository_url=state["task"].repository_url,
                repository_local_path=state["task"].repository_local_path,
            ),
            "issue_id": state["task"].issue_id,
            "branch_name": state["sandbox"].get("branch_name"),
            "iteration": state["iterations"] + 1,
            "tool_call_count": len(response.tool_calls),
        },
    )

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
    log_config = setup_logging()

    tool_messages: list[ToolMessage] = []
    step_results = list(state["steps"])
    pr_url = state.get("pr_url", "")

    for tool_call in last_message.tool_calls:
        tool_name = tool_call["name"]
        tool = tool_map.get(tool_name)
        if tool is None:
            step_result = ToolResult(
                tool=tool_name,
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
            if tool_name == "run_command":
                success = bool(output.get("exit_code", 0) == 0)
            elif tool_name == "commit_and_open_pr":
                success = bool(output.get("success"))
                if success and output.get("pr_url"):
                    pr_url = output["pr_url"]
            else:
                success = True
            step_result = ToolResult(
                tool=tool_name,
                success=success,
                output=output,
                error=None if success else output.get("error") or "command failed",
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
                tool=tool_name,
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
        if log_config.log_tool_results:
            extra = {
                "repository": normalize_repository_identity(
                    repository_url=state["task"].repository_url,
                    repository_local_path=state["task"].repository_local_path,
                ),
                "issue_id": state["task"].issue_id,
                "branch_name": state["sandbox"].get("branch_name"),
                "tool": tool_name,
                "success": step_result.success,
            }
            if tool_name == "run_command":
                extra["exit_code"] = step_result.output.get("exit_code")
                if log_config.log_command_output:
                    extra["stdout"] = step_result.output.get("stdout", "")
                    extra["stderr"] = step_result.output.get("stderr", "")
            elif tool_name == "commit_and_open_pr":
                extra["pr_url"] = step_result.output.get("pr_url")
                extra["pr_existing"] = step_result.output.get("pr_existing")
            logger.info("agent tool executed", extra=extra)

    return {
        **state,
        "messages": tool_messages,
        "steps": step_results,
        "status": "running",
        "pr_url": pr_url,
    }


def _agent_called_commit(state: AgentState) -> bool:
    """Return True if the agent successfully called commit_and_open_pr this run."""
    return bool(state.get("pr_url"))


def should_continue(state: AgentState) -> str:
    runtime_config = ResolvedAgentSettings(**state["runtime_config"])

    if not state["provider_configured"]:
        return "finalize"

    if state["iterations"] >= runtime_config.max_steps:
        return "finalize"

    last_message = state["messages"][-1]
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "execute_tools"

    # Premature-termination guard.
    # If the agent wants to stop without having committed, and it hasn't been
    # warned yet, inject a reminder and loop back once.
    if (
        isinstance(last_message, AIMessage)
        and not last_message.tool_calls
        and not _agent_called_commit(state)
        and not state.get("termination_warned")
        and runtime_config.allow_commit_and_push
    ):
        return "warn_incomplete"

    return "finalize"


def warn_incomplete(state: AgentState) -> AgentState:
    """Inject a warning when the agent stops without committing its work."""
    from uuid import uuid4

    tc_id = str(uuid4())
    warning = ToolMessage(
        content=(
            "You stopped without calling `commit_and_open_pr`. "
            "If your implementation is complete, you MUST call `commit_and_open_pr` to push "
            "your changes and open a PR. If there is nothing to commit, explain why and "
            "call `commit_and_open_pr` to confirm the state of the repository."
        ),
        tool_call_id=tc_id,
        name="system_warning",
    )
    logger.info(
        "premature termination guard triggered",
        extra={
            "issue_id": state["task"].issue_id,
            "iterations": state["iterations"],
        },
    )
    return {
        **state,
        "messages": [warning],
        "termination_warned": True,
        "status": "running",
    }


def finalize(state: AgentState) -> AgentState:
    runtime_config = ResolvedAgentSettings(**state["runtime_config"])
    final_message = state["final_message"]
    if state["messages"] and isinstance(state["messages"][-1], AIMessage):
        content = state["messages"][-1].content
        if isinstance(content, str):
            final_message = content

    if not final_message:
        if state["iterations"] >= runtime_config.max_steps:
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


def build_agent_graph() -> CompiledStateGraph:
    graph = StateGraph(AgentState)
    graph.add_node("inspect_workspace", inspect_workspace)
    graph.add_node("call_model", call_model)
    graph.add_node("execute_tools", execute_tools)
    graph.add_node("warn_incomplete", warn_incomplete)
    graph.add_node("finalize", finalize)

    graph.add_edge(START, "inspect_workspace")
    graph.add_conditional_edges(
        "inspect_workspace",
        lambda state: "call_model" if state["provider_configured"] else "finalize",
        {"call_model": "call_model", "finalize": "finalize"},
    )
    graph.add_conditional_edges(
        "call_model",
        should_continue,
        {
            "execute_tools": "execute_tools",
            "warn_incomplete": "warn_incomplete",
            "finalize": "finalize",
        },
    )
    graph.add_edge("execute_tools", "call_model")
    graph.add_edge("warn_incomplete", "call_model")
    graph.add_edge("finalize", END)
    return graph.compile()


class AgentGraphRunner:
    def __init__(self) -> None:
        self.graph = build_agent_graph()

    def run(
        self,
        task: AgentTaskRequest,
        sandbox: dict[str, object] | None = None,
        log_config: RuntimeLogSettings | None = None,
    ) -> AgentRunResult:
        final_state = self.graph.invoke(
            build_initial_state(task, sandbox=sandbox, log_config=log_config)
        )
        logger.info(
            "agent run completed",
            extra={
                "repository": normalize_repository_identity(
                    repository_url=task.repository_url,
                    repository_local_path=task.repository_local_path,
                ),
                "issue_id": task.issue_id,
                "branch_name": final_state["sandbox"].get("branch_name"),
                "status": final_state["status"],
                "iterations": final_state["iterations"],
                "pr_url": final_state.get("pr_url") or "",
            },
        )
        return AgentRunResult(
            status=final_state["status"],
            provider_configured=final_state["provider_configured"],
            task=final_state["task"],
            available_tools=final_state["available_tools"],
            sandbox=final_state["sandbox"],
            workspace_summary=final_state["workspace_summary"],
            steps=final_state["steps"],
            final_message=final_state["final_message"],
            iterations=final_state["iterations"],
            pr_url=final_state.get("pr_url") or "",
        )
