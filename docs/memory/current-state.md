# Current State

This file summarizes the repo as it exists now.

## Core Areas

- `knight/api/`
  Thin webhook-facing API layer
- `knight/agents/`
  LangGraph-based coding agent scaffold
- `knight/runtime/`
  Shared runtime concerns like worktrees, logging, locking, repository identity
- `knight/worker/`
  Celery worker orchestration and post-run git handling
- `knight/utils/db/`
  Shared database layer for config and branch state persistence

## Agent State

The agent currently has:

- a graph loop
- file and shell tool surfaces
- runtime-configurable provider/model settings
- command and file-write policy gating
- logging hooks

The agent currently does not have:

- proven production-grade autonomous editing behavior
- live-verified provider execution in this current pass
- mature diff/patch-native editing strategy
- PR-aware planning behavior

## Worker State

The worker currently handles:

- receiving queued tasks
- preparing sandbox repos
- creating disposable worktrees
- invoking the agent with a prepared workspace
- running post-agent git operations
- updating persistent branch state

## Sandbox Model

Current model:

- one sandbox repo per repository
- one disposable worktree per run
- worktree removed after the run
- branch retained for future work

Concurrency model:

- shared sandbox metadata operations are locked per repository
- actual agent work in separate worktrees can run concurrently

## Database State

The active shared DB package is:

- `knight/utils/db/engine.py`
- `knight/utils/db/schema.py`
- `knight/utils/db/backend.py`
- `knight/utils/db/config_store.py`
- `knight/utils/db/state_store.py`
- `knight/utils/db/bootstrap.py`

Current database direction:

- Postgres is live-verified
- MySQL and SQL Server are structurally supported in code
- MySQL and SQL Server are not yet live-verified

## Logging State

Logging is DB-configurable.

Current live behavior:

- `logging_format` is set to `json`

Startup behavior:

- API and worker initialize logging
- if DB config fails, logging falls back to sane defaults

## Configuration State

Runtime config is stored in `app_config`.

Current important keys include:

- logging controls
- provider/model controls
- command/tool policy flags
- prompt/system settings

Resolution order:

1. repository-scoped DB config
2. global DB config
3. env/code defaults

## Persistence State

Branch workflow state is stored in `agent_branches`.

This is used to remember:

- which agent branch exists for a repo/issue flow
- whether that branch should be reused
- future PR linkage once PR creation is added

## Scripts

Current DB bootstrap scripts:

- `scripts/init_db.py`
- `scripts/drop_db.py`

These are code-driven bootstrap scripts, not raw SQL files.

## What Is Working

- webhook-first architecture direction
- Celery/worker execution backbone
- deterministic sandbox/worktree preparation
- per-repo locking around shared git operations
- DB-backed runtime config
- DB-backed branch state
- JSON logging configuration
- Postgres read/write path through the shared DB package

## What Is Not Fully Proven Yet

- live MySQL support
- live SQL Server support
- end-to-end PR creation/update flow
- production-grade autonomous coding behavior
