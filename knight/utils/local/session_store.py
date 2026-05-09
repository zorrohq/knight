"""File-based pi agent session store.

Sessions are stored as JSONL files in <data_dir>/sessions/<slug>.jsonl.
The slug is derived from the issue_id by replacing path separators with
underscores so it is safe to use as a filename.
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

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


def _slug(issue_id: str) -> str:
    return issue_id.replace("/", "_").replace("#", "_").replace(":", "_")


class AgentSessionStore:
    def __init__(self, data_dir: str | Path | None = None) -> None:
        from knight.worker.config import settings
        self._sessions_dir = Path(data_dir or settings.knight_data_dir).expanduser() / "sessions"
        self._sessions_dir.mkdir(parents=True, exist_ok=True)

    def load(self, issue_id: str) -> tuple[str, str] | None:
        """Return (session_file_name, session_data) or None if no session exists."""
        path = self._sessions_dir / f"{_slug(issue_id)}.jsonl"
        try:
            if path.is_file():
                return path.name, path.read_text(encoding="utf-8")
        except OSError:
            logger.warning("failed to load session for %s", issue_id, exc_info=True)
        return None

    def save(self, issue_id: str, session_file_name: str, session_data: str) -> None:
        """Persist session data for this issue, trimming if it exceeds the size cap."""
        session_data = _trim_session(session_data, _MAX_SESSION_BYTES)
        path = self._sessions_dir / f"{_slug(issue_id)}.jsonl"
        try:
            path.write_text(session_data, encoding="utf-8")
        except OSError:
            logger.warning("failed to save session for %s", issue_id, exc_info=True)
