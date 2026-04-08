# Knight Progress

## Overview

Knight currently has a working backend skeleton for:

- webhook ingestion through FastAPI
- asynchronous task dispatch through Celery
- worker-side runtime preparation for sandbox repos and worktrees
- a LangGraph-based coding agent scaffold
- worker-side post-run git hooks for commit and push orchestration

The codebase is currently centered around a root-level `knight/` package rather than a `src/` layout.

## Current Repository Structure

The active package layout is:

```text
knight/
  agents/
  api/
  models/
  runtime/
  worker/
docs/
Dockerfile
docker-compose.yml
pyproject.toml
README.md
```

Important modules:

- `knight/api/app.py`: FastAPI app setup
- `knight/api/routers/webhooks.py`: webhook ingestion route
- `knight/worker/celery_app.py`: Celery application setup
- `knight/worker/tasks/run_agent_task.py`: worker task entrypoint
- `knight/worker/runtime.py`: deterministic worker-side task preparation
- `knight/runtime/worktree.py`: sandbox repo and worktree management
- `knight/worker/git_ops.py`: post-run git hook logic
- `knight/worker/state_store.py`: JSON-backed branch state utility
- `knight/agents/graph.py`: LangGraph-based agent loop scaffold
- `knight/agents/tools.py`: file and command tools exposed to the agent

## API And Queue

The current ingestion flow is:

1. webhook request arrives at `POST /api/webhooks`
2. FastAPI validates the request payload
3. Celery task is enqueued
4. worker prepares runtime state
5. agent runs against a prepared workspace
6. post-run git hook executes

Implemented pieces:

- FastAPI app and settings
- webhook router
- request and response models
- Celery app configuration
- producer helper for enqueueing tasks
- worker task entrypoint that returns structured task results

## Agent Layer

The agent layer is scaffolded with LangGraph and LangChain.

Implemented pieces:

- provider-configured chat model initialization
- agent state and result models
- LangGraph control loop
- file tools:
  - `list_files`
  - `read_file`
  - `write_file`
  - `replace_in_file`
  - `search_files`
- git inspection tools:
  - `git_status`
  - `git_diff`
- shell command tool with policy enforcement

Current behavior:

- if no provider is configured, the agent returns `awaiting_provider`
- if a provider is configured, the graph can iterate through tool calls
- the agent only operates on a prepared workspace path

## Sandbox And Workspace Preparation

Sandbox and worktree preparation is now worker-owned, not agent-owned.

Implemented behavior:

- one persistent sandbox repo per repository under `.knight/sandboxes/<repo-key>/repo`
- one disposable worktree per issue/run under `.knight/sandboxes/<repo-key>/worktrees/<issue-key>`
- the worker prepares the worktree before invoking the agent
- the agent receives only the prepared workspace path

Current branch/worktree model:

- branches are reusable
- worktrees are disposable
- existing remote branch is the source of truth
- local-only agent branches are not treated as durable resumable state
- new branches are created from a selected base branch
- worktrees are removed after post-run cleanup if enabled

## Git Operations

Worker-side git logic exists outside the agent loop.

Implemented behavior:

- detect whether the worktree has changes
- generate a commit message through a dedicated commit-message service
- configure git user name and email
- stage and commit changes
- push the branch when enabled
- remove the worktree after finalization when enabled

Notes:

- commit message generation uses the configured model if available
- there is a deterministic fallback message when no model is configured
- PR creation is not implemented yet

## Branch State Tracking

A small persistence utility exists behind a database-like interface:

- `BranchStateStore.get_open_branch(...)`
- `BranchStateStore.upsert_branch(...)`
- `BranchStateStore.mark_branch_status(...)`

Current implementation:

- persistence is backed by a JSON file at `.knight/state/agent_branches.json`
- the worker runtime uses this store to remember reusable agent-created branches for a repository and issue

This is intended as a temporary implementation that can later be replaced with a real database.

## Runtime Safety

Current safety controls:

- workspace file access is rooted to the assigned worktree path
- shell commands are filtered through a sandbox policy
- blocked command prefixes are configurable
- agent-issued git commands are restricted to read-only inspection commands
- command output is truncated to a configured maximum size

## Docker And Local Runtime

Current containerization state:

- a shared app `Dockerfile` exists
- runtime commands live in `docker-compose.yml`
- Compose defines:
  - `redis`
  - `api`
  - `worker`

Current intent:

- API receives webhooks
- Redis acts as Celery broker/result backend
- worker consumes and executes tasks

## Current State Summary

The project is beyond boilerplate and now has a coherent worker-driven flow:

- webhook -> queue -> worker
- worker prepares sandbox repo and issue worktree
- agent runs inside the prepared workspace
- worker post-run hook commits and pushes changes

The remaining work is mostly around correctness, robustness, provider integration, PR handling, and persistent state.
