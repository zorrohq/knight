from __future__ import annotations

from sqlalchemy import text

from knight.utils.db.backend import create_store_backend
from knight.utils.db.engine import create_database_engine, infer_database_backend
from knight.utils.db.schema import metadata


DEFAULT_APP_CONFIG: list[dict[str, object]] = [
    {
        "key": "logging_level",
        "value": "INFO",
        "description": "Root application log level.",
    },
    {
        "key": "logging_format",
        "value": "json",
        "description": "Log formatter type. Allowed values: text, json.",
    },
    {
        "key": "logging_include_timestamp",
        "value": True,
        "description": "Whether log lines include timestamps.",
    },
    {
        "key": "logging_include_logger_name",
        "value": True,
        "description": "Whether log lines include the logger name.",
    },
    {
        "key": "logging_include_process",
        "value": True,
        "description": "Whether log lines include the process id.",
    },
    {
        "key": "logging_log_tool_results",
        "value": True,
        "description": "Whether agent tool execution summaries are emitted to logs.",
    },
    {
        "key": "logging_log_command_output",
        "value": False,
        "description": "Whether command stdout and stderr are included in logs.",
    },
    {
        "key": "agent_provider",
        "value": "openai",
        "description": "Model provider. Allowed values: openai, anthropic, google-genai.",
    },
    {
        "key": "agent_model_default",
        "value": "gpt-4o-mini",
        "description": "Default model. Used when no tier-specific model is configured.",
    },
    {
        "key": "agent_model_high",
        "value": "gpt-5.3-codex",
        "description": "High-tier model for coding tasks. Falls back to agent_model_default if unset.",
    },
    {
        "key": "agent_model_low",
        "value": "gpt-4o-mini",
        "description": "Low-tier model for lightweight tasks (commit messages, changelogs). Falls back to agent_model_default if unset.",
    },
    {
        "key": "agent_temperature",
        "value": 0.0,
        "description": "Sampling temperature used by the coding agent.",
    },
    {
        "key": "agent_max_steps",
        "value": 25,
        "description": "Maximum number of model/tool iterations for the coding agent.",
    },
    {
        "key": "agent_command_timeout_seconds",
        "value": 300,
        "description": "Maximum shell command runtime for the coding agent.",
    },
    {
        "key": "agent_max_command_output_chars",
        "value": 12000,
        "description": "Maximum stdout/stderr characters captured from agent-run shell commands.",
    },
    {
        "key": "agent_blocked_command_prefixes",
        "value": ["rm", "sudo", "shutdown", "reboot", "mkfs", "dd"],
        "description": "Command prefixes blocked by the sandbox policy.",
    },
    {
        "key": "agent_allow_run_command",
        "value": True,
        "description": "Whether the agent can call the run_command tool.",
    },
    {
        "key": "agent_allow_write_files",
        "value": True,
        "description": "Whether the agent can call write and replace file tools.",
    },
    {
        "key": "agent_system_prompt",
        "value": (
            "You are Knight, an autonomous software engineering agent. "
            "Work iteratively: inspect the repository, read files before editing, "
            "prefer targeted edits over broad rewrites, run commands when needed, "
            "and stop once the task is complete. "
            "Use the available tools to list files, read files, write files, replace "
            "text in files, inspect git status/diff, and run safe shell commands."
        ),
        "description": "System prompt used by the coding agent.",
    },
]


def initialize_database(database_url: str) -> None:
    engine = create_database_engine(database_url)
    metadata.create_all(engine)
    with engine.begin() as conn:
        for table in reversed(metadata.sorted_tables):
            conn.execute(table.delete())
    backend = create_store_backend(database_url)
    for item in DEFAULT_APP_CONFIG:
        backend.upsert_config_value(
            key=str(item["key"]),
            value=item["value"],
            scope="global",
            repository=None,
            description=str(item["description"]),
        )


def drop_database_schema(database_url: str) -> None:
    engine = create_database_engine(database_url)
    metadata.drop_all(engine)
    if infer_database_backend(database_url) == "postgres":
        with engine.begin() as conn:
            conn.execute(text("DROP TYPE IF EXISTS app_config_scope"))
