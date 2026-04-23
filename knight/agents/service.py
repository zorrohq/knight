"""Pi coding agent runner.

Invokes the pi coding agent (https://github.com/badlogic/pi-mono) as a
subprocess in RPC mode and maps its JSONL event stream to AgentRunResult.

Pi handles: LLM loop, tool execution (read/write/edit/bash), streaming.
Knight handles: workspace prep, post-workflow (commit/push/PR/notify).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any

from knight.agents.models import AgentRunResult, AgentTaskRequest, ToolResult
from knight.agents.runtime_config import AgentConfigResolver
from knight.runtime.logging_config import ResolvedLoggingSettings, get_logger
from knight.runtime.repository_identity import normalize_repository_identity
from knight.utils.db.session_store import AgentSessionStore

logger = get_logger(__name__)

_PI_BINARY = "pi"
_AGENTS_MD_FILENAME = "AGENTS.md"
_PI_PROVIDER_MAP: dict[str, str] = json.loads(
    (Path(__file__).parent.parent / "data" / "pi_provider_map.json").read_text()
)


def _read_agents_md(worktree_path: str) -> str:
    try:
        path = Path(worktree_path) / _AGENTS_MD_FILENAME
        if path.is_file():
            return path.read_text(encoding="utf-8").strip()
    except OSError:
        pass
    return ""


def _build_pi_prompt(
    *,
    task: AgentTaskRequest,
    sandbox: dict[str, Any],
    agents_md: str,
    repository: str,
    is_continuation: bool = False,
) -> str:
    worktree_path = sandbox.get("worktree_path") or task.workspace_path or "."
    branch_name = sandbox.get("branch_name") or task.branch_name or "unknown"
    base_branch = task.base_branch or "main"

    if agents_md:
        agents_md_section = f"## Repository Rules (AGENTS.md)\n\n{agents_md}"
    else:
        agents_md_section = "## Repository Rules\n\nNo AGENTS.md found. Apply general best practices."

    continuation_note = (
        "\n## Conversation Context\n\n"
        "This is a continuation of an ongoing issue. Your full conversation history, "
        "including previous changes and responses, is already in your session context. "
        "Use `git log` and `git show <SHA>` to inspect commits mentioned in previous "
        "responses before making further changes.\n"
        if is_continuation
        else ""
    )

    return f"""## Working Environment

You are operating in a git worktree at `{worktree_path}`.
The repository has been cloned and your working branch has been checked out.

- Branch: `{branch_name}`
- Base branch: `{base_branch}`
- Repository: `{repository or "unknown"}`

{agents_md_section}
{continuation_note}
## Task Execution

1. **Understand** — Read the task carefully. Explore relevant files before making any changes.
2. **Implement** — Make focused, minimal changes. Do not touch code outside the task scope.
3. **Verify** — Run linters and tests related to changed files only. Do NOT run the full test suite.
4. **Done** — Once your changes are written to disk, your job is complete. Committing, pushing, and opening the PR are handled automatically.

Do NOT describe what you plan to do and then stop. Write the actual code.

## Coding Standards

- Read files before modifying them. Never guess at existing content.
- Fix root causes, not symptoms.
- Maintain existing code style and conventions.
- Never create backup files — all changes are tracked by git.
- Never add copyright headers unless explicitly requested.
- Never add inline comments unless the logic is genuinely non-obvious.
- Only install trusted, well-maintained packages. Update dependency files accordingly.
- If a command fails and you make changes to fix it, re-run it to verify the fix.
- Ignore unrelated bugs or broken tests — stay scoped to the task.

## Task

{task.instructions}
"""


def _map_status(agent_end_event: dict[str, Any]) -> str:
    # returncode is always -9 (SIGKILL) since we kill after agent_end — ignore it
    reason = (agent_end_event.get("reason") or agent_end_event.get("status") or "").lower()
    if not agent_end_event:
        return "error"
    if "max" in reason:
        return "max_iterations_reached"
    if "error" in reason:
        return "error"
    return "completed"


class PiAgentRunner:
    def run(
        self,
        task: AgentTaskRequest,
        sandbox: dict[str, Any] | None = None,
        log_config: ResolvedLoggingSettings | None = None,
    ) -> AgentRunResult:
        sandbox = dict(sandbox or {})
        worktree_path = sandbox.get("worktree_path") or task.workspace_path or "."
        repository = normalize_repository_identity(
            repository_url=task.repository_url,
            repository_local_path=task.repository_local_path,
        )

        runtime_config = AgentConfigResolver().resolve(repository=repository or None)
        model = runtime_config.model_high or runtime_config.model_default
        pi_provider = _PI_PROVIDER_MAP.get(runtime_config.provider, runtime_config.provider) if runtime_config.provider else ""
        provider_configured = bool(pi_provider and model)

        if not provider_configured:
            return AgentRunResult(
                status="awaiting_provider",
                provider_configured=False,
                task=task,
                available_tools=[],
                sandbox=sandbox,
                workspace_summary={},
                final_message="No model configured for pi agent.",
                iterations=0,
                pr_url="",
            )

        pi_path = shutil.which(_PI_BINARY)
        if pi_path is None:
            logger.error("pi binary not found on PATH")
            return AgentRunResult(
                status="error",
                provider_configured=provider_configured,
                task=task,
                available_tools=[],
                sandbox=sandbox,
                workspace_summary={},
                final_message="pi binary not found. Ensure @mariozechner/pi-coding-agent is installed globally.",
                iterations=0,
                pr_url="",
            )

        agents_md = _read_agents_md(worktree_path)

        # Session restore
        session_store = AgentSessionStore()
        existing_session = session_store.load(task.issue_id) if task.issue_id else None
        is_continuation = existing_session is not None
        session_dir = Path(tempfile.mkdtemp(prefix="knight-session-"))
        if existing_session:
            session_file_name, session_data = existing_session
            (session_dir / session_file_name).write_text(session_data, encoding="utf-8")

        # Build prompt — full context on first run, just the new message on continuation
        if is_continuation:
            user_message = task.instructions
        elif task.issue_context:
            user_message = f"{task.issue_context}\n\n---\n\n{task.instructions}".strip()
        else:
            user_message = task.instructions

        prompt = _build_pi_prompt(
            task=task,
            sandbox=sandbox,
            agents_md=agents_md,
            repository=repository,
            is_continuation=is_continuation,
        )
        # Prepend the user message to the system-level prompt context
        full_prompt = f"{prompt}\n\n## User Message\n\n{user_message}"

        timeout_seconds = runtime_config.max_steps * runtime_config.command_timeout_seconds
        pi_model_id = f"{pi_provider}/{model}"
        cmd = [
            pi_path, "--mode", "rpc",
            "--session-dir", str(session_dir),
            "--provider", pi_provider,
            "--model", model,
        ]

        logger.info(
            "pi agent starting",
            extra={
                "repository": repository,
                "issue_id": task.issue_id,
                "branch_name": sandbox.get("branch_name"),
                "model": pi_model_id,
                "worktree_path": worktree_path,
                "timeout_seconds": timeout_seconds,
                "is_continuation": is_continuation,
            },
        )

        try:
            proc = subprocess.Popen(
                cmd,
                cwd=worktree_path,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except Exception as exc:
            logger.exception(
                "pi agent subprocess failed to start",
                extra={"repository": repository, "issue_id": task.issue_id},
            )
            return AgentRunResult(
                status="error",
                provider_configured=provider_configured,
                task=task,
                available_tools=[],
                sandbox=sandbox,
                workspace_summary={},
                final_message=f"pi subprocess error: {exc}",
                iterations=0,
                pr_url="",
            )

        # Configure session then send prompt
        # Keep stdin open — closing stdin causes pi to exit immediately
        proc.stdin.write(json.dumps({"type": "set_auto_compaction", "enabled": True}) + "\n")
        proc.stdin.write(json.dumps({"type": "set_thinking_level", "level": "medium"}) + "\n")
        proc.stdin.write(json.dumps({"type": "prompt", "message": full_prompt}) + "\n")
        proc.stdin.flush()

        # Read stdout line by line in a thread until agent_end or timeout
        stdout_lines: list[str] = []
        timed_out = False

        def _read_stdout() -> None:
            assert proc.stdout is not None
            for line in proc.stdout:
                stdout_lines.append(line)
                try:
                    if json.loads(line.strip()).get("type") == "agent_end":
                        break
                except json.JSONDecodeError:
                    pass

        reader = threading.Thread(target=_read_stdout, daemon=True)
        reader.start()
        reader.join(timeout=timeout_seconds)

        if reader.is_alive():
            timed_out = True

        proc.stdin.close()
        proc.kill()
        proc.wait()
        stderr_output = proc.stderr.read() if proc.stderr else ""

        # Save session to DB, then clean up temp dir
        try:
            session_files = sorted(
                session_dir.glob("*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True
            )
            if session_files and task.issue_id:
                sf = session_files[0]
                session_store.save(task.issue_id, sf.name, sf.read_text(encoding="utf-8"))
        except Exception:
            logger.warning(
                "pi session save failed",
                extra={"repository": repository, "issue_id": task.issue_id},
                exc_info=True,
            )
        finally:
            shutil.rmtree(session_dir, ignore_errors=True)

        if timed_out:
            shutil.rmtree(session_dir, ignore_errors=True)
            logger.warning(
                "pi agent timed out",
                extra={"repository": repository, "issue_id": task.issue_id},
            )
            return AgentRunResult(
                status="max_iterations_reached",
                provider_configured=provider_configured,
                task=task,
                available_tools=["read", "write", "edit", "bash"],
                sandbox=sandbox,
                workspace_summary={"root": worktree_path, "agents_md": agents_md},
                steps=[],
                final_message="Agent run timed out.",
                iterations=0,
                pr_url="",
            )

        if proc.returncode not in (0, -9) and stderr_output:
            logger.warning(
                "pi agent stderr",
                extra={
                    "repository": repository,
                    "issue_id": task.issue_id,
                    "stderr": stderr_output[:2000],
                },
            )

        # Parse JSONL event stream
        steps: list[ToolResult] = []
        final_message = ""
        agent_end_event: dict[str, Any] = {}
        pending_tool: dict[str, str] = {}  # call_id → tool_name
        iterations = 0

        for raw_line in stdout_lines:
            line = raw_line.strip()
            if not line:
                continue
            try:
                event: dict[str, Any] = json.loads(line)
            except json.JSONDecodeError:
                logger.debug("pi: unparseable stdout line: %s", line[:200], extra={"repository": repository})
                continue

            event_type = event.get("type", "")

            if event_type == "tool_execution_start":
                call_id = event.get("id") or event.get("call_id", "")
                tool_name = event.get("tool") or event.get("name", "unknown")
                if call_id:
                    pending_tool[call_id] = tool_name

            elif event_type == "tool_execution_end":
                iterations += 1
                call_id = event.get("id") or event.get("call_id", "")
                tool_name = pending_tool.pop(call_id, event.get("tool") or event.get("name", "unknown"))
                error = event.get("error") or None
                step = ToolResult(
                    tool=tool_name,
                    success=not bool(error),
                    output={"result": event.get("result") or event.get("output", "")},
                    error=error,
                )
                steps.append(step)
                logger.info(
                    "pi agent tool executed",
                    extra={
                        "repository": repository,
                        "issue_id": task.issue_id,
                        "tool": tool_name,
                        "success": step.success,
                        **({"error": step.error} if not step.success else {}),
                    },
                )

            elif event_type == "message_update":
                content = event.get("content") or event.get("text") or event.get("delta") or ""
                if content:
                    final_message = content

            elif event_type == "agent_end":
                agent_end_event = event
                final_message = (
                    event.get("message")
                    or event.get("final_message")
                    or final_message
                )

            else:
                logger.debug(
                    "pi: unhandled event type: %s",
                    event_type,
                    extra={"event": event},
                )

        status = _map_status(agent_end_event)

        logger.info(
            "pi agent completed",
            extra={
                "repository": repository,
                "issue_id": task.issue_id,
                "branch_name": sandbox.get("branch_name"),
                "status": status,
                "iterations": iterations,
                "returncode": proc.returncode,
            },
        )

        return AgentRunResult(
            status=status,
            provider_configured=provider_configured,
            task=task,
            available_tools=["read", "write", "edit", "bash"],
            sandbox=sandbox,
            workspace_summary={"root": worktree_path, "agents_md": agents_md},
            steps=steps,
            final_message=final_message or "Agent run completed.",
            iterations=iterations,
            pr_url="",
        )


class CodingAgentService:
    def __init__(self) -> None:
        self.runner = PiAgentRunner()

    def run(
        self,
        task: AgentTaskRequest,
        sandbox: dict[str, object] | None = None,
        log_config: ResolvedLoggingSettings | None = None,
    ) -> AgentRunResult:
        return self.runner.run(task, sandbox=sandbox, log_config=log_config)
