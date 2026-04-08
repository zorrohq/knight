# Knight Pending Work

## Major Pending Areas

## 1. Branch Source-Of-Truth Rules

The branch lifecycle is not fully finalized yet.

Desired behavior:

- if `origin/<target-branch>` exists, that remote branch should be the source of truth
- if the target branch does not exist, create a new branch from `origin/<base-branch>` or local `<base-branch>`
- local-only feature branches should not be treated as durable resumable state

Current shortcoming:

- branch selection and syncing logic is close, but still needs one more hardening pass around remote-authoritative behavior and parallel worker safety

## 2. Concurrency And Locking

There is no explicit repository-level locking yet.

Why this matters:

- multiple workers may fetch/update the same sandbox repo at the same time
- worktree creation and branch manipulation can race
- shared sandbox state can become inconsistent without coordination

Pending solution:

- add per-repository locking around fetch/sync/worktree creation and cleanup

## 3. Post-Run Error Handling

The post-run hook exists, but failure handling is still rough.

Current shortcomings:

- commit failures raise raw runtime errors
- push failures raise raw runtime errors
- there is no structured outcome model for partial success cases

Examples that need defined behavior:

- agent made changes but commit failed
- commit succeeded but push failed
- push succeeded but cleanup failed

## 4. PR Creation And PR State

PR orchestration is intentionally deferred.

Missing pieces:

- create PR after first successful push
- persist PR number in branch state
- detect follow-up comments or review requests for an existing PR
- route follow-up events back to the same agent branch

## 5. Persistent State Backing Store

The current branch state utility is backed by a JSON file.

Shortcomings:

- not safe for multiple workers without extra coordination
- not durable enough for production-scale execution
- awkward for querying, filtering, and concurrent updates

Expected next step:

- replace JSON-backed state storage with a real database while preserving the current interface shape

## 6. Webhook Modeling

Webhook ingestion is still too generic.

Current payload limitations:

- no event-type differentiation
- no explicit support for issue events vs PR review/comment events
- no delivery id or provider metadata
- no signature verification support

Needed improvements:

- stronger provider-specific webhook models
- clearer routing logic for new-task vs follow-up-on-existing-PR events

## 7. Agent Capability Depth

The agent scaffold exists, but it is still not at the level of a production coding agent.

Current shortcomings:

- no provider has been exercised end-to-end for real autonomous edits
- edit primitives are still basic
- no patch-native or diff-native editing strategy
- no dedicated verification loop after edits
- no human-input or approval step integration

## 8. Security And Isolation

Current isolation is not a true hardened sandbox.

Current state:

- workspace-rooted file access
- in-process command filtering
- per-repo sandbox repo and per-issue worktree separation

What is missing:

- per-run container isolation
- network restrictions
- user separation
- resource limits
- hardened OS-level sandboxing

## 9. Git Operations Scope

The worker currently handles commit and push, but more git lifecycle work remains.

Pending items:

- smarter remote detection and push behavior
- support for non-`origin` workflows in a cleaner way
- branch status transitions after push
- handling merged/closed branches in persistent state
- robust retry semantics

## 10. Observability

There is no real run-trace persistence yet.

Missing pieces:

- structured worker logs
- persisted task execution history
- agent message and tool trace storage
- sandbox/worktree lifecycle events
- easier debugging surfaces for failed runs

## Current Implementation Shortcomings

## JSON Store Is Temporary

The JSON-backed branch store is useful as a local stub, but it should not be considered production-ready.

## Commit Agent Is Minimal

The commit-message generator is implemented as a service, but it is not yet a fully separated commit-agent workflow with its own configuration and failure semantics.

## Remote-First Follow-Up Flow Is Incomplete

The intended lifecycle is:

1. create branch
2. push branch
3. create PR
4. future comments/reviews reuse that same branch

The current codebase has only part of this:

- branch reuse support
- push support
- JSON-backed branch tracking

It does not yet have:

- PR creation
- PR linkage
- event-to-existing-PR resolution

## Testing Coverage Is Missing

There are no automated tests yet for:

- worktree provisioning
- branch reuse logic
- JSON state store behavior
- commit/push hook behavior
- webhook-to-worker flow

## Recommended Next Steps

Recommended order:

1. finalize remote-authoritative branch selection semantics
2. add repository-level locking for runtime operations
3. make post-run commit/push return structured outcomes
4. add PR creation and persist PR linkage in the state store
5. replace JSON persistence with a real database
6. add tests around worktree lifecycle and branch reuse
