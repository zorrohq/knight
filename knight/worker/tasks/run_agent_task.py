from collections.abc import Mapping
from typing import Any

from knight.agents.models import AgentTaskRequest
from knight.agents.service import CodingAgentService
from knight.worker.celery_app import celery_app
from knight.worker.runtime import WorkerRuntimeService


@celery_app.task(
    bind=True,
    name="knight.worker.tasks.run_agent_task",
)
def run_agent_task(
    self, payload: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    task = AgentTaskRequest.model_validate(payload or {})
    runtime = WorkerRuntimeService()
    prepared_task, sandbox = runtime.prepare_task(task)
    agent = CodingAgentService()
    result = agent.run(prepared_task, sandbox=sandbox)

    return {
        "task_id": self.request.id,
        "status": result.status,
        "provider_configured": result.provider_configured,
        "final_message": result.final_message,
        "iterations": result.iterations,
        "task": result.task.model_dump(),
        "available_tools": result.available_tools,
        "sandbox": result.sandbox,
        "workspace_summary": result.workspace_summary,
        "steps": [step.model_dump() for step in result.steps],
    }
