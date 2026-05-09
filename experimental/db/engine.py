from __future__ import annotations

from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url


SUPPORTED_BACKENDS = {"postgres", "mysql", "mssql"}


def infer_database_backend(database_url: str) -> str:
    driver_name = make_url(database_url).drivername.lower()
    if driver_name.startswith("postgresql") or driver_name.startswith("postgres"):
        return "postgres"
    if driver_name.startswith("mysql"):
        return "mysql"
    if driver_name.startswith("mssql") or driver_name.startswith("sqlserver"):
        return "mssql"
    raise ValueError(
        "unsupported database backend; expected a Postgres, MySQL, or SQL Server URL"
    )


def normalize_database_url(database_url: str) -> str:
    url = make_url(database_url)
    if url.drivername == "postgres":
        url = url.set(drivername="postgresql+psycopg")
    elif url.drivername == "postgresql":
        url = url.set(drivername="postgresql+psycopg")
    elif url.drivername == "mysql":
        url = url.set(drivername="mysql+pymysql")
    elif url.drivername == "sqlserver":
        url = url.set(drivername="mssql+pytds")
    return url.render_as_string(hide_password=False)


@lru_cache(maxsize=8)
def create_database_engine(database_url: str) -> Engine:
    infer_database_backend(database_url)
    normalized = normalize_database_url(database_url)
    return create_engine(
        normalized,
        future=True,
        pool_pre_ping=True,
    )
