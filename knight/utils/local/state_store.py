"""SQLite-backed branch state store.

Uses Python's stdlib sqlite3 with WAL mode for safe concurrent access.
The database lives at <data_dir>/state.db and is created automatically.
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field


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


_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS agent_branches (
    repository   TEXT NOT NULL,
    issue_id     TEXT NOT NULL,
    base_branch  TEXT NOT NULL,
    agent_branch TEXT NOT NULL,
    pr_number    INTEGER,
    provider     TEXT NOT NULL DEFAULT 'github',
    status       TEXT NOT NULL DEFAULT 'open',
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    PRIMARY KEY (repository, issue_id, agent_branch)
)
"""


class BranchStateStore:
    def __init__(self, data_dir: str | Path | None = None) -> None:
        from knight.worker.config import settings
        db_path = Path(data_dir or settings.knight_data_dir).expanduser() / "state.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = str(db_path)
        self._lock = threading.Lock()
        with self._lock:
            with self._conn() as conn:
                conn.execute(_CREATE_TABLE)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def get_open_branch(self, *, repository: str, issue_id: str) -> BranchRecord | None:
        with self._lock, self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM agent_branches "
                "WHERE repository=? AND issue_id=? AND status='open' "
                "ORDER BY updated_at DESC LIMIT 1",
                (repository, issue_id),
            ).fetchone()
        return BranchRecord(**dict(row)) if row else None

    def upsert_branch(self, record: BranchRecord) -> BranchRecord:
        now = _utc_now()
        with self._lock, self._conn() as conn:
            conn.execute(
                """
                INSERT INTO agent_branches
                    (repository, issue_id, base_branch, agent_branch,
                     pr_number, provider, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(repository, issue_id, agent_branch) DO UPDATE SET
                    base_branch = excluded.base_branch,
                    pr_number   = excluded.pr_number,
                    provider    = excluded.provider,
                    status      = excluded.status,
                    updated_at  = excluded.updated_at
                """,
                (
                    record.repository, record.issue_id, record.base_branch,
                    record.agent_branch, record.pr_number, record.provider,
                    record.status, record.created_at or now, now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM agent_branches "
                "WHERE repository=? AND issue_id=? AND agent_branch=?",
                (record.repository, record.issue_id, record.agent_branch),
            ).fetchone()
        return BranchRecord(**dict(row))

    def mark_branch_status(
        self,
        *,
        repository: str,
        issue_id: str,
        agent_branch: str,
        status: str,
        pr_number: int | None = None,
    ) -> BranchRecord | None:
        with self._lock, self._conn() as conn:
            existing = conn.execute(
                "SELECT pr_number FROM agent_branches "
                "WHERE repository=? AND issue_id=? AND agent_branch=?",
                (repository, issue_id, agent_branch),
            ).fetchone()
            if not existing:
                return None
            resolved_pr = pr_number if pr_number is not None else existing["pr_number"]
            conn.execute(
                "UPDATE agent_branches SET status=?, pr_number=?, updated_at=? "
                "WHERE repository=? AND issue_id=? AND agent_branch=?",
                (status, resolved_pr, _utc_now(), repository, issue_id, agent_branch),
            )
            row = conn.execute(
                "SELECT * FROM agent_branches "
                "WHERE repository=? AND issue_id=? AND agent_branch=?",
                (repository, issue_id, agent_branch),
            ).fetchone()
        return BranchRecord(**dict(row)) if row else None
