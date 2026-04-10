from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path

from pydantic import BaseModel, Field

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
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path or settings.worker_state_store_path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def get_open_branch(
        self,
        *,
        repository: str,
        issue_id: str,
    ) -> BranchRecord | None:
        records = self._load()
        for record in records:
            if (
                record.repository == repository
                and record.issue_id == issue_id
                and record.status == "open"
            ):
                return record
        return None

    def upsert_branch(self, record: BranchRecord) -> BranchRecord:
        records = self._load()
        updated_records: list[BranchRecord] = []
        replaced = False

        for existing in records:
            if (
                existing.repository == record.repository
                and existing.issue_id == record.issue_id
                and existing.agent_branch == record.agent_branch
            ):
                updated_records.append(
                    record.model_copy(
                        update={
                            "created_at": existing.created_at,
                            "updated_at": _utc_now(),
                        }
                    )
                )
                replaced = True
            else:
                updated_records.append(existing)

        if not replaced:
            updated_records.append(record.model_copy(update={"updated_at": _utc_now()}))

        self._save(updated_records)
        return updated_records[-1] if not replaced else next(
            item
            for item in updated_records
            if item.repository == record.repository
            and item.issue_id == record.issue_id
            and item.agent_branch == record.agent_branch
        )

    def mark_branch_status(
        self,
        *,
        repository: str,
        issue_id: str,
        agent_branch: str,
        status: str,
        pr_number: int | None = None,
    ) -> BranchRecord | None:
        records = self._load()
        updated_records: list[BranchRecord] = []
        matched: BranchRecord | None = None

        for existing in records:
            if (
                existing.repository == repository
                and existing.issue_id == issue_id
                and existing.agent_branch == agent_branch
            ):
                matched = existing.model_copy(
                    update={
                        "status": status,
                        "pr_number": pr_number if pr_number is not None else existing.pr_number,
                        "updated_at": _utc_now(),
                    }
                )
                updated_records.append(matched)
            else:
                updated_records.append(existing)

        self._save(updated_records)
        return matched

    def _load(self) -> list[BranchRecord]:
        if not self.path.exists():
            return []

        payload = json.loads(self.path.read_text(encoding="utf-8"))
        return [BranchRecord.model_validate(item) for item in payload]

    def _save(self, records: list[BranchRecord]) -> None:
        self.path.write_text(
            json.dumps([record.model_dump() for record in records], indent=2),
            encoding="utf-8",
        )
