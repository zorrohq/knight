from pydantic import BaseModel


class WebhookEventRequest(BaseModel):
    repository_url: str = ""
    task_type: str = "repository_task"
    instructions: str = ""


class WebhookEventResponse(BaseModel):
    task_id: str
    status: str
