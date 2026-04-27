from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field

from knight.worker.config import settings
from knight.utils.db.backend import create_store_backend


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


class BranchRecord(BaseModel):
    repository: str
    issue_id: str
    base_branch: str
    agent_branch: str
    pr_number: int | None = None
    provider: str = "github"
    status: str = "open"
    created_at: str = Field(default_factory=_utc_now)
    updated_at: str = Field(default_factory=_utc_now)


class BranchStateStore:
    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url or settings.database_url
        if not self.database_url:
            raise ValueError("DATABASE_URL must be configured")
        self.backend = create_store_backend(self.database_url)

    def get_open_branch(
        self,
        *,
        repository: str,
        issue_id: str,
    ) -> BranchRecord | None:
        row = self.backend.get_open_branch(repository=repository, issue_id=issue_id)
        return BranchRecord.model_validate(row) if row else None

    def upsert_branch(self, record: BranchRecord) -> BranchRecord:
        row = self.backend.upsert_branch(record.model_dump())
        return BranchRecord.model_validate(row)

    def mark_branch_status(
        self,
        *,
        repository: str,
        issue_id: str,
        agent_branch: str,
        status: str,
        pr_number: int | None = None,
    ) -> BranchRecord | None:
        row = self.backend.mark_branch_status(
            repository=repository,
            issue_id=issue_id,
            agent_branch=agent_branch,
            status=status,
            pr_number=pr_number,
        )
        return BranchRecord.model_validate(row) if row else None
