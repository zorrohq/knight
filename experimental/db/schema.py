from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    JSON,
    Column,
    DateTime,
    Enum,
    Integer,
    Index,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    text,
)


metadata = MetaData()

agent_branches_table = Table(
    "agent_branches",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("repository", String(255), nullable=False),
    Column("issue_id", String(255), nullable=False),
    Column("base_branch", String(255), nullable=False),
    Column("agent_branch", String(255), nullable=False),
    Column("pr_number", Integer, nullable=True),
    Column("provider", String(100), nullable=False),
    Column("status", String(50), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        "status IN ('open', 'pushed', 'merged', 'closed', 'failed')",
        name="agent_branches_status_check",
    ),
    UniqueConstraint(
        "repository",
        "issue_id",
        "agent_branch",
        name="agent_branches_repo_issue_branch_unique",
    ),
)

Index(
    "agent_branches_repo_issue_status_idx",
    agent_branches_table.c.repository,
    agent_branches_table.c.issue_id,
    agent_branches_table.c.status,
)
Index(
    "agent_branches_agent_branch_idx",
    agent_branches_table.c.agent_branch,
)

app_config_table = Table(
    "app_config",
    metadata,
    Column("id", Integer, primary_key=True),
    Column(
        "scope",
        Enum("global", "repository", name="app_config_scope", native_enum=True),
        nullable=False,
    ),
    Column("repository", String(255), nullable=True),
    Column("key", String(255), nullable=False),
    Column("value", JSON, nullable=False),
    Column("description", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        "(scope = 'repository' AND repository IS NOT NULL) OR (scope <> 'repository' AND repository IS NULL)",
        name="app_config_scope_repository_check",
    ),
    UniqueConstraint(
        "scope",
        "repository",
        "key",
        name="app_config_scope_key_repository_unique",
    ),
)

Index(
    "app_config_scope_key_idx",
    app_config_table.c.scope,
    app_config_table.c.key,
)
Index(
    "app_config_repository_key_idx",
    app_config_table.c.repository,
    app_config_table.c.key,
)

agent_sessions_table = Table(
    "agent_sessions",
    metadata,
    Column("issue_id", String(255), primary_key=True),
    Column("session_file_name", String(255), nullable=False),
    Column("session_data", Text, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)
