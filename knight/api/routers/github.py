"""GitHub webhook receiver.

Listens for GitHub events (issues, issue_comment, pull_request_review_comment)
and enqueues a Knight agent task when the trigger keyword is found.

Webhook setup:
  GitHub repo → Settings → Webhooks → Add webhook
  Payload URL: https://<your-host>/api/github/webhook
  Content type: application/json
  Secret: value of GITHUB_WEBHOOK_SECRET env var
  Events: Issues, Issue comments, Pull request review comments
"""
from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request, status

from knight.api.config import settings
from knight.worker.producer import enqueue_agent_task

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/github", tags=["GitHub"])

# GitHub events we care about
_SUPPORTED_EVENTS = {"issues", "issue_comment", "pull_request_review_comment"}


def _verify_signature(body: bytes, signature_header: str | None) -> None:
    """Raise 403 if the payload signature does not match the configured secret."""
    secret = settings.github_webhook_secret
    if not secret:
        # No secret configured — skip verification (dev/test mode).
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
    keyword = settings.github_trigger_keyword
    if not keyword:
        return True
    return keyword.lower() in text.lower()


def _extract_task(event: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    """Return an enqueue-ready payload dict, or None if this event should be ignored."""
    repo = payload.get("repository", {})
    repository_url: str = repo.get("clone_url", "")
    repo_full_name: str = repo.get("full_name", "")

    sender = payload.get("sender", {})
    author_login: str = sender.get("login", "")

    if not repository_url:
        return None

    # Use the token configured server-side; callers cannot supply their own.
    github_token = settings.github_token

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
            "repository_url": repository_url,
            "issue_id": f"{repo_full_name}#{issue_number}",
            "instructions": instructions,
            "author_name": author_login,
            "github_token": github_token,
            "task_type": "issue",
        }

    if event == "issue_comment":
        if payload.get("action") != "created":
            return None
        comment = payload.get("comment", {})
        body = comment.get("body") or ""
        if not _contains_trigger(body):
            return None
        issue = payload.get("issue", {})
        issue_number = issue.get("number")
        instructions = body.strip()
        return {
            "repository_url": repository_url,
            "issue_id": f"{repo_full_name}#{issue_number}",
            "instructions": instructions,
            "author_name": author_login,
            "github_token": github_token,
            "task_type": "issue_comment",
        }

    if event == "pull_request_review_comment":
        if payload.get("action") != "created":
            return None
        comment = payload.get("comment", {})
        body = comment.get("body") or ""
        if not _contains_trigger(body):
            return None
        pr = payload.get("pull_request", {})
        pr_number = pr.get("number")
        # Use the PR's head branch so the agent works on the right branch
        head_branch: str = pr.get("head", {}).get("ref", "")
        instructions = body.strip()
        return {
            "repository_url": repository_url,
            "issue_id": f"{repo_full_name}#{pr_number}",
            "branch_name": head_branch,
            "instructions": instructions,
            "author_name": author_login,
            "github_token": github_token,
            "task_type": "pr_review_comment",
        }

    return None


@router.post(
    "/webhook",
    status_code=status.HTTP_202_ACCEPTED,
)
async def github_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None),
    x_github_event: str | None = Header(default=None),
) -> dict[str, str]:
    body = await request.body()
    _verify_signature(body, x_hub_signature_256)

    event = (x_github_event or "").lower()
    if event not in _SUPPORTED_EVENTS:
        # Acknowledge silently — GitHub sends many events we don't care about.
        logger.debug("ignoring unsupported github event: %s", event)
        return {"status": "ignored", "reason": f"event '{event}' not handled"}

    try:
        payload: dict[str, Any] = await request.json()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload",
        )

    task_payload = _extract_task(event, payload)
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
        },
    )
    return {"status": "queued", "task_id": task_id}
