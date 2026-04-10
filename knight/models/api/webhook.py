from pydantic import BaseModel


class WebhookEventRequest(BaseModel):
    repository_url: str = ""
    repository_local_path: str = ""
    issue_id: str = ""
    base_branch: str = "main"
    branch_name: str = ""
    push_remote: str = "origin"
    commit_changes: bool = True
    push_changes: bool = True
    cleanup_worktree: bool = True
    task_type: str = "repository_task"
    instructions: str = ""


class WebhookEventResponse(BaseModel):
    task_id: str
    status: str
