from __future__ import annotations

from pathlib import Path
import re
import subprocess


def normalize_repository_identity(
    *,
    repository_url: str = "",
    repository_local_path: str = "",
) -> str:
    parsed = _parse_repository_identity(repository_url)
    if parsed:
        return parsed

    if repository_local_path:
        source_path = Path(repository_local_path).resolve()
        remote_url = _get_origin_remote_url(source_path)
        parsed_remote = _parse_repository_identity(remote_url)
        if parsed_remote:
            return parsed_remote
        return f"local/{source_path.name}"

    return ""


def repository_key(
    *,
    repository_url: str = "",
    repository_local_path: str = "",
) -> str:
    identity = normalize_repository_identity(
        repository_url=repository_url,
        repository_local_path=repository_local_path,
    )
    if identity:
        return _slugify(identity.replace("/", "-"))
    return "default"


def _parse_repository_identity(value: str) -> str:
    candidate = value.strip()
    if not candidate:
        return ""

    candidate = candidate.removesuffix(".git").rstrip("/")
    if candidate.startswith("git@"):
        _, _, repo_path = candidate.partition(":")
        return _last_two_segments(repo_path)

    candidate = re.sub(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", "", candidate)
    path = candidate.split("/", 1)[1] if "/" in candidate else ""
    return _last_two_segments(path)


def _last_two_segments(path: str) -> str:
    parts = [part for part in path.split("/") if part]
    if len(parts) >= 2:
        return f"{parts[-2]}/{parts[-1]}"
    return ""


def _get_origin_remote_url(source_path: Path) -> str:
    completed = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=source_path,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def _slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip())
    return cleaned.strip("-._") or "default"
