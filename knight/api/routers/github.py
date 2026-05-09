"""GitHub webhook receiver.

Listens for GitHub events (issues, issue_comment, pull_request_review_comment)
and enqueues a Knight agent task when the trigger keyword is found.

Auth priority:
  1. GitHub App (app_id + private_key) — generates a short-lived installation
     token per webhook event. Preferred for private repos and org-wide installs.
  2. PAT (github_token) — static token, simpler but less secure.

Webhook setup:
  GitHub repo → Settings → Webhooks → Add webhook
  Payload URL: https://<your-host>/api/github/webhook
  Content type: application/json
  Secret: value of API_GITHUB_WEBHOOK_SECRET env var
  Events: Issues, Issue comments, Pull request review comments
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import time
from typing import Any

import httpx
from fastapi import APIRouter, Header, HTTPException, Request, status

from knight.api.config import settings
from knight.runtime.github_app import get_installation_token
from knight.utils.local.config_store import ConfigStore
from knight.worker.producer import enqueue_agent_task

# Non-sensitive config (trigger keyword, etc.) — loaded once at startup.
_cfg = ConfigStore()

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/github", tags=["GitHub"])

_SUPPORTED_EVENTS = {"issues", "issue_comment", "pull_request_review_comment"}

# Delivery IDs seen within the last hour — prevents double-processing GitHub retries.
_seen_deliveries: dict[str, float] = {}
_DELIVERY_TTL = 3600  # seconds


def _is_duplicate_delivery(delivery_id: str) -> bool:
    """Return True if this delivery was already processed. Registers it if new."""
    now = time.time()
    # Prune expired entries
    expired = [k for k, t in _seen_deliveries.items() if now - t > _DELIVERY_TTL]
    for k in expired:
        del _seen_deliveries[k]
    if delivery_id in _seen_deliveries:
        return True
    _seen_deliveries[delivery_id] = now
    return False


def _verify_signature(body: bytes, signature_header: str | None) -> None:
    """Raise 403 if the payload signature does not match the configured secret."""
    secret = settings.github_webhook_secret
    if not secret:
        logger.warning("github_webhook_secret not set; skipping signature verification")
        return

    if not signature_header or not signature_header.startswith("sha256="):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing or malformed X-Hub-Signature-256 header",
        )

    expected = "sha256=" + hmac.new(
        secret.encode(), body, digestmod=hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected, signature_header):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Signature mismatch",
        )


def _contains_trigger(text: str) -> bool:
    keyword = _cfg.get_string(key="github_trigger_keyword", default="@knight")
    if not keyword:
        return True
    return keyword.lower() in text.lower()


async def _resolve_token(installation_id: int | None) -> str:
    """Return the best available GitHub token.

    If App credentials are configured and an installation_id is present,
    exchange them for a short-lived installation access token.
    Otherwise fall back to the configured PAT.
    """
    app_id = settings.github_app_id
    app_private_key = settings.github_app_private_key
    if app_id and app_private_key and installation_id:
        try:
            token = await get_installation_token(
                app_id=app_id,
                private_key=app_private_key,
                installation_id=installation_id,
            )
            logger.debug(
                "resolved github app installation token",
                extra={"installation_id": installation_id},
            )
            return token
        except Exception:
            logger.exception(
                "failed to get github app installation token; falling back to PAT",
                extra={"installation_id": installation_id},
            )

    return settings.github_token


def _extract_task(
    event: str,
    payload: dict[str, Any],
    github_token: str,
) -> dict[str, Any] | None:
    """Return an enqueue-ready payload dict, or None if this event should be ignored."""
    repo = payload.get("repository", {})
    repository_url: str = repo.get("clone_url", "")
    repo_full_name: str = repo.get("full_name", "")
    author_login: str = payload.get("sender", {}).get("login", "")

    if not repository_url:
        return None

    base: dict[str, Any] = {
        "repository_url": repository_url,
        "author_name": author_login,
        "github_token": github_token,
    }

    if event == "issues":
        action = payload.get("action", "")
        if action not in {"opened", "edited"}:
            return None
        issue = payload.get("issue", {})
        issue_number = issue.get("number")
        title: str = issue.get("title", "")
        body: str = issue.get("body") or ""
        instructions = f"{title}\n\n{body}".strip()
        if not instructions or not _contains_trigger(instructions):
            return None
        return {
            **base,
            "issue_id": f"{repo_full_name}#{issue_number}",
            "instructions": instructions,
            "task_type": "issue",
        }

    if event == "issue_comment":
        if payload.get("action") != "created":
            return None
        comment = payload.get("comment", {})
        comment_body = comment.get("body") or ""
        if not _contains_trigger(comment_body):
            return None
        # Strip trigger keyword — it's routing noise, not part of the task
        trigger = _cfg.get_string(key="github_trigger_keyword", default="@knight")
        clean_comment = comment_body.replace(trigger, "").strip() if trigger else comment_body.strip()
        issue = payload.get("issue", {})
        issue_number = issue.get("number")
        issue_title: str = issue.get("title", "")
        issue_body: str = issue.get("body") or ""
        return {
            **base,
            "issue_id": f"{repo_full_name}#{issue_number}",
            "issue_context": f"## {issue_title}\n\n{issue_body}".strip(),
            "instructions": clean_comment,
            "task_type": "issue_comment",
            "trigger_comment_id": comment.get("id"),
        }

    if event == "pull_request_review_comment":
        if payload.get("action") != "created":
            return None
        body = payload.get("comment", {}).get("body") or ""
        if not _contains_trigger(body):
            return None
        pr = payload.get("pull_request", {})
        pr_number = pr.get("number")
        head_branch: str = pr.get("head", {}).get("ref", "")
        return {
            **base,
            "issue_id": f"{repo_full_name}#{pr_number}",
            "branch_name": head_branch,
            "instructions": body.strip(),
            "task_type": "pr_review_comment",
        }

    return None


@router.post("/webhook", status_code=status.HTTP_202_ACCEPTED)
async def github_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None),
    x_github_event: str | None = Header(default=None),
    x_github_delivery: str | None = Header(default=None),
) -> dict[str, str]:
    body = await request.body()
    _verify_signature(body, x_hub_signature_256)

    if x_github_delivery and _is_duplicate_delivery(x_github_delivery):
        logger.info("ignoring duplicate github delivery: %s", x_github_delivery)
        return {"status": "duplicate", "delivery_id": x_github_delivery}

    event = (x_github_event or "").lower()
    if event not in _SUPPORTED_EVENTS:
        logger.debug("ignoring unsupported github event: %s", event)
        return {"status": "ignored", "reason": f"event '{event}' not handled"}

    try:
        payload: dict[str, Any] = await request.json()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload",
        )

    installation_id: int | None = (payload.get("installation") or {}).get("id")
    github_token = await _resolve_token(installation_id)

    task_payload = _extract_task(event, payload, github_token)
    if task_payload is None:
        return {"status": "ignored", "reason": "event did not match trigger criteria"}

    task_id = enqueue_agent_task(task_payload)
    logger.info(
        "github webhook enqueued task",
        extra={
            "event": event,
            "task_id": task_id,
            "repository_url": task_payload.get("repository_url"),
            "issue_id": task_payload.get("issue_id"),
            "author": task_payload.get("author_name"),
            "auth_method": "app" if installation_id and settings.github_app_id else "pat",
        },
    )
    return {"status": "queued", "task_id": task_id}
