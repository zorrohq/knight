"""File-based config store backed by config.json.

config.json structure:
{
  "provider": "openai",
  "model_default": "gpt-5-mini-2025-08-07",
  "model_high": "gpt-5-mini-2025-08-07",
  "model_low": "gpt-5-mini-2025-08-07",
  "temperature": 0.0,
  "max_steps": 25,
  "command_timeout_seconds": 300,
  "max_command_output_chars": 12000,
  "blocked_command_prefixes": ["rm", "sudo", "shutdown", "reboot", "mkfs", "dd"],
  "repositories": {
    "owner/repo": {
      "model_high": "gpt-5.3-codex"
    }
  }
}
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Maps internal key names (used by AgentConfigResolver) to config.json field names.
_KEY_MAP: dict[str, str] = {
    "agent_provider": "provider",
    "agent_model_default": "model_default",
    "agent_model_high": "model_high",
    "agent_model_low": "model_low",
    "agent_temperature": "temperature",
    "agent_max_steps": "max_steps",
    "agent_command_timeout_seconds": "command_timeout_seconds",
    "agent_max_command_output_chars": "max_command_output_chars",
    "agent_blocked_command_prefixes": "blocked_command_prefixes",
}


class ConfigStore:
    def __init__(self, config_path: str | Path | None = None) -> None:
        from knight.worker.config import settings
        path = Path(config_path or settings.config_path).expanduser()
        self._config: dict = {}
        if path.is_file():
            try:
                self._config = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                logger.warning("failed to load config.json from %s", path, exc_info=True)
        else:
            logger.warning("config.json not found at %s — using env defaults", path)

    def _resolve(self, key: str, repository: str | None) -> object | None:
        field = _KEY_MAP.get(key, key)
        if repository:
            repo_cfg = (self._config.get("repositories") or {}).get(repository) or {}
            if field in repo_cfg:
                return repo_cfg[field]
        return self._config.get(field)

    def get_string(self, *, key: str, repository: str | None = None, default: str = "") -> str:
        v = self._resolve(key, repository)
        return v if isinstance(v, str) else default

    def get_bool(self, *, key: str, repository: str | None = None, default: bool = False) -> bool:
        v = self._resolve(key, repository)
        return v if isinstance(v, bool) else default

    def get_int(self, *, key: str, repository: str | None = None, default: int = 0) -> int:
        v = self._resolve(key, repository)
        return v if isinstance(v, int) and not isinstance(v, bool) else default

    def get_float(self, *, key: str, repository: str | None = None, default: float = 0.0) -> float:
        v = self._resolve(key, repository)
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else default

    def get_string_list(
        self, *, key: str, repository: str | None = None, default: list[str] | None = None
    ) -> list[str]:
        v = self._resolve(key, repository)
        if isinstance(v, list) and all(isinstance(i, str) for i in v):
            return v
        return list(default or [])
