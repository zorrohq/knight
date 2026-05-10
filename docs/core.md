# Knight — Core Reference

Everything needed to understand, continue, and extend this project from scratch.

---

## What Is Knight

Knight is an **autonomous background coding agent** triggered by GitHub events. A user comments `@knight <task>` on a GitHub issue or PR review comment, Knight picks it up, runs a coding agent (pi) in an isolated git worktree, commits the result, pushes a branch, opens a PR, and notifies the original issue.

The user never leaves GitHub. Knight operates entirely in the background.

---

## Architecture

```
GitHub Webhook
      │
      ▼
FastAPI API (knight/api/)
  - Validates signature
  - Deduplicates by X-GitHub-Delivery
  - Extracts task payload
  - Enqueues via Celery
      │
      ▼
Redis (broker + result backend)
      │
      ▼
Celery Worker (knight/worker/)
  - prepare_task: clone/fetch repo, provision git worktree
  - CodingAgentService: runs pi subprocess via JSONL RPC
  - WorkerGitOpsService: commit, push, open/update PR, notify issue
      │
      ▼
Pi Coding Agent (external binary: `pi`)
  - LLM loop with read/write/edit/bash tools
  - Communicates via stdin/stdout JSONL
  - Session JSONL saved to DB for continuations
```

### Key Design Decisions

- **Pi handles the LLM loop.** Knight handles workspace prep and post-workflow (commit/push/PR/notify). Knight does not call the LLM directly for coding.
- **LangChain is kept** for commit message + changelog generation (one LLM call via `CommitMessageService.generate_both()`). It was intentionally kept despite being a heavy dep.
- **Worktrees, not branches directly.** Each issue gets its own git worktree under `.knight/sandboxes/<repo-key>/worktrees/<issue-slug>/`. The bare repo lives at `.knight/sandboxes/<repo-key>/repo/`.
- **Session persistence.** Pi's JSONL session is saved to the DB after each run (keyed by `issue_id`). On the next trigger for the same issue, the session is restored via `switch_session` RPC so pi has full conversation history.
- **Model config is in the DB**, not env vars. Use `app_config` table with `scope=global` or `scope=repository`. Keys: `agent_provider`, `agent_model_default`, `agent_model_high`, `agent_model_low`. The currently configured model (as of last session) is `gpt-5-mini-2025-08-07` via `openai` provider (set via DB).

---

## Directory Layout

```
knight/
  api/
    app.py              — FastAPI app, mounts all routers
    config.py           — APISettings (env prefix API_)
    routers/
      github.py         — GitHub webhook handler (main entry point)
      webhooks.py       — Generic webhook endpoint
      health.py         — Health check
  agents/
    service.py          — PiAgentRunner: subprocess management, JSONL protocol
    models.py           — AgentTaskRequest, AgentRunResult, ToolResult
    runtime_config.py   — AgentConfigResolver: reads model config from DB
    config.py           — AgentSettings (env vars, all overridable via DB)
    llm.py              — create_agent_model(): LangChain model factory
  worker/
    celery_app.py       — Celery app, queue definitions, startup worktree sweep
    producer.py         — enqueue_agent_task(): validates + sends to Celery
    runtime.py          — WorkerRuntimeService: prepare_task() → sandbox dict
    git_ops.py          — WorkerGitOpsService: commit, push, PR, notify
    commit_message.py   — CommitMessageService.generate_both(): one LLM call
    pr_description.py   — ChangelogService (used for PR body formatting)
    config.py           — WorkerSettings (env vars)
    tasks/
      run_agent_task.py — Main Celery task (soft 140min, hard 150min limit)
      dlq_task.py       — Dead-letter task for failed agent runs
  runtime/
    github.py           — GitHub API: create PR, post comment, react, retry
    github_app.py       — GitHub App JWT + installation token exchange
    worktree.py         — WorktreeProvisioner: clone, fetch, branch, worktree ops
    locking.py          — File-based repo lock (prevents concurrent git ops)
    authorship.py       — Co-author trailer, PR collaboration note helpers
    repository_identity.py — normalize_repository_identity(), slugify, repo key
    sandbox.py          — Sandbox path helpers
    logging_config.py   — Structured JSON logging setup
    filesystem.py       — File utilities
    command_runner.py   — Shell command runner
  utils/
    db/
      engine.py         — create_database_engine()
      schema.py         — SQLAlchemy table definitions
      backend.py        — SqlAlchemyStoreBackend (branches + config CRUD)
      session_store.py  — AgentSessionStore (pi session JSONL, 5MB cap)
      state_store.py    — BranchStateStore, ConfigStore (thin wrappers)
      config_store.py   — ConfigStore.get_string/int/float/string_list
      bootstrap.py      — DB schema creation script
  data/
    pi_provider_map.json — {"google-genai": "google"} — maps provider names for pi
docs/
  core.md               — This file
  bugs.md               — Audit checklist (all 16 items resolved)
  pending.md            — Pending feature ideas
  progress.md           — Historical progress log
scripts/
  init_db.py            — Create tables
  drop_db.py            — Drop tables
docker-compose.yml      — redis + api + worker services
pyproject.toml          — Python 3.13+, uv for package management
.dockerignore           — Excludes .git, docs/, experimental/, references/
```

---

## Database Schema

Three tables, all managed by SQLAlchemy (no ORM, raw Core):

### `agent_branches`
Tracks the git branch created for each issue.
- `repository` (str) — e.g. `owner/repo`
- `issue_id` (str) — e.g. `owner/repo#42`
- `base_branch`, `agent_branch` — branch names
- `pr_number` — GitHub PR number once created
- `status` — `open | pushed | merged | closed | failed`
- Unique on `(repository, issue_id, agent_branch)`

### `app_config`
Key-value store for runtime config. Overrides env defaults.
- `scope` — `global` or `repository`
- `repository` — NULL for global, `owner/repo` for repo-scoped
- `key`, `value` (JSON), `description`
- Unique on `(scope, repository, key)`

Model is configured here: set `agent_provider`, `agent_model_high`, etc.

### `agent_sessions`
Stores pi's JSONL session data per issue.
- `issue_id` (PK)
- `session_file_name` — the `.jsonl` filename pi uses
- `session_data` — full JSONL content, capped at 5MB (trimmed from oldest lines)
- `updated_at`

---

## Pi RPC Protocol

Pi is invoked as: `pi --mode rpc --session-dir <dir> --provider <p> --model <m>`

Communication is JSONL over stdin/stdout. Knight sends:

```json
{"type": "set_auto_compaction", "enabled": true}
{"type": "set_auto_retry", "enabled": true}
{"type": "follow_up", "message": "Review your work..."}
{"type": "switch_session", "sessionPath": "/tmp/.../session.jsonl"}  // continuations only
{"type": "prompt", "message": "<full task prompt>"}
```

Pi emits events:
- `tool_execution_start` — fields: `toolCallId`, `toolName`
- `tool_execution_end` — fields: `toolCallId`, `toolName`, `isError`, `result.content[0].text`
- `message_end` — fields: `message.role`, `message.content[].text` (last assistant message)
- `agent_end` — fields: `reason` or `status` (e.g. `max_iterations`, `error`)
- `extension_ui_request` — pi blocking on confirm/select/input dialog; auto-responded in reader thread
- `response` (with `command: "switch_session"`) — signals session swap complete

### Critical: switch_session timing bug (fixed)

`switch_session` does async file I/O inside pi. If the prompt is sent immediately after `switch_session`, pi accepts it for the **old** session before the swap completes and then discards it. This caused pi to hang indefinitely (47+ minute runs, no progress).

**Fix:** All stdout reads happen in a single reader thread (`_read_stdout`). The thread sets `_waiting_for_switch = True` before starting, drains output until it sees `response/switch_session`, then sends the prompt. 30-second deadline before sending anyway. No `select()` used — that had a TextIOWrapper buffering race.

### Critical: extension_ui_request auto-response (fixed)

Pi shows confirmation dialogs for tool use. In RPC mode these block until a response is written to stdin. Knight auto-responds in the reader thread: `confirm → {confirmed: True}`, `select/input/editor → {value: options[0]}`.

---

## Task Flow (end-to-end)

1. **Webhook arrives** at `POST /api/github/webhook`
   - Signature verified via `hmac.compare_digest`
   - `X-GitHub-Delivery` header checked against `_seen_deliveries` dict (1h TTL) — duplicate → 202 immediately
   - Event parsed: `issues` (opened/edited), `issue_comment` (created), `pull_request_review_comment` (created)
   - Trigger keyword checked (default: `@knight`)
   - For `issue_comment`: trigger keyword stripped from instructions
   - GitHub token resolved: App installation token preferred, PAT fallback
   - `enqueue_agent_task()` called

2. **Celery task starts** (`run_agent_task`)
   - Reacts to trigger comment with 👀 emoji
   - `WorkerRuntimeService.prepare_task()`:
     - Looks up existing `agent_branches` record for this `(repository, issue_id)`
     - Provisions worktree via `WorktreeProvisioner.prepare_worktree()`
       - Acquires file lock on `<sandbox>/<repo-key>/.repo.lock`
       - Clones repo if not present, else fetches + resets to remote base
       - Creates/reuses git worktree at `<sandbox>/<repo-key>/worktrees/<issue-slug>/`
       - Branch name: reuses existing `agent_branch` from DB, or generates `knight/<issue-slug>`
     - Upserts `agent_branches` record
   - `CodingAgentService.run()` → `PiAgentRunner.run()`
   - `WorkerGitOpsService.finalize_task()`:
     - `git diff` + `git status` to detect changes
     - If changes + `commit_changes`: generates commit message + changelog via single LLM call, commits
     - If committed + `push_changes`: pushes branch to origin
     - If pushed + no existing PR: `create_github_pr()` — checks for existing PR first, creates only if none
     - If PR existed: posts changelog comment to PR
     - Posts notification comment to original issue with PR link
     - Cleans up worktree if `cleanup_worktree` is set
     - Updates `agent_branches` status to `pushed`

3. **On failure:**
   - `SoftTimeLimitExceeded` (140min): posts "ran out of time" comment, re-raises (no retry)
   - `Exception`: retries once after 90s, then posts error comment + routes payload to `knight-tasks-dlq` queue

---

## Environment Variables

### API service (prefix `API_`)
```
API_WEBHOOK_SECRET          — generic webhook auth (optional)
API_GITHUB_WEBHOOK_SECRET   — GitHub webhook HMAC secret
API_GITHUB_TOKEN            — PAT fallback token
API_GITHUB_APP_ID           — GitHub App ID (preferred)
API_GITHUB_APP_PRIVATE_KEY  — GitHub App private key PEM
API_GITHUB_TRIGGER_KEYWORD  — default "@knight"
API_CORS_ORIGINS            — allowed CORS origins
```

### Worker service (no prefix)
```
DATABASE_URL                — Postgres connection string
CELERY_BROKER_URL           — redis://...:6379/0
CELERY_RESULT_BACKEND       — redis://...:6379/1
WORKER_SANDBOX_ROOT         — .knight/sandboxes (where clones/worktrees go)
WORKER_GIT_USER_NAME        — commit author name ("Knight Bot")
WORKER_GIT_USER_EMAIL       — commit author email
GITHUB_TOKEN                — worker-side PAT (for PR creation)
```

### Agent config (overridden by DB at runtime)
```
AGENT_PROVIDER              — openai | anthropic | google-genai
AGENT_MODEL_DEFAULT         — model name
AGENT_MODEL_HIGH            — model for high-complexity tasks (what pi uses)
AGENT_MODEL_LOW             — model for commit message generation
AGENT_MAX_STEPS             — 25 (pi iteration limit)
AGENT_COMMAND_TIMEOUT_SECONDS — 300
```

---

## Celery Configuration

- **Main queue:** `knight.default` (configurable via `CELERY_TASK_DEFAULT_QUEUE`)
- **DLQ:** `knight.default-dlq`
- **Broker:** Redis db 0
- **Result backend:** Redis db 1
- **Task limits:** `soft_time_limit=8400` (140min), `time_limit=9000` (150min)
- **Reliability:** `acks_late=True`, `reject_on_worker_lost=True`
- **Retries:** `max_retries=1`, `default_retry_delay=90s` (Exception only, not SoftTimeLimitExceeded)
- **Startup hook:** `worker_ready` signal sweeps `<sandbox_root>/*/worktrees/` and removes dirs with `mtime > 4h`

---

## GitHub Integration

### Auth priority
1. **GitHub App** — `github_app_id` + `github_app_private_key` → generates short-lived installation token per webhook event
2. **PAT** — `github_token` — static, simpler, works for public repos

### PR flow
1. `_find_existing_pr()` — GET `/repos/{owner}/{repo}/pulls?head={owner}:{branch}&state=open` — **checked first**
2. If found → `pr_existing=True`, post changelog comment to PR, notify issue
3. If not found → POST `/repos/{owner}/{repo}/pulls` to create
4. All GitHub API calls use `requests.Session` with `urllib3.Retry(total=3, backoff_factor=1, status_forcelist=(429,500,502,503,504))`

### Webhook deduplication
`X-GitHub-Delivery` header stored in `_seen_deliveries: dict[str, float]` for 1 hour. Duplicate delivery → immediate 202, no task enqueued.

---

## Pi Prompt Design

**First run:** full prompt including working environment, branch info, AGENTS.md content (if present), task execution instructions, coding standards, and the task itself.

**Continuation run (same issue, existing session):** short prompt — just workspace reminder + task instructions + scope/verify reminder. Full conversation history already in pi's session.

**Follow-up pass:** queued before the prompt via `follow_up` RPC. Pi performs a self-review after its main run: re-reads modified files, checks for syntax errors, incomplete changes, regressions.

**Coding standards injected:**
- Read files before modifying
- Match scope exactly (no over-engineering, no token changes on redesign tasks)
- Verify after implementing (re-read, run linters/tests)
- No backup files, no copyright headers, no unnecessary comments

---

## Upsert Pattern (DB)

All upserts use UPDATE-first (no savepoints):
```python
result = conn.execute(update(...).where(filter).values(...))
if result.rowcount == 0:
    try:
        conn.execute(insert(...).values(...))
    except IntegrityError:
        pass  # lost concurrent insert race — other writer's row is fine
```

---

## Known Intentional Non-Fixes

- **LangChain dependency** — heavy but kept; used for commit message + changelog LLM call
- **pi_provider_map.json only has `google-genai`** — `.get(k, k)` passthrough handles all other providers correctly; no action needed

---

## How to Run Locally

```bash
# Start dependencies
docker compose up redis -d

# Install deps
uv sync

# Init DB
uv run python scripts/init_db.py

# Start API
uv run fastapi dev knight/api/app.py

# Start worker
uv run celery -A knight.worker.celery_app:celery_app worker --loglevel=info --queues=knight.default
```

## How to Set Model Config

Via DB (takes effect immediately, no restart needed):

```python
from knight.utils.db.config_store import ConfigStore
store = ConfigStore()
store.set("agent_provider", "openai", scope="global")
store.set("agent_model_high", "gpt-5-mini-2025-08-07", scope="global")
store.set("agent_model_low", "gpt-5-mini-2025-08-07", scope="global")
```

Or per-repository by passing `repository="owner/repo"` and `scope="repository"`.

---

## Commit Conventions

Imperative mood, conventional commits format. No co-author trailers. Example: `feat(worker): add DLQ queue + one retry for failed agent tasks`
