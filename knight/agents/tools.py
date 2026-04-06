from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from knight.agents.config import settings
from knight.runtime.command_runner import LocalCommandRunner
from knight.runtime.filesystem import LocalWorkspace


class ListFilesInput(BaseModel):
    path: str = "."
    recursive: bool = True


class ReadFileInput(BaseModel):
    path: str
    start_line: int = 1
    end_line: int | None = None


class WriteFileInput(BaseModel):
    path: str
    content: str = ""


class ReplaceInFileInput(BaseModel):
    path: str
    old_text: str
    new_text: str = ""
    replace_all: bool = False


class SearchFilesInput(BaseModel):
    pattern: str
    path: str = "."


class RunCommandInput(BaseModel):
    command: str
    cwd: str = "."
    timeout_seconds: int = Field(default=settings.agent_command_timeout_seconds)


class AgentToolset:
    def __init__(
        self,
        workspace: LocalWorkspace,
        command_runner: LocalCommandRunner,
    ) -> None:
        self.workspace = workspace
        self.command_runner = command_runner

    def list_files(self, path: str = ".", recursive: bool = True) -> dict[str, Any]:
        return {"files": self.workspace.list_files(path=path, recursive=recursive)}

    def read_file(
        self,
        path: str,
        start_line: int = 1,
        end_line: int | None = None,
    ) -> dict[str, Any]:
        return {
            "content": self.workspace.read_file(
                path=path,
                start_line=start_line,
                end_line=end_line,
            )
        }

    def write_file(self, path: str, content: str = "") -> dict[str, Any]:
        self.workspace.write_file(path=path, content=content)
        return {"path": path}

    def replace_in_file(
        self,
        path: str,
        old_text: str,
        new_text: str = "",
        replace_all: bool = False,
    ) -> dict[str, Any]:
        replacements = self.workspace.replace_in_file(
            path=path,
            old_text=old_text,
            new_text=new_text,
            replace_all=replace_all,
        )
        return {"replacements": replacements}

    def search_files(self, pattern: str, path: str = ".") -> dict[str, Any]:
        return {"matches": self.workspace.search_files(pattern=pattern, path=path)}

    def run_command(
        self,
        command: str,
        cwd: str = ".",
        timeout_seconds: int = settings.agent_command_timeout_seconds,
    ) -> dict[str, Any]:
        result = self.command_runner.run(
            command=command,
            cwd=self.workspace.resolve_path(cwd),
            timeout_seconds=timeout_seconds,
        )
        return {
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    def build_tools(self) -> list[StructuredTool]:
        return [
            StructuredTool.from_function(
                func=self.list_files,
                name="list_files",
                description="List files under a workspace path.",
                args_schema=ListFilesInput,
            ),
            StructuredTool.from_function(
                func=self.read_file,
                name="read_file",
                description="Read a file from the workspace.",
                args_schema=ReadFileInput,
            ),
            StructuredTool.from_function(
                func=self.write_file,
                name="write_file",
                description="Write a file in the workspace.",
                args_schema=WriteFileInput,
            ),
            StructuredTool.from_function(
                func=self.replace_in_file,
                name="replace_in_file",
                description="Replace text inside a workspace file.",
                args_schema=ReplaceInFileInput,
            ),
            StructuredTool.from_function(
                func=self.search_files,
                name="search_files",
                description="Search files in the workspace with ripgrep.",
                args_schema=SearchFilesInput,
            ),
            StructuredTool.from_function(
                func=self.run_command,
                name="run_command",
                description="Run a shell command inside the workspace.",
                args_schema=RunCommandInput,
            ),
        ]

    def build_tool_map(self) -> dict[str, StructuredTool]:
        return {tool.name: tool for tool in self.build_tools()}
