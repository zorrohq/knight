from collections.abc import Mapping
from typing import Any

from knight.agents.models import AgentTaskRequest
from knight.agents.service import CodingAgentService
from knight.worker.celery_app import celery_app


@celery_app.task(
    bind=True,
    name="knight.worker.tasks.run_agent_task",
)
def run_agent_task(
    self, payload: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    task = AgentTaskRequest.model_validate(payload or {})
    agent = CodingAgentService()
    result = agent.run(task)

    return {
        "task_id": self.request.id,
        "status": result.status,
        "provider_configured": result.provider_configured,
        "task": result.task.model_dump(),
        "available_tools": result.available_tools,
        "workspace_summary": result.workspace_summary,
        "steps": [step.model_dump() for step in result.steps],
    }
