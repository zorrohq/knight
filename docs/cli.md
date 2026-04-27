# Knight CLI — Build Reference

This document is the authoritative spec for building the Knight Go CLI. It covers the full config schema, how each field maps to env vars inside the containers, expected CLI commands, and the intended Docker usage pattern.

---

## Overview

The CLI's job is simple:

1. **`knight init`** — interactive wizard that writes `config.json`
2. **`knight config`** — read/write individual fields in `config.json`
3. **`knight start`** — launch the Docker stack (api + worker + redis) using the local `config.json` and `.knight/` dir as volumes

The user never touches env vars or Docker flags directly. The CLI owns that translation layer.

---

## Config File

### Location

`config.json` in the current working directory (where the user runs `knight`).

Inside the Docker containers it is mounted at `/app/config.json`. The containers read it via `CONFIG_PATH=/app/config.json`.

### Full Schema

```json
{
  "provider": "openai",
  "model_default": "gpt-5-mini-2025-08-07",
  "model_high": "gpt-5-mini-2025-08-07",
  "model_low": "gpt-5-mini-2025-08-07",
  "temperature": 0.0,
  "max_steps": 25,
  "command_timeout_seconds": 300,
  "max_command_output_chars": 12000,
  "blocked_command_prefixes": ["rm", "sudo", "shutdown", "reboot", "mkfs", "dd"],

  "trigger_keyword": "@knight",
  "github_token": "ghp_...",
  "github_webhook_secret": "...",
  "github_app_id": "",
  "github_app_private_key": "",

  "git_user_name": "Knight Bot",
  "git_user_email": "knight@example.com",

  "repositories": {
    "owner/repo": {
      "model_high": "gpt-5.3-codex",
      "max_steps": 40
    }
  }
}
```

### Field Reference

| Field | Type | Default | Description |
|---|---|---|---|
| `provider` | string | `""` | LLM provider: `openai`, `anthropic`, `google-genai` |
| `model_default` | string | `""` | Fallback model when no tier-specific model is set |
| `model_high` | string | `""` | Model used by the coding agent (pi). Falls back to `model_default` |
| `model_low` | string | `""` | Model used for commit messages / changelogs. Falls back to `model_default` |
| `temperature` | float | `0.0` | Sampling temperature for all LLM calls |
| `max_steps` | int | `25` | Max tool iterations per agent run |
| `command_timeout_seconds` | int | `300` | Max seconds a single shell command can run inside the agent |
| `max_command_output_chars` | int | `12000` | Max stdout/stderr chars captured from agent shell commands |
| `blocked_command_prefixes` | []string | see above | Shell command prefixes the agent is not allowed to run |
| `trigger_keyword` | string | `"@knight"` | String that must appear in a GitHub comment to trigger Knight. Empty string triggers on all events |
| `github_token` | string | `""` | GitHub Personal Access Token. Used for PR creation, commenting, reactions |
| `github_webhook_secret` | string | `""` | HMAC secret configured in the GitHub webhook settings for payload verification |
| `github_app_id` | string | `""` | GitHub App ID. When set alongside `github_app_private_key`, generates short-lived installation tokens instead of using the PAT |
| `github_app_private_key` | string | `""` | GitHub App private key (PEM). Can be inline or a path to a file |
| `git_user_name` | string | `"Knight Bot"` | Git commit author name |
| `git_user_email` | string | `"knight@example.com"` | Git commit author email |
| `repositories` | object | `{}` | Per-repository overrides. Keys are `owner/repo`. Supported override fields: `provider`, `model_default`, `model_high`, `model_low`, `temperature`, `max_steps`, `command_timeout_seconds`, `max_command_output_chars`, `blocked_command_prefixes` |

### Auth Priority

1. If `github_app_id` + `github_app_private_key` are both set → generates a short-lived installation token per webhook event (preferred for org installs and private repos)
2. Otherwise → uses `github_token` (PAT)

---

## Data Directory

Knight stores all runtime state in `.knight/` in the current working directory.

```
.knight/
  sandboxes/          — cloned repos and git worktrees (can be large)
    <repo-slug>/
      repo/           — bare clone
      worktrees/
        <issue-slug>/ — per-issue working tree
  sessions/           — pi agent session JSONL, one file per issue
    owner_repo_42.jsonl
  state.db            — SQLite database tracking branch state per issue
```

Inside Docker it is mounted at `/data/.knight`. The container reads it via `KNIGHT_DATA_DIR=/data/.knight` and `WORKER_SANDBOX_ROOT=/data/.knight/sandboxes`.

---

## Environment Variables

The CLI translates `config.json` fields into these env vars when launching containers. The CLI constructs the Docker run command — users never set these directly.

### API container (`API_` prefix)

| Env var | Source | Notes |
|---|---|---|
| `API_GITHUB_TOKEN` | `config.github_token` | |
| `API_GITHUB_WEBHOOK_SECRET` | `config.github_webhook_secret` | |
| `API_GITHUB_APP_ID` | `config.github_app_id` | |
| `API_GITHUB_APP_PRIVATE_KEY` | `config.github_app_private_key` | |
| `API_GITHUB_TRIGGER_KEYWORD` | `config.trigger_keyword` | |
| `API_CORS_ORIGINS` | hardcoded or future config field | |

### Worker container (no prefix)

| Env var | Source | Notes |
|---|---|---|
| `CONFIG_PATH` | `/app/config.json` | fixed mount path |
| `KNIGHT_DATA_DIR` | `/data/.knight` | fixed mount path |
| `WORKER_SANDBOX_ROOT` | `/data/.knight/sandboxes` | derived from data dir |
| `WORKER_GIT_USER_NAME` | `config.git_user_name` | |
| `WORKER_GIT_USER_EMAIL` | `config.git_user_email` | |
| `GITHUB_TOKEN` | `config.github_token` | worker-side token for PR creation |
| `CELERY_BROKER_URL` | `redis://redis:6379/0` | internal network, fixed |
| `CELERY_RESULT_BACKEND` | `redis://redis:6379/1` | internal network, fixed |

### LLM API keys (always env vars, never in config.json)

These are secrets and must be passed as env vars, not stored in `config.json`.

| Env var | When needed |
|---|---|
| `OPENAI_API_KEY` | `provider = "openai"` |
| `ANTHROPIC_API_KEY` | `provider = "anthropic"` |
| `GOOGLE_API_KEY` | `provider = "google-genai"` |

The CLI should prompt for the relevant key during `knight init` and store it in the shell environment (or a `.env` file that is gitignored), never in `config.json`.

---

## CLI Commands

### `knight init`

Interactive wizard. Asks questions, writes `config.json` and an optional `.env` for API keys.

```
$ knight init

Provider [openai/anthropic/google-genai]: openai
Model (high tier, used for coding): gpt-5-mini-2025-08-07
Model (low tier, used for commit messages) [same]:
GitHub token (PAT): ghp_...
GitHub webhook secret (leave blank to generate):
Trigger keyword [@knight]:
Git author name [Knight Bot]:
Git author email [knight@example.com]:

✓ Written config.json
✓ Written .env  (add to .gitignore)
```

Generates a random webhook secret if left blank. Tells the user to configure that secret in GitHub → Settings → Webhooks.

### `knight config set <key> <value>`

Update a single field in `config.json`.

```
knight config set model_high gpt-5.3-codex
knight config set trigger_keyword "@bot"
knight config set repositories.owner/repo.model_high gpt-5.3-codex
```

Dot-notation for nested fields. For the `repositories` block:
- `knight config set repositories.owner/repo.model_high gpt-5.3-codex`

### `knight config get <key>`

Print the current value of a field.

```
$ knight config get model_high
gpt-5-mini-2025-08-07
```

### `knight config show`

Pretty-print the full `config.json` with secrets redacted.

```
$ knight config show
provider:       openai
model_high:     gpt-5-mini-2025-08-07
model_low:      gpt-5-mini-2025-08-07
trigger:        @knight
github_token:   ghp_***...abc
webhook_secret: ***
repositories:   (none)
```

### `knight start`

Pull the GHCR image and start the stack (api + worker + redis).

```
knight start [--image ghcr.io/you/knight:latest] [--port 8000]
```

Equivalent Docker invocation the CLI constructs:

```bash
docker network create knight-net 2>/dev/null || true

docker run -d --name knight-redis --network knight-net redis:7-alpine

docker run -d --name knight-api \
  --network knight-net \
  -p 8000:8000 \
  -v "$(pwd)/config.json:/app/config.json:ro" \
  -e API_GITHUB_TOKEN="..." \
  -e API_GITHUB_WEBHOOK_SECRET="..." \
  -e API_GITHUB_TRIGGER_KEYWORD="@knight" \
  -e API_CELERY_BROKER_URL="redis://knight-redis:6379/0" \
  ghcr.io/you/knight:latest \
  fastapi run knight/api/app.py

docker run -d --name knight-worker \
  --network knight-net \
  -v "$(pwd)/config.json:/app/config.json:ro" \
  -v "$(pwd)/.knight:/data/.knight" \
  -e CONFIG_PATH="/app/config.json" \
  -e KNIGHT_DATA_DIR="/data/.knight" \
  -e WORKER_SANDBOX_ROOT="/data/.knight/sandboxes" \
  -e CELERY_BROKER_URL="redis://knight-redis:6379/0" \
  -e CELERY_RESULT_BACKEND="redis://knight-redis:6379/1" \
  -e OPENAI_API_KEY="..." \
  ghcr.io/you/knight:latest \
  celery -A knight.worker.celery_app:celery_app worker --loglevel=info --queues=knight.default
```

### `knight stop`

Stop and remove all Knight containers (but not the data dir or config.json).

### `knight status`

Show running containers and their health.

### `knight logs [api|worker]`

Tail logs from the specified container.

---

## Implementation Notes for the CLI

### Config file handling

- Read/write `config.json` atomically (write to `.config.json.tmp`, then rename) to avoid corrupt writes
- On `config set`, load → mutate → write. Never reformat the whole file if only one field changed — preserve field order
- Validate `provider` against the allowed set (`openai`, `anthropic`, `google-genai`) before writing
- For `github_app_private_key`: accept either an inline PEM string or a file path. If a file path is given, read the file and inline it into config.json (so the container doesn't need a separate volume mount)

### Secret handling

- `github_token`, `github_webhook_secret`, `github_app_private_key` live in `config.json` — acceptable since it's a local file on the user's machine
- LLM API keys (`OPENAI_API_KEY` etc.) must NOT go in `config.json`. Store them in a `.env` file alongside `config.json` and inject via `-e` on `docker run`
- `knight config show` should redact any field containing `token`, `secret`, or `key` in its name — show last 4 chars only

### Docker management

- Use the Docker socket directly (`/var/run/docker.sock`) via the Go Docker SDK (`github.com/docker/docker/client`) rather than shelling out to `docker` — more reliable and portable
- Name containers `knight-redis`, `knight-api`, `knight-worker` so `stop`/`status`/`logs` can find them by name
- On `knight start`, check if containers are already running and skip or restart as appropriate
- Pull the image before starting if it's not present locally

### Webhook URL hint

After `knight start`, print the webhook URL the user should configure in GitHub:

```
✓ Knight is running.

Configure your GitHub webhook:
  Payload URL:  http://<your-public-ip>:8000/api/github/webhook
  Content type: application/json
  Secret:       <webhook_secret from config.json>
  Events:       Issues, Issue comments, Pull request review comments
```

---

## Project Layout for the CLI (suggestion)

```
knight-cli/
  main.go
  cmd/
    root.go
    init.go
    config.go      — set/get/show subcommands
    start.go
    stop.go
    status.go
    logs.go
  internal/
    config/
      config.go    — Config struct, Load(), Save(), redact helpers
    docker/
      client.go    — Docker SDK wrapper
    prompt/
      prompt.go    — interactive wizard helpers
  go.mod
```

Recommended Go libraries:
- CLI framework: `github.com/spf13/cobra`
- Interactive prompts: `github.com/charmbracelet/huh` or `github.com/AlecAivazis/survey/v2`
- Docker: `github.com/docker/docker/client`
- JSON with key order preservation: `encoding/json` is fine (Go structs preserve declaration order on marshal)
