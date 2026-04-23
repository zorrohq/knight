"""Dead-letter queue task.

Failed agent tasks are routed here after exhausting retries so that the
payload is preserved in the result backend and visible in logs for inspection
and manual replay.
"""
from __future__ import annotations

from typing import Any

from knight.runtime.logging_config import get_logger
from knight.worker.celery_app import celery_app

logger = get_logger(__name__)


@celery_app.task(
    name="knight.worker.tasks.dlq_task",
    queue="knight-tasks-dlq",
    acks_late=True,
)
def record_dlq_entry(
    *,
    original_task_id: str,
    payload: dict[str, Any],
    error_type: str,
    error_message: str,
) -> dict[str, Any]:
    """Log and store a failed task payload for operator inspection."""
    redacted_payload = {**payload, "github_token": "<redacted>"}
    logger.error(
        "task landed in DLQ",
        extra={
            "original_task_id": original_task_id,
            "issue_id": payload.get("issue_id"),
            "repository_url": payload.get("repository_url"),
            "error_type": error_type,
            "error_message": error_message,
        },
    )
    return {
        "original_task_id": original_task_id,
        "payload": redacted_payload,
        "error_type": error_type,
        "error_message": error_message,
    }
