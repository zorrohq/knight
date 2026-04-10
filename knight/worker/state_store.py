from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field
import psycopg
from psycopg.rows import dict_row

from knight.worker.config import settings


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

    def get_open_branch(
        self,
        *,
        repository: str,
        issue_id: str,
    ) -> BranchRecord | None:
        query = """
            SELECT repository, issue_id, base_branch, agent_branch, pr_number, provider, status,
                   created_at::text, updated_at::text
            FROM agent_branches
            WHERE repository = %s
              AND issue_id = %s
              AND status = 'open'
            ORDER BY updated_at DESC
            LIMIT 1
        """
        with self._connect() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(query, (repository, issue_id))
            row = cur.fetchone()
        return BranchRecord.model_validate(row) if row else None

    def upsert_branch(self, record: BranchRecord) -> BranchRecord:
        query = """
            INSERT INTO agent_branches (
                repository,
                issue_id,
                base_branch,
                agent_branch,
                pr_number,
                provider,
                status
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (repository, issue_id, agent_branch)
            DO UPDATE SET
                base_branch = EXCLUDED.base_branch,
                pr_number = EXCLUDED.pr_number,
                provider = EXCLUDED.provider,
                status = EXCLUDED.status,
                updated_at = NOW()
            RETURNING repository, issue_id, base_branch, agent_branch, pr_number, provider, status,
                      created_at::text, updated_at::text
        """
        params = (
            record.repository,
            record.issue_id,
            record.base_branch,
            record.agent_branch,
            record.pr_number,
            record.provider,
            record.status,
        )
        with self._connect() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(query, params)
            row = cur.fetchone()
            conn.commit()
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
        query = """
            UPDATE agent_branches
            SET
                status = %s,
                pr_number = COALESCE(%s, pr_number),
                updated_at = NOW()
            WHERE repository = %s
              AND issue_id = %s
              AND agent_branch = %s
            RETURNING repository, issue_id, base_branch, agent_branch, pr_number, provider, status,
                      created_at::text, updated_at::text
        """
        params = (status, pr_number, repository, issue_id, agent_branch)
        with self._connect() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(query, params)
            row = cur.fetchone()
            conn.commit()
        return BranchRecord.model_validate(row) if row else None

    def _connect(self):
        return psycopg.connect(self.database_url)
