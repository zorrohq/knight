from collections.abc import Mapping
from typing import Any

from knight.worker.celery_app import celery_app


@celery_app.task(
    bind=True,
    name="knight.worker.tasks.run_agent_task",
)
def run_agent_task(
    self, payload: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    task_payload = {
        "repository_url": "",
        "task_type": "repository_task",
        "instructions": "",
    }
    if payload:
        task_payload.update(payload)

    return {
        "task_id": self.request.id,
        "status": "accepted",
        "payload": dict(task_payload),
    }
