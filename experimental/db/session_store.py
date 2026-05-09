from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError

from knight.utils.db.engine import create_database_engine
from knight.utils.db.schema import agent_sessions_table
from knight.worker.config import settings

logger = logging.getLogger(__name__)

# Sessions larger than this are trimmed to the most recent lines before saving.
# Pi's auto-compaction should keep sessions well under this, but it's a hard
# safety net against unbounded DB growth.
_MAX_SESSION_BYTES = 5 * 1024 * 1024  # 5 MB


def _trim_session(data: str, max_bytes: int) -> str:
    """Return the most recent JSONL lines of data that fit within max_bytes."""
    if len(data.encode()) <= max_bytes:
        return data
    lines = data.splitlines(keepends=True)
    kept: list[str] = []
    size = 0
    for line in reversed(lines):
        line_bytes = len(line.encode())
        if size + line_bytes > max_bytes:
            break
        kept.append(line)
        size += line_bytes
    result = "".join(reversed(kept))
    logger.warning(
        "session data exceeded %d MB, trimmed from %d to %d lines",
        max_bytes // (1024 * 1024),
        len(lines),
        len(kept),
    )
    return result


class AgentSessionStore:
    def __init__(self, database_url: str | None = None) -> None:
        url = database_url or settings.database_url
        if not url:
            raise ValueError("DATABASE_URL must be configured")
        self.engine = create_database_engine(url)

    def load(self, issue_id: str) -> tuple[str, str] | None:
        """Return (session_file_name, session_data) or None if no session exists."""
        statement = (
            select(
                agent_sessions_table.c.session_file_name,
                agent_sessions_table.c.session_data,
            )
            .where(agent_sessions_table.c.issue_id == issue_id)
            .limit(1)
        )
        try:
            with self.engine.connect() as conn:
                row = conn.execute(statement).first()
            if row:
                return row[0], row[1]
        except Exception:
            logger.warning("failed to load session for %s", issue_id, exc_info=True)
        return None

    def save(self, issue_id: str, session_file_name: str, session_data: str) -> None:
        """Upsert session data for this issue, trimming if it exceeds the size limit."""
        session_data = _trim_session(session_data, _MAX_SESSION_BYTES)
        now = datetime.now(UTC)
        try:
            with self.engine.begin() as conn:
                result = conn.execute(
                    update(agent_sessions_table)
                    .where(agent_sessions_table.c.issue_id == issue_id)
                    .values(
                        session_file_name=session_file_name,
                        session_data=session_data,
                        updated_at=now,
                    )
                )
                if result.rowcount == 0:
                    try:
                        conn.execute(
                            insert(agent_sessions_table).values(
                                issue_id=issue_id,
                                session_file_name=session_file_name,
                                session_data=session_data,
                                updated_at=now,
                            )
                        )
                    except IntegrityError:
                        # Lost a concurrent insert race — the other writer's row is fine.
                        pass
        except Exception:
            logger.warning("failed to save session for %s", issue_id, exc_info=True)
