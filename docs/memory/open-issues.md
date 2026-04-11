# Open Issues

This file captures the major known gaps and pending technical work.

## Database Verification

- MySQL support is implemented structurally but not live-tested
- SQL Server support is implemented structurally but not live-tested
- cross-database runtime behavior still needs verification beyond DDL compilation

## Worker Correctness

- post-run git outcomes should be modeled with clearer structured states
- push failure and cleanup failure behavior still need stronger operational semantics
- branch lifecycle should later include PR linkage and state transitions

## PR Workflow

- PR creation is still deferred
- branch state persistence is ready to support PR linkage, but PR numbers and PR-state-aware logic still need implementation
- follow-up review/comment events need more explicit workflow handling

## Agent Maturity

- the current agent is still a scaffold
- autonomous code-edit quality is not yet at Cursor/Codex/Claude Code level
- edit strategy still needs to improve
- verification loops and stronger task planning still need work

## Event Modeling

- webhook payloads still need stronger event typing
- the worker should eventually distinguish clearly between:
  - new issue/task
  - follow-up PR comment
  - changes-requested review
  - comment on an existing agent-created PR

## Multi-Database Operations

- backend inference from `DATABASE_URL` is in place
- actual live end-to-end runs need to be tested on each supported database
- migration strategy is still primitive because bootstrap currently assumes reset/init scripts

## Operational Tooling

- database health-check tooling would help operational clarity
- admin/update tooling for `app_config` would be useful so config changes do not require manual DB editing
- more explicit worker startup validation would help fail fast on misconfiguration
