from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    celery_app_name: str = "knight"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"
    celery_task_default_queue: str = "knight.default"
    celery_task_serializer: str = "json"
    celery_result_serializer: str = "json"
    celery_accept_content: list[str] = ["json"]
    celery_timezone: str = "UTC"
    worker_sandbox_root: str = ".knight/sandboxes"
    worker_state_store_path: str = ".knight/state/agent_branches.json"
    worker_default_base_branch: str = "main"
    worker_repo_lock_timeout_seconds: int = 30
    worker_repo_lock_poll_interval_seconds: float = 0.1
    worker_git_user_name: str = "Knight Bot"
    worker_git_user_email: str = "knight@example.com"
    worker_commit_max_diff_chars: int = 20000


settings = WorkerSettings()
