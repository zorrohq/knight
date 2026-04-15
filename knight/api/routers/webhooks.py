import hashlib
import hmac
import logging

from fastapi import APIRouter, Header, HTTPException, status

from knight.api.config import settings
from knight.models.api.webhook import WebhookEventRequest, WebhookEventResponse
from knight.worker.producer import enqueue_agent_task

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


def _verify_secret(x_webhook_secret: str | None) -> None:
    """Raise 403 if a webhook secret is configured and the header does not match."""
    secret = settings.webhook_secret
    if not secret:
        logger.warning("webhook_secret not set; generic webhook endpoint is unauthenticated")
        return

    if not x_webhook_secret:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing X-Webhook-Secret header",
        )

    if not hmac.compare_digest(
        hashlib.sha256(secret.encode()).digest(),
        hashlib.sha256(x_webhook_secret.encode()).digest(),
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid webhook secret",
        )


@router.post("", response_model=WebhookEventResponse, status_code=status.HTTP_202_ACCEPTED)
async def receive_webhook(
    payload: WebhookEventRequest,
    x_webhook_secret: str | None = Header(default=None),
) -> WebhookEventResponse:
    _verify_secret(x_webhook_secret)
    task_id = enqueue_agent_task(payload.model_dump())
    return WebhookEventResponse(
        task_id=task_id,
        status="queued",
    )
