from __future__ import annotations

from pathlib import Path
import subprocess


class WorkspacePathError(ValueError):
    """Raised when a path escapes the workspace root."""


class LocalWorkspace:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    def resolve_path(self, path: str | Path = ".") -> Path:
        candidate = (self.root / path).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise WorkspacePathError(f"path escapes workspace root: {path}")
        return candidate

    def list_files(self, path: str = ".", recursive: bool = True) -> list[str]:
        base_path = self.resolve_path(path)
        if not base_path.exists():
            return []

        iterator = base_path.rglob("*") if recursive else base_path.glob("*")
        return sorted(
            str(item.relative_to(self.root))
            for item in iterator
            if item.is_file()
        )

    def read_file(self, path: str, start_line: int = 1, end_line: int | None = None) -> str:
        file_path = self.resolve_path(path)
        lines = file_path.read_text(encoding="utf-8").splitlines()
        start_index = max(start_line - 1, 0)
        end_index = end_line if end_line is not None else len(lines)
        return "\n".join(lines[start_index:end_index])

    def write_file(self, path: str, content: str) -> None:
        file_path = self.resolve_path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")

    def replace_in_file(
        self,
        path: str,
        old_text: str,
        new_text: str,
        *,
        replace_all: bool = False,
    ) -> int:
        file_path = self.resolve_path(path)
        original = file_path.read_text(encoding="utf-8")
        if old_text not in original:
            return 0

        if replace_all:
            updated = original.replace(old_text, new_text)
            replacements = original.count(old_text)
        else:
            updated = original.replace(old_text, new_text, 1)
            replacements = 1

        file_path.write_text(updated, encoding="utf-8")
        return replacements

    def search_files(self, pattern: str, path: str = ".") -> str:
        search_root = self.resolve_path(path)
        completed = subprocess.run(
            ["rg", "-n", pattern, "."],
            check=False,
            capture_output=True,
            text=True,
            cwd=search_root,
        )
        if completed.returncode not in {0, 1}:
            raise RuntimeError(completed.stderr.strip() or "search command failed")
        return completed.stdout.strip()
