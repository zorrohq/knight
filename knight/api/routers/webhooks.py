from fastapi import APIRouter, status

from knight.models.api.webhook import WebhookEventRequest, WebhookEventResponse
from knight.worker.producer import enqueue_agent_task


router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


@router.post("", response_model=WebhookEventResponse, status_code=status.HTTP_202_ACCEPTED)
async def receive_webhook(payload: WebhookEventRequest) -> WebhookEventResponse:
    task_id = enqueue_agent_task(payload.model_dump())
    return WebhookEventResponse(
        task_id=task_id,
        status="queued",
    )
