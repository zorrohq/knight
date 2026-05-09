from __future__ import annotations

from knight.worker.config import settings
from knight.utils.db.backend import create_store_backend


class ConfigStore:
    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url or settings.database_url
        if not self.database_url:
            raise ValueError("DATABASE_URL must be configured")
        self.backend = create_store_backend(self.database_url)

    def get_value(
        self,
        *,
        key: str,
        scope: str = "global",
        repository: str | None = None,
    ) -> object | None:
        return self.backend.get_config_value(
            key=key,
            scope=scope,
            repository=repository,
        )

    def get_effective_value(
        self,
        *,
        key: str,
        repository: str | None = None,
    ) -> object | None:
        if repository:
            value = self.get_value(
                key=key,
                scope="repository",
                repository=repository,
            )
            if value is not None:
                return value

        return self.get_value(key=key, scope="global", repository=None)

    def get_string(
        self,
        *,
        key: str,
        repository: str | None = None,
        default: str = "",
    ) -> str:
        value = self.get_effective_value(key=key, repository=repository)
        return value if isinstance(value, str) else default

    def get_bool(
        self,
        *,
        key: str,
        repository: str | None = None,
        default: bool = False,
    ) -> bool:
        value = self.get_effective_value(key=key, repository=repository)
        return value if isinstance(value, bool) else default

    def get_int(
        self,
        *,
        key: str,
        repository: str | None = None,
        default: int = 0,
    ) -> int:
        value = self.get_effective_value(key=key, repository=repository)
        return value if isinstance(value, int) and not isinstance(value, bool) else default

    def get_float(
        self,
        *,
        key: str,
        repository: str | None = None,
        default: float = 0.0,
    ) -> float:
        value = self.get_effective_value(key=key, repository=repository)
        return (
            float(value)
            if isinstance(value, int | float) and not isinstance(value, bool)
            else default
        )

    def get_string_list(
        self,
        *,
        key: str,
        repository: str | None = None,
        default: list[str] | None = None,
    ) -> list[str]:
        value = self.get_effective_value(key=key, repository=repository)
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
        self.backend.upsert_config_value(
            key=key,
            value=value,
            scope=scope,
            repository=repository,
            description=description,
        )
