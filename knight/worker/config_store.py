from __future__ import annotations

import json

import psycopg
from psycopg.rows import dict_row

from knight.worker.config import settings


class ConfigStore:
    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url or settings.database_url
        if not self.database_url:
            raise ValueError("DATABASE_URL must be configured")

    def get_value(
        self,
        *,
        key: str,
        scope: str = "global",
        repository: str | None = None,
    ) -> object | None:
        query = """
            SELECT value
            FROM app_config
            WHERE scope = %s
              AND key = %s
              AND repository IS NOT DISTINCT FROM %s
            LIMIT 1
        """
        with self._connect() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(query, (scope, key, repository))
            row = cur.fetchone()
        return row["value"] if row else None

    def get_string(
        self,
        *,
        key: str,
        scope: str = "global",
        repository: str | None = None,
        default: str = "",
    ) -> str:
        value = self.get_value(key=key, scope=scope, repository=repository)
        return value if isinstance(value, str) else default

    def get_bool(
        self,
        *,
        key: str,
        scope: str = "global",
        repository: str | None = None,
        default: bool = False,
    ) -> bool:
        value = self.get_value(key=key, scope=scope, repository=repository)
        return value if isinstance(value, bool) else default

    def get_int(
        self,
        *,
        key: str,
        scope: str = "global",
        repository: str | None = None,
        default: int = 0,
    ) -> int:
        value = self.get_value(key=key, scope=scope, repository=repository)
        return value if isinstance(value, int) and not isinstance(value, bool) else default

    def get_float(
        self,
        *,
        key: str,
        scope: str = "global",
        repository: str | None = None,
        default: float = 0.0,
    ) -> float:
        value = self.get_value(key=key, scope=scope, repository=repository)
        return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else default

    def get_string_list(
        self,
        *,
        key: str,
        scope: str = "global",
        repository: str | None = None,
        default: list[str] | None = None,
    ) -> list[str]:
        value = self.get_value(key=key, scope=scope, repository=repository)
        if isinstance(value, list) and all(isinstance(item, str) for item in value):
            return value
        return list(default or [])

    def upsert_value(
        self,
        *,
        key: str,
        value: object,
        scope: str = "global",
        repository: str | None = None,
        description: str | None = None,
    ) -> None:
        query = """
            INSERT INTO app_config (scope, repository, key, value, description)
            VALUES (%s, %s, %s, %s::jsonb, %s)
            ON CONFLICT (scope, key, repository)
            DO UPDATE SET
                value = EXCLUDED.value,
                description = COALESCE(EXCLUDED.description, app_config.description),
                updated_at = NOW()
        """
        encoded_value = json.dumps(value, ensure_ascii=True)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(query, (scope, repository, key, encoded_value, description))
            conn.commit()

    def _connect(self):
        return psycopg.connect(self.database_url)
