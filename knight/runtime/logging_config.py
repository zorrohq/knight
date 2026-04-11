from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import sys
from typing import Any

from knight.utils.db.config_store import ConfigStore


@dataclass(slots=True)
class ResolvedLoggingSettings:
    level: str
    format: str
    include_timestamp: bool
    include_logger_name: bool
    include_process: bool
    log_tool_results: bool
    log_command_output: bool


class JsonLogFormatter(logging.Formatter):
    def __init__(
        self,
        *,
        include_timestamp: bool,
        include_logger_name: bool,
        include_process: bool,
    ) -> None:
        super().__init__()
        self.include_timestamp = include_timestamp
        self.include_logger_name = include_logger_name
        self.include_process = include_process

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "message": record.getMessage(),
        }
        if self.include_timestamp:
            payload["timestamp"] = self.formatTime(record, self.datefmt)
        if self.include_logger_name:
            payload["logger"] = record.name
        if self.include_process:
            payload["process"] = record.process

        for key, value in record.__dict__.items():
            if key.startswith("_") or key in _RESERVED_LOG_RECORD_KEYS:
                continue
            payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=True)


class LoggingConfigResolver:
    def __init__(self) -> None:
        self.store = ConfigStore()

    def resolve(self) -> ResolvedLoggingSettings:
        return ResolvedLoggingSettings(
            level=self.store.get_string(key="logging_level", default="INFO"),
            format=self.store.get_string(key="logging_format", default="text"),
            include_timestamp=self.store.get_bool(
                key="logging_include_timestamp",
                default=True,
            ),
            include_logger_name=self.store.get_bool(
                key="logging_include_logger_name",
                default=True,
            ),
            include_process=self.store.get_bool(
                key="logging_include_process",
                default=True,
            ),
            log_tool_results=self.store.get_bool(
                key="logging_log_tool_results",
                default=True,
            ),
            log_command_output=self.store.get_bool(
                key="logging_log_command_output",
                default=False,
            ),
        )


_LOGGING_CONFIGURED = False
_RESERVED_LOG_RECORD_KEYS = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "module",
    "msecs",
    "message",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
}


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def setup_logging() -> ResolvedLoggingSettings:
    global _LOGGING_CONFIGURED

    try:
        resolved = LoggingConfigResolver().resolve()
    except Exception as exc:
        print(
            f"[knight] logging config unavailable, using defaults: {exc}",
            file=sys.stderr,
        )
        resolved = ResolvedLoggingSettings(
            level="INFO",
            format="text",
            include_timestamp=True,
            include_logger_name=True,
            include_process=True,
            log_tool_results=True,
            log_command_output=False,
        )
    if _LOGGING_CONFIGURED:
        logging.getLogger().setLevel(_coerce_log_level(resolved.level))
        return resolved

    handler = logging.StreamHandler()
    handler.setFormatter(_build_formatter(resolved))

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(_coerce_log_level(resolved.level))
    _LOGGING_CONFIGURED = True
    return resolved


def _build_formatter(resolved: ResolvedLoggingSettings) -> logging.Formatter:
    if resolved.format.lower() == "json":
        return JsonLogFormatter(
            include_timestamp=resolved.include_timestamp,
            include_logger_name=resolved.include_logger_name,
            include_process=resolved.include_process,
        )

    parts: list[str] = []
    if resolved.include_timestamp:
        parts.append("%(asctime)s")
    parts.append("%(levelname)s")
    if resolved.include_logger_name:
        parts.append("%(name)s")
    if resolved.include_process:
        parts.append("pid=%(process)d")
    parts.append("%(message)s")
    return logging.Formatter(" ".join(parts))


def _coerce_log_level(value: str) -> int:
    level = getattr(logging, value.upper(), None)
    return level if isinstance(level, int) else logging.INFO
