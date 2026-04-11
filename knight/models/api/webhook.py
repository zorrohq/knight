from pydantic import BaseModel, model_validator


class WebhookEventRequest(BaseModel):
    repository_url: str = ""
    repository_local_path: str = ""
    issue_id: str = ""
    base_branch: str = ""
    branch_name: str = ""
    push_remote: str = ""
    commit_changes: bool = True
    push_changes: bool = True
    cleanup_worktree: bool = True
    task_type: str = "repository_task"
    instructions: str = ""
    github_token: str = ""
    author_name: str = ""
    author_email: str = ""

    @model_validator(mode="after")
    def check_repository_and_instructions(self) -> "WebhookEventRequest":
        if not self.repository_url and not self.repository_local_path:
            raise ValueError(
                "at least one of repository_url or repository_local_path must be provided"
            )
        if not self.instructions.strip():
            raise ValueError("instructions must not be empty")
        return self


class WebhookEventResponse(BaseModel):
    task_id: str
    status: str
