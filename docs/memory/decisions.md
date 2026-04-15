# Decisions

This file captures the main architectural and implementation decisions made so far.

## Package Layout

- Keep a root package layout: `knight/`
- Do not use a `src/` layout
- Keep the `knight` namespace
- Use absolute imports starting with `knight.`
- Do not use relative imports

Reason:

- cleaner Docker and runtime story
- explicit package ownership
- better fit for an open source self-hosted application

## Webhook-First Ingestion

- Use webhook ingestion first
- Keep the API thin
- Replace generic task routes with webhook-oriented routes

Reason:

- external systems need an HTTP entrypoint
- the worker system should be driven by events, not a broad app surface

## Worker Owns Infra Setup

- Sandbox preparation belongs to the worker
- Clone, fetch, branch sync, and worktree creation are deterministic worker responsibilities
- The agent must not manage git lifecycle or sandbox setup

Reason:

- better determinism
- easier testing
- cleaner separation between infra and agent reasoning

## Branch and Worktree Model

- Branches are reusable
- Worktrees are disposable
- Remove worktrees after the run
- Keep branches for follow-up edits and PR updates

Reason:

- avoids long-lived checked-out directories
- matches the intended PR review loop
- easier to recreate clean execution state

## Branch Source of Truth

- Existing remote branch state is authoritative
- Local-only feature branches are not durable resumable state
- New branches should be created from the base branch when no remote target branch exists

Reason:

- prevents stale local branch state from driving future work
- aligns with the expectation that agent-created branches are pushed

## Repository Locking

- Lock shared sandbox repo operations per repository
- Do not lock the full agent execution window
- Allow multiple workers to work on the same repository concurrently through separate worktrees

Reason:

- shared git metadata operations need serialization
- actual coding work should still parallelize

## Repository Identity

- Normalize repository identity to `owner/repo`
- Use parsed remote origin where available
- Fall back to `local/<dirname>` only for local-only cases

Reason:

- stable identifier for config and branch state lookup
- avoids raw URL mismatch issues

## Runtime Configuration

- Use DB-backed config for runtime-tunable behavior
- Keep secrets and infra endpoints in `.env`
- Config lookup order:
  1. repository-scoped DB config
  2. global DB config
  3. env/code defaults

Reason:

- operational flexibility without redeploys
- clear separation between config and secrets

## What Belongs in DB Config

- provider
- model
- temperature
- max steps
- command timeout
- command output limits
- blocked command prefixes
- feature flags
- logging behavior
- system prompts

## What Does Not Belong in DB Config

- `DATABASE_URL`
- Redis URLs
- provider API keys
- default git base branch

Reason:

- infra and secret data should stay outside the runtime-tunable config path

## Database Support Direction

- Keep one modular DB layer under `knight/utils/db/`
- Support Postgres, MySQL, and SQL Server
- Infer backend from `DATABASE_URL`

Reason:

- centralize persistence behavior
- make database support configurable rather than worker-local

## Nullable Repository Scope

- Support `NULL` for global config rows in `app_config.repository`
- Use null-safe comparators in the DB layer
- Do not use `''` sentinel values for repository identity

Reason:

- the data model should represent real absence, not a placeholder string
- mistakes should be handled intentionally

## Logging

- Logging configuration should come from DB-backed runtime config
- Support JSON logging
- Include contextual fields in worker and agent logs

Reason:

- operational visibility
- easier debugging in containerized/self-hosted setups

## Agent Scope

- The current agent is a scaffold, not yet a production-grade autonomous coder
- Focus first on execution boundaries and worker correctness
- Expand autonomous behavior after the worker backbone is reliable

Reason:

- infrastructure correctness is a prerequisite for safe agent execution

## Persistence for Agent-Created Branches

- Persist branch ownership and lifecycle state
- Use that state to decide whether to create a new branch or continue an existing one

Reason:

- follow-up PR changes must reuse the existing branch rather than creating nested agent branches
