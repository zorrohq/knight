from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import and_, desc, insert, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from knight.utils.db.engine import create_database_engine
from knight.utils.db.schema import agent_branches_table, app_config_table


class StoreBackend(Protocol):
    def get_open_branch(self, *, repository: str, issue_id: str) -> dict[str, object] | None: ...

    def upsert_branch(self, record: Mapping[str, object]) -> dict[str, object]: ...

    def mark_branch_status(
        self,
        *,
        repository: str,
        issue_id: str,
        agent_branch: str,
        status: str,
        pr_number: int | None = None,
    ) -> dict[str, object] | None: ...

    def get_config_value(
        self,
        *,
        key: str,
        scope: str,
        repository: str | None = None,
    ) -> object | None: ...

    def upsert_config_value(
        self,
        *,
        key: str,
        value: object,
        scope: str,
        repository: str | None = None,
        description: str | None = None,
    ) -> None: ...


def create_store_backend(database_url: str) -> StoreBackend:
    return SqlAlchemyStoreBackend(create_database_engine(database_url))


class SqlAlchemyStoreBackend:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def get_open_branch(self, *, repository: str, issue_id: str) -> dict[str, object] | None:
        statement = (
            select(agent_branches_table)
            .where(
                and_(
                    agent_branches_table.c.repository == repository,
                    agent_branches_table.c.issue_id == issue_id,
                    agent_branches_table.c.status == "open",
                )
            )
            .order_by(desc(agent_branches_table.c.updated_at))
            .limit(1)
        )
        with self.engine.connect() as conn:
            row = conn.execute(statement).mappings().first()
        return self._serialize_row(row) if row else None

    def upsert_branch(self, record: Mapping[str, object]) -> dict[str, object]:
        now = datetime.now(UTC)
        branch_filter = and_(
            agent_branches_table.c.repository == record["repository"],
            agent_branches_table.c.issue_id == record["issue_id"],
            agent_branches_table.c.agent_branch == record["agent_branch"],
        )
        update_values = {
            "repository": record["repository"],
            "issue_id": record["issue_id"],
            "base_branch": record["base_branch"],
            "agent_branch": record["agent_branch"],
            "pr_number": record.get("pr_number"),
            "provider": record.get("provider", "github"),
            "status": record.get("status", "open"),
            "updated_at": now,
        }
        with self.engine.begin() as conn:
            result = conn.execute(
                update(agent_branches_table).where(branch_filter).values(**update_values)
            )
            if result.rowcount == 0:
                try:
                    conn.execute(
                        insert(agent_branches_table).values(**update_values, created_at=now)
                    )
                except IntegrityError:
                    # Lost a concurrent insert race — row was created by another writer.
                    conn.execute(
                        update(agent_branches_table).where(branch_filter).values(**update_values)
                    )
            row = conn.execute(
                select(agent_branches_table).where(branch_filter).limit(1)
            ).mappings().one()
        return self._serialize_row(row)

    def mark_branch_status(
        self,
        *,
        repository: str,
        issue_id: str,
        agent_branch: str,
        status: str,
        pr_number: int | None = None,
    ) -> dict[str, object] | None:
        branch_filter = and_(
            agent_branches_table.c.repository == repository,
            agent_branches_table.c.issue_id == issue_id,
            agent_branches_table.c.agent_branch == agent_branch,
        )
        with self.engine.begin() as conn:
            existing = conn.execute(
                select(agent_branches_table.c.pr_number).where(branch_filter).limit(1)
            ).mappings().first()
            if not existing:
                return None
            conn.execute(
                update(agent_branches_table)
                .where(branch_filter)
                .values(
                    status=status,
                    pr_number=pr_number if pr_number is not None else existing["pr_number"],
                    updated_at=datetime.now(UTC),
                )
            )
            row = conn.execute(select(agent_branches_table).where(branch_filter).limit(1)).mappings().one()
        return self._serialize_row(row)

    def get_config_value(
        self,
        *,
        key: str,
        scope: str,
        repository: str | None = None,
    ) -> object | None:
        statement = (
            select(app_config_table.c.value)
            .where(
                and_(
                    app_config_table.c.scope == scope,
                    app_config_table.c.key == key,
                    app_config_table.c.repository.is_not_distinct_from(repository),
                )
            )
            .limit(1)
        )
        with self.engine.connect() as conn:
            row = conn.execute(statement).first()
        return row[0] if row else None

    def upsert_config_value(
        self,
        *,
        key: str,
        value: object,
        scope: str,
        repository: str | None = None,
        description: str | None = None,
    ) -> None:
        now = datetime.now(UTC)
        config_filter = and_(
            app_config_table.c.scope == scope,
            app_config_table.c.key == key,
            app_config_table.c.repository.is_not_distinct_from(repository),
        )
        update_values = {
            "scope": scope,
            "repository": repository,
            "key": key,
            "value": value,
            "description": description,
            "updated_at": now,
        }
        with self.engine.begin() as conn:
            # Preserve existing description when the caller passes None.
            existing_desc = None
            if description is None:
                row = conn.execute(
                    select(app_config_table.c.description).where(config_filter).limit(1)
                ).mappings().first()
                existing_desc = row["description"] if row else None
            resolved_description = description if description is not None else existing_desc
            result = conn.execute(
                update(app_config_table)
                .where(config_filter)
                .values(**update_values, description=resolved_description)
            )
            if result.rowcount == 0:
                try:
                    conn.execute(
                        insert(app_config_table).values(**update_values, created_at=now)
                    )
                except IntegrityError:
                    # Lost a concurrent insert race — safe to ignore.
                    pass

    def _serialize_row(self, row: Mapping[str, Any]) -> dict[str, object]:
        output: dict[str, object] = {}
        for key, value in row.items():
            if hasattr(value, "isoformat"):
                output[key] = value.isoformat()
            else:
                output[key] = value
        return output
