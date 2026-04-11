# Project Memory

This document is a compact memory dump of the current Knight codebase, its architecture, the decisions made so far, and the known boundaries of the current implementation.

## Purpose

Knight is being built as an open source, self-hostable automation system that:

- receives external events, initially via webhooks
- runs background jobs through Celery
- prepares deterministic repo sandboxes and issue-specific worktrees
- lets an agent work only inside those prepared workspaces
- commits and pushes changes after the agent finishes
- will later create and update PRs automatically

The long-term goal is to let others host Knight in Docker with their own model providers and credentials.

## Package Structure

The repo uses a root package layout, not a `src/` layout.

```text
knight/
  agents/
  api/
  models/
  runtime/
  utils/
    db/
  worker/
docs/
scripts/
```

Important conventions:

- keep the `knight` namespace
- use absolute imports starting with `knight.`
- do not use relative imports
- do not use bare top-level imports like `from api...`

## High-Level Flow

Current intended flow:

1. external system sends a webhook
2. API receives and validates it
3. API enqueues a Celery task into Redis
4. worker prepares sandbox repo and worktree deterministically
5. agent runs only inside the prepared worktree
6. worker runs post-agent git operations
7. worktree is removed
8. branch remains reusable for later follow-up work

Current direction:

- branches are reusable
- worktrees are disposable
- worker owns repo/worktree lifecycle
- agent does not manage clone/worktree/branch creation

## API

The API app lives under `knight/api/app.py`.

The design is webhook-first. A generic `/api/tasks` route was replaced with `/api/webhooks`.

The API should remain thin:

- receive webhook payloads
- validate payloads
- enqueue worker tasks

It is not intended to grow into a large general-purpose API before the webhook-first flow is solid.

## Celery and Worker

Celery is set up as the background execution layer with Redis as broker/backend.

Worker-side logic lives under `knight/worker/`.

Key worker responsibilities:

- receive queued jobs
- prepare task runtime state
- resolve repo identity
- provision sandbox and worktree
- call the agent service with a prepared workspace
- run post-agent git operations
- update branch state persistence

## Agent

The agent lives under `knight/agents/` and is currently a LangGraph-based coding-agent scaffold.

It has:

- a graph loop
- tool exposure for file operations and shell commands
- runtime-configurable provider/model settings
- command and file-write policy gates
- logging and execution tracing hooks

It does not yet represent a fully mature coding agent equivalent to Cursor/Codex/Claude Code. It is an expanding scaffold with the right execution boundaries.

Current important rule:

- the agent receives a prepared workspace path
- the agent should only operate inside that workspace
- sandbox/worktree setup is deterministic worker logic, not agent logic

## Sandbox and Worktree Model

The current repo execution model is based on one sandbox repo per repository and disposable worktrees per task/issue/branch.

Rules that have been agreed on:

- one sandbox repo per target repository
- create a worktree for the target branch
- let the agent work in that worktree
- commit and push after the agent finishes
- remove the worktree after post-run completion
- keep the branch
- if more changes are requested later, create a fresh worktree for the same branch and continue

Important distinction:

- a branch is a line of history
- a worktree is a checked-out filesystem view of a branch/commit

The system must not keep worktrees around indefinitely. It should recreate them as needed.

## Branch Source of Truth

The agreed branch semantics are:

- if `origin/<target-branch>` exists, that remote branch is the source of truth
- if the target branch does not exist remotely, create a new branch from the chosen base branch
- local-only feature branches must not be treated as durable resumable state

Reason:

- remote branch state is the only reliable resumable state once worktrees are disposable
- local-only branches are not sufficient as a durable workflow primitive
- follow-up work should continue from the pushed branch, not from stale local state

The worker should fetch remote refs and materialize worktrees from the relevant source ref rather than relying on mutable local branch state as authority.

## Repository Locking

Repository-level locking exists to protect shared sandbox repo operations while still allowing concurrent work on the same repository.

The intended concurrency model is:

- multiple workers may work on the same repository
- shared sandbox repo metadata operations must be serialized
- actual agent work inside separate worktrees may run concurrently

The lock is used around operations like:

- sandbox repo refresh
- branch ref synchronization
- worktree create
- worktree remove

The lock must not be held for the full duration of agent execution.

## Repository Identity

Repository identity has been normalized to `owner/repo`.

Examples:

- `https://github.com/openai/codex.git` -> `openai/codex`
- `git@github.com:openai/codex.git` -> `openai/codex`

For local repos:

- if `origin` is parseable, use its normalized `owner/repo`
- otherwise fall back to `local/<dirname>`

This normalized identity is used for:

- branch state storage
- repository-scoped config lookup
- sandbox keying

## Branch State Persistence

Knight needs persistent knowledge of branches it has created so it can distinguish between:

- a new branch/PR workflow
- follow-up work on an existing agent-created branch/PR

That persistence started as a JSON-backed store and was later moved to the database layer.

Current persisted branch-state concepts include:

- repository
- issue id
- base branch
- agent branch
- optional PR number
- provider
- status
- timestamps

The point of this state is to let the worker decide whether it should:

- create a fresh branch
- or continue working on an existing branch it already owns

## Database Layer

All database code has been moved under `knight/utils/db/`.

Current files:

- `knight/utils/db/engine.py`
- `knight/utils/db/schema.py`
- `knight/utils/db/backend.py`
- `knight/utils/db/config_store.py`
- `knight/utils/db/state_store.py`
- `knight/utils/db/bootstrap.py`

Worker-local compatibility shims were removed. Active code should use the shared DB package directly.

## Supported Database Direction

The DB layer is structured to support:

- Postgres
- MySQL
- SQL Server

Backend type is inferred from `DATABASE_URL`.

Current URL normalization:

- `postgres://...` or `postgresql://...` -> `postgresql+psycopg`
- `mysql://...` -> `mysql+pymysql`
- `sqlserver://...` -> `mssql+pytds`

Important honesty boundary:

- Postgres has been live-verified
- MySQL and SQL Server are structurally supported in the shared DB layer and DDL-compilation was checked
- MySQL and SQL Server have not yet been verified against live instances

## Database Cross-Dialect Decisions

The main cross-database concerns so far have been:

- explicit string lengths for MySQL compatibility
- portable uniqueness behavior
- JSON storage
- enum handling
- nullable repository scoping

Important resolved decision:

- `app_config.repository` supports `NULL`
- global config rows use `repository = NULL`
- repository-specific rows use a real repository identifier
- code must use null-safe comparators for repository-scoped config operations

The user explicitly rejected using `''` as a sentinel in place of `NULL`, so the current design uses real `NULL` values and null-safe comparison semantics.

## Null-Safe Repository Handling

Global app config rows use:

- `scope = 'global'`
- `repository = NULL`

Repository-specific rows use:

- `scope = 'repository'`
- `repository = 'owner/repo'`

The DB layer uses null-safe comparison for config read/write paths so `NULL` is handled deliberately rather than being replaced with an empty-string sentinel.

This was an explicit design correction after earlier experimentation with `repository = ''`.

## Schema Summary

### `agent_branches`

Purpose:

- persist branch ownership and branch workflow state

Important fields:

- `repository`
- `issue_id`
- `base_branch`
- `agent_branch`
- `provider`
- `status`
- timestamps

Important constraints:

- unique branch record identity
- status check constraint
- supporting indexes for repo/issue/status and branch lookups

### `app_config`

Purpose:

- runtime-tunable configuration stored in DB

Current scope values:

- `global`
- `repository`

Important fields:

- `scope`
- `repository`
- `key`
- `value` as JSON
- `description`
- timestamps

Important design intent:

- runtime config belongs here
- secrets and infrastructure details stay in `.env`

## Configuration Strategy

The DB config table should be used for runtime-tunable behavior, not infrastructure or secret storage.

Examples of good DB-stored config:

- agent provider
- agent model
- temperature
- max steps
- command timeout
- command output limits
- blocked command prefixes
- tool enable/disable flags
- logging behavior
- system prompt

Examples of things that should stay in `.env`:

- `DATABASE_URL`
- Redis/Celery connection details
- provider API keys

## Config Resolution Order

Current intended config resolution order:

1. repository-scoped DB config
2. global DB config
3. env/code defaults

Repository identity for scoped lookup uses the normalized `owner/repo` format.

## Seeded Runtime Config

The DB bootstrap currently seeds defaults for:

- `logging_level`
- `logging_format`
- `logging_include_timestamp`
- `logging_include_logger_name`
- `logging_include_process`
- `logging_log_tool_results`
- `logging_log_command_output`
- `agent_provider`
- `agent_model`
- `agent_temperature`
- `agent_max_steps`
- `agent_command_timeout_seconds`
- `agent_max_command_output_chars`
- `agent_blocked_command_prefixes`
- `agent_allow_run_command`
- `agent_allow_write_files`
- `agent_system_prompt`

Current live config note:

- `logging_format` has been updated to `"json"`

## Logging

Detailed logging has been implemented with DB-backed configuration.

Core file:

- `knight/runtime/logging_config.py`

Important characteristics:

- logging config is read from DB at startup
- if DB config lookup fails, logging falls back to sane defaults
- API and worker both initialize logging
- logs include contextual fields for task and worker activity
- command output logging is gated by configuration

Current format support:

- text
- json

Current live DB configuration:

- JSON logging is enabled

## Git Operations

Post-run git orchestration exists and is worker-owned.

The intended post-run sequence is:

1. inspect worktree changes
2. generate commit message
3. commit changes if present
4. push if enabled
5. remove worktree if cleanup is enabled

PR creation is intentionally deferred for now.

Important current direction:

- commit/push remains deterministic worker behavior
- commit message generation can use a dedicated commit-message path
- PR creation can be added later on top of the persisted branch-state model

## Commit Message Path

A separate commit-message generation path has already been introduced conceptually.

The idea is:

- the main coding agent edits code
- a specialized commit-message generator or smaller commit agent produces commit messages from diffs

This keeps commit-message generation separate from code-edit execution.

## Default Branch Handling

The project deliberately moved away from storing branch defaults in the DB config layer.

Important current understanding:

- for fresh clones, Git already lands on the remote default branch
- for explicit remote default-branch discovery, Git can be queried directly if needed
- branch defaults do not belong in the DB runtime config table

The DB config table should focus on agent/runtime behavior instead.

## Scripts

Current DB bootstrap scripts are Python scripts:

- `scripts/init_db.py`
- `scripts/drop_db.py`

They use the shared DB bootstrap package rather than raw database-specific SQL scripts.

Earlier SQL bootstrap scripts were removed in favor of code-driven bootstrap logic.

## Dependency and Tooling Notes

Dependencies were added with `uv`.

Notable additions:

- `sqlalchemy`
- `pymysql`
- `python-tds`

`pyproject.toml` and `uv.lock` were updated accordingly.

## What Has Been Verified

Verified live:

- Postgres connectivity and shared DB package read/write path
- config store read
- branch state upsert/read/close cycle
- DB reset and re-init through Python bootstrap
- global app config rows stored with `repository = NULL`
- JSON logging config stored in DB

Verified locally:

- schema DDL compiles for Postgres
- schema DDL compiles for MySQL
- schema DDL compiles for SQL Server
- code compiles with `python -m compileall`

Not yet verified live:

- MySQL runtime behavior
- SQL Server runtime behavior
- full end-to-end worker flow against non-Postgres DBs

## Current Limitations

These are still true:

- only Postgres has been exercised against a real live database instance
- MySQL and SQL Server support is implemented structurally but not live-tested
- the coding agent is still a scaffold, not yet a production-grade autonomous coding system
- PR creation is still deferred
- failure-state modeling around commit/push/cleanup still needs hardening
- webhook/event semantics still need clearer modeling for issue creation vs PR review follow-ups

## Design Principles Established So Far

- worker owns deterministic infra setup
- agent owns code inspection/editing within a prepared workspace
- branches are reusable
- worktrees are disposable
- remote branch state is authoritative
- repository identity should be normalized to `owner/repo`
- runtime-tunable settings belong in the DB
- secrets and infra endpoints belong in `.env`
- use null-safe DB semantics for nullable repository-scoped config
- keep imports absolute under the `knight` namespace

## Near-Term Next Steps

Reasonable next steps from the current state:

- verify the shared DB layer against a real MySQL instance
- verify the shared DB layer against a real SQL Server instance
- harden post-run git outcome handling into structured statuses
- add PR creation and store PR numbers in branch state
- improve webhook event modeling for follow-up review cycles
- continue maturing the agent loop, edit strategy, and policy model

## File and Module Landmarks

Key areas to inspect first when re-entering the project:

- `knight/api/app.py`
- `knight/agents/`
- `knight/runtime/logging_config.py`
- `knight/runtime/locking.py`
- `knight/runtime/repository_identity.py`
- `knight/runtime/worktree.py`
- `knight/worker/runtime.py`
- `knight/worker/git_ops.py`
- `knight/worker/tasks/run_agent_task.py`
- `knight/utils/db/`
- `docs/progress.md`
- `docs/pending.md`
- `docs/agents/context.md`

## Final Notes

The project has moved from rough scaffolding into a clearer architecture:

- webhook ingestion
- queued worker execution
- deterministic repo/worktree prep
- constrained agent execution
- DB-backed runtime configuration
- DB-backed branch workflow state
- structured path toward PR-aware iteration

The main unresolved work is no longer basic scaffolding. It is correctness hardening, live multi-database validation, and turning the agent scaffold into a stronger production execution system.
