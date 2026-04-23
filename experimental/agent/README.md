# Experimental: LangGraph Agent

This directory contains the original Knight coding agent implementation, built on LangGraph + LangChain. It has been superseded by the pi-based agent (`knight/agents/service.py`) but is preserved here for reference.

## What it does

A LangGraph state machine with the following nodes:

- **inspect_workspace** — lists top-level files, reads `AGENTS.md`, initialises the toolset
- **call_model** — invokes the configured LLM (via LangChain `init_chat_model`) with tools bound
- **execute_tools** — runs all tool calls from the model response, records `ToolResult` steps
- **warn_incomplete** — guards against premature termination: if the agent stops without writing any files, injects a warning message and loops back (up to 3 attempts)
- **finalize** — captures final message and maps status

### Tools available to the agent

Always available: `list_files`, `read_file`, `search_files`, `git_status`, `git_diff`, `http_request`, `fetch_url`

Conditionally (config flags): `write_file`, `replace_in_file`, `run_command`

### Model tiers

Uses `model_high` for the agent loop. `model_low` is used by commit message and changelog services (unchanged, still active in the current stack).

## What was working

- Full end-to-end pipeline: webhook → Celery → workspace prep → agent → post-workflow
- Post-workflow (commit/push/PR/changelog/notify) was fully deterministic and decoupled from the agent
- Issue comment reactions (👀), PR notifications, changelog comments on existing PRs
- GitHub App + PAT auth
- Worktree provisioning with branch cleanup
- Premature-termination guard (warn_incomplete) catching agents that described instead of acted

## What was lacking

- **Model quality**: GPT-4o mini (the affordable option) frequently described changes instead of writing them, even after 3 warning injections. The warn_incomplete guard helped but wasn't reliable enough for autonomous use.
- **String-match file editing**: `replace_in_file` would silently fail or produce wrong results when the model reproduced whitespace or context incorrectly. No hash-anchor safety like pi's `edit` tool.
- **Tool proliferation**: 10 separate tools vs pi's 4. More surface area for the model to misuse.
- **LangGraph overhead**: the state machine added complexity without meaningful benefit once commit/push/PR was moved out of the agent's responsibility.

## Why pi replaced it

Pi's `edit` tool uses content-hash anchors (8-bit hash per line) to make surgical edits safe — if the file changed since the last read, the edit fails before mutating anything. This eliminated the class of "wrong string match" failures that plagued `replace_in_file`. Pi also ships with a `bash` tool that covers everything `run_command` did, plus git operations natively. The net result is a simpler, more reliable agent loop with better real-world task completion rates.

---

## Restoration checklist

Everything needed to bring this agent back as the active implementation.

### Files to move back into `knight/agents/`
- `experimental/agent/graph.py`
- `experimental/agent/tools.py`
- `experimental/agent/prompt.py`
- `experimental/agent/state.py`

### `knight/agents/service.py`
Replace the current `PiAgentRunner` with `AgentGraphRunner`:
```python
from knight.agents.graph import AgentGraphRunner

class CodingAgentService:
    def __init__(self) -> None:
        self.runner = AgentGraphRunner()

    def run(self, task, sandbox=None, log_config=None) -> AgentRunResult:
        return self.runner.run(task, sandbox=sandbox, log_config=log_config)
```

### `knight/agents/runtime_config.py`
Add back the four fields removed when pi was integrated, to both `ResolvedAgentSettings` (dataclass) and `AgentConfigResolver.resolve()`:

```python
# ResolvedAgentSettings dataclass
allow_run_command: bool
allow_write_files: bool
allow_commit_and_push: bool
system_prompt: str

# AgentConfigResolver.resolve()
allow_run_command=self.store.get_bool(key="agent_allow_run_command", repository=repository, default=True),
allow_write_files=self.store.get_bool(key="agent_allow_write_files", repository=repository, default=True),
allow_commit_and_push=self.store.get_bool(key="agent_allow_commit_and_push", repository=repository, default=True),
system_prompt=self.store.get_string(key="agent_system_prompt", repository=repository, default=settings.agent_system_prompt),
```

### `knight/agents/config.py`
Add back `agent_system_prompt` to `AgentSettings`:
```python
agent_system_prompt: str = (
    "You are Knight, an autonomous software engineering agent. ..."
)
```

### `knight/agents/models.py`
Add back the `ToolName` Literal (used by `tools.py`):
```python
from typing import Literal

ToolName = Literal[
    "list_files", "read_file", "write_file", "replace_in_file",
    "search_files", "git_status", "git_diff", "run_command",
    "http_request", "fetch_url",
]
```

### `pyproject.toml`
Add back `langgraph`:
```
"langgraph>=1.1.6",
```
Then regenerate `requirements.txt` via `uv pip compile` or equivalent.

### `Dockerfile`
Remove the Node.js + pi install steps (or keep them if running both agents in parallel):
```dockerfile
# Remove these blocks:
RUN apt-get update && apt-get install -y curl --no-install-recommends \
    && curl -fsSL https://deb.nodesource.com/setup_lts.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*
RUN npm install -g @mariozechner/pi-coding-agent
```

### `knight/utils/db/bootstrap.py`
Ensure these keys are present in `DEFAULT_APP_CONFIG` (they were removed during pi migration):
- `agent_allow_run_command` (bool, default `True`)
- `agent_allow_write_files` (bool, default `True`)
- `agent_system_prompt` (string)

Re-run `scripts/init_db.py` after updating the config list.

### `graph.py` — things that changed before the move
These changes were made to `graph.py` during the pi migration sprint and are reflected in the file in this directory:

- `termination_warned: bool` in state was renamed to `termination_warnings: int` (counter, not flag) — allows up to 3 warnings before finalizing
- `committed: bool` in state was renamed to `files_written: bool` — termination guard now checks whether any `write_file`/`replace_in_file` call succeeded, not whether `commit_and_open_pr` was called
- `commit_and_open_pr` was removed as an agent tool — post-workflow owns commit/push/PR entirely
- `warn_incomplete` messages updated to drop `commit_and_open_pr` references
- `should_continue` uses `allow_write_files` (not `allow_commit_and_push`) to gate the termination guard
