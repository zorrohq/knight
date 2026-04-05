from collections.abc import Mapping
from typing import Any

from knight.worker.tasks.run_agent_task import run_agent_task


def enqueue_agent_task(payload: Mapping[str, Any] | None = None) -> str:
    task_payload = {
        "repository_url": "",
        "task_type": "repository_task",
        "instructions": "",
    }
    if payload:
        task_payload.update(payload)

    result = run_agent_task.delay(dict(task_payload))
    return result.id
