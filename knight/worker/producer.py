from collections.abc import Mapping
from typing import Any

from knight.agents.models import AgentTaskRequest
from knight.worker.tasks.run_agent_task import run_agent_task


def enqueue_agent_task(payload: Mapping[str, Any] | None = None) -> str:
    task_payload = AgentTaskRequest.model_validate(payload or {}).model_dump()

    result = run_agent_task.delay(dict(task_payload))
    return result.id
