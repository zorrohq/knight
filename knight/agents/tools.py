from __future__ import annotations

import asyncio
import ipaddress
import logging
import shlex
import socket
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests as _requests
from langchain_core.tools import StructuredTool
from markdownify import markdownify
from pydantic import BaseModel, Field

from knight.agents.models import AgentTaskRequest
from knight.agents.runtime_config import ResolvedAgentSettings
from knight.runtime.authorship import (
    KNIGHT_BOT_EMAIL,
    KNIGHT_BOT_NAME,
    add_coauthor_trailer,
    add_pr_collaboration_note,
    make_identity,
)
from knight.runtime.command_runner import LocalCommandRunner
from knight.runtime.filesystem import LocalWorkspace
from knight.runtime.github import (
    create_github_pr,
    get_github_default_branch,
)
from knight.runtime.repository_identity import normalize_repository_identity

logger = logging.getLogger(__name__)

_MAX_REDIRECTS = 5
_GIT_TIMEOUT = 60


# ---------------------------------------------------------------------------
# Input schemas
# ---------------------------------------------------------------------------


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


class GitStatusInput(BaseModel):
    path: str = "."


class GitDiffInput(BaseModel):
    path: str = "."


class RunCommandInput(BaseModel):
    command: str
    cwd: str = "."
    timeout_seconds: int = Field(default=300)


class HttpRequestInput(BaseModel):
    url: str
    method: str = "GET"
    headers: dict[str, str] | None = None
    data: str | dict | None = None
    params: dict[str, str] | None = None
    timeout: int = 30


class FetchUrlInput(BaseModel):
    url: str
    timeout: int = 30


class CommitAndOpenPrInput(BaseModel):
    title: str
    body: str
    commit_message: str | None = None


# ---------------------------------------------------------------------------
# SSRF-safe HTTP helpers
# ---------------------------------------------------------------------------


def _is_url_safe(url: str) -> tuple[bool, str]:
    """Check that a URL does not resolve to a private or reserved address."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return False, f"unsupported URL scheme: {parsed.scheme or '<missing>'}"
        hostname = parsed.hostname
        if not hostname:
            return False, "could not parse hostname from URL"
        try:
            addr_infos = socket.getaddrinfo(hostname, None)
        except socket.gaierror:
            return False, f"could not resolve hostname: {hostname}"
        for addr_info in addr_infos:
            ip_str = addr_info[4][0]
            try:
                ip = ipaddress.ip_address(ip_str)
            except ValueError:
                continue
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return False, f"URL resolves to blocked address: {ip_str}"
        return True, ""
    except Exception as exc:
        return False, f"URL validation error: {exc}"


def _blocked_response(url: str, reason: str) -> dict[str, Any]:
    return {
        "success": False,
        "status_code": 0,
        "headers": {},
        "content": f"Request blocked: {reason}",
        "url": url,
    }


def _request_with_safe_redirects(
    method: str,
    url: str,
    *,
    timeout: int,
    **kwargs: Any,
) -> tuple[_requests.Response | None, dict[str, Any] | None]:
    current_method = method.upper()
    current_url = url
    request_kwargs = dict(kwargs)

    for redirect_count in range(_MAX_REDIRECTS + 1):
        is_safe, reason = _is_url_safe(current_url)
        if not is_safe:
            return None, _blocked_response(current_url, reason)

        response = _requests.request(
            current_method,
            current_url,
            timeout=timeout,
            allow_redirects=False,
            **request_kwargs,
        )

        if not response.is_redirect and not response.is_permanent_redirect:
            return response, None

        location = response.headers.get("Location")
        if not location:
            return response, None

        if redirect_count == _MAX_REDIRECTS:
            return None, _blocked_response(current_url, "too many redirects")

        current_url = urljoin(str(response.url), location)

        if response.status_code == _requests.codes.see_other or (
            response.status_code in {_requests.codes.moved, _requests.codes.found}
            and current_method not in {"GET", "HEAD"}
        ):
            current_method = "GET"
            request_kwargs.pop("data", None)
            request_kwargs.pop("json", None)

    return None, _blocked_response(current_url, "too many redirects")


# ---------------------------------------------------------------------------
# AgentToolset
# ---------------------------------------------------------------------------


class AgentToolset:
    def __init__(
        self,
        workspace: LocalWorkspace,
        command_runner: LocalCommandRunner,
        runtime_config: ResolvedAgentSettings,
        task: AgentTaskRequest | None = None,
        sandbox: dict[str, Any] | None = None,
    ) -> None:
        self.workspace = workspace
        self.command_runner = command_runner
        self.runtime_config = runtime_config
        self.task = task
        self.sandbox = sandbox or {}

    # ------------------------------------------------------------------
    # Filesystem tools
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Git tools (read-only within workspace)
    # ------------------------------------------------------------------

    def git_status(self, path: str = ".") -> dict[str, Any]:
        result = self.command_runner.run(
            command="git status --short",
            cwd=self.workspace.resolve_path(path),
            timeout_seconds=self.runtime_config.command_timeout_seconds,
        )
        return {
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    def git_diff(self, path: str = ".") -> dict[str, Any]:
        result = self.command_runner.run(
            command="git diff -- .",
            cwd=self.workspace.resolve_path(path),
            timeout_seconds=self.runtime_config.command_timeout_seconds,
        )
        return {
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    # ------------------------------------------------------------------
    # Shell tool
    # ------------------------------------------------------------------

    def run_command(
        self,
        command: str,
        cwd: str = ".",
        timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        result = self.command_runner.run(
            command=command,
            cwd=self.workspace.resolve_path(cwd),
            timeout_seconds=timeout_seconds or self.runtime_config.command_timeout_seconds,
        )
        return {
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    # ------------------------------------------------------------------
    # Web tools
    # ------------------------------------------------------------------

    def http_request(
        self,
        url: str,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        data: str | dict | None = None,
        params: dict[str, str] | None = None,
        timeout: int = 30,
    ) -> dict[str, Any]:
        """Make an HTTP request to an external API or service.

        Private and internal IP addresses are blocked to prevent SSRF attacks.
        """
        try:
            kwargs: dict[str, Any] = {}
            if headers:
                kwargs["headers"] = headers
            if params:
                kwargs["params"] = params
            if data:
                if isinstance(data, dict):
                    kwargs["json"] = data
                else:
                    kwargs["data"] = data

            response, blocked = _request_with_safe_redirects(
                method, url, timeout=timeout, **kwargs
            )
            if blocked:
                return blocked

            try:
                content = response.json()
            except (ValueError, _requests.exceptions.JSONDecodeError):
                content = response.text

            return {
                "success": response.status_code < 400,
                "status_code": response.status_code,
                "headers": dict(response.headers),
                "content": content,
                "url": str(response.url),
            }
        except _requests.exceptions.Timeout:
            return {
                "success": False,
                "status_code": 0,
                "headers": {},
                "content": f"request timed out after {timeout}s",
                "url": url,
            }
        except _requests.exceptions.RequestException as exc:
            return {
                "success": False,
                "status_code": 0,
                "headers": {},
                "content": f"request error: {exc}",
                "url": url,
            }

    def fetch_url(self, url: str, timeout: int = 30) -> dict[str, Any]:
        """Fetch a web page and convert it to readable markdown."""
        try:
            response, blocked = _request_with_safe_redirects(
                "GET",
                url,
                timeout=timeout,
                headers={"User-Agent": "Mozilla/5.0 (compatible; Knight/1.0)"},
            )
            if blocked:
                return {"error": blocked["content"], "status_code": 0, "url": url}

            response.raise_for_status()
            markdown_content = markdownify(response.text)
            return {
                "url": str(response.url),
                "markdown_content": markdown_content,
                "status_code": response.status_code,
                "content_length": len(markdown_content),
            }
        except _requests.exceptions.RequestException as exc:
            return {"error": f"fetch error: {exc}", "url": url}

    # ------------------------------------------------------------------
    # Commit and open PR tool
    # ------------------------------------------------------------------

    def commit_and_open_pr(
        self,
        title: str,
        body: str,
        commit_message: str | None = None,
    ) -> dict[str, Any]:
        """Commit all changes, push to the branch, and open a GitHub draft PR.

        If a PR already exists for the branch it is updated rather than recreated.
        Call this as the final step of any code-change task.
        """
        if not self.task or not self.sandbox:
            return {
                "success": False,
                "error": "commit_and_open_pr is unavailable: sandbox context not provided",
                "pr_url": None,
            }

        worktree_path = Path(self.sandbox.get("worktree_path", str(self.workspace.root)))
        branch_name = self.sandbox.get("branch_name", "")
        push_remote = (self.task.push_remote or "origin") if self.task else "origin"

        # Check for uncommitted changes
        status = self._git(["git", "status", "--porcelain"], cwd=worktree_path)
        has_uncommitted = bool(status.stdout.strip())

        # Check for unpushed commits
        unpushed = self._git(
            ["git", "log", "--oneline", f"origin/{branch_name}..HEAD"],
            cwd=worktree_path,
            check=False,
        )
        has_unpushed = bool(unpushed.stdout.strip())

        if not has_uncommitted and not has_unpushed:
            return {"success": False, "error": "no changes detected", "pr_url": None}

        # Build commit message with attribution
        final_commit_msg = commit_message or title
        if self.task:
            identity = make_identity(
                name=self.task.author_name,
                email=self.task.author_email,
            )
            final_commit_msg = add_coauthor_trailer(final_commit_msg, identity)
            pr_body = add_pr_collaboration_note(body, identity)
        else:
            pr_body = body

        if has_uncommitted:
            self._git(
                ["git", "config", "user.name", KNIGHT_BOT_NAME],
                cwd=worktree_path,
            )
            self._git(
                ["git", "config", "user.email", KNIGHT_BOT_EMAIL],
                cwd=worktree_path,
            )
            self._git(["git", "add", "--all"], cwd=worktree_path)
            commit_result = self._git(
                ["git", "commit", "-m", final_commit_msg],
                cwd=worktree_path,
                check=False,
            )
            if commit_result.returncode != 0:
                return {
                    "success": False,
                    "error": f"git commit failed: {commit_result.stderr.strip()}",
                    "pr_url": None,
                }

        push_result = self._git(
            ["git", "push", "--set-upstream", push_remote, branch_name],
            cwd=worktree_path,
            check=False,
        )
        if push_result.returncode != 0:
            return {
                "success": False,
                "error": f"git push failed: {push_result.stderr.strip()}",
                "pr_url": None,
            }

        github_token = (self.task.github_token if self.task else "") or ""
        if not github_token:
            logger.info("no github_token available; push succeeded but PR not created")
            return {
                "success": True,
                "pr_url": None,
                "pr_existing": False,
                "note": "branch pushed; no github_token configured for PR creation",
            }

        repository = normalize_repository_identity(
            repository_url=self.task.repository_url if self.task else "",
            repository_local_path=self.task.repository_local_path if self.task else "",
        )
        if "/" not in repository:
            return {
                "success": False,
                "error": f"could not determine repo owner/name from repository: {repository!r}",
                "pr_url": None,
            }
        repo_owner, repo_name = repository.split("/", 1)

        try:
            base_branch = asyncio.run(
                get_github_default_branch(
                    repo_owner=repo_owner,
                    repo_name=repo_name,
                    github_token=github_token,
                )
            )
            pr_url, _pr_number, pr_existing = asyncio.run(
                create_github_pr(
                    repo_owner=repo_owner,
                    repo_name=repo_name,
                    github_token=github_token,
                    title=title,
                    head_branch=branch_name,
                    base_branch=base_branch,
                    body=pr_body,
                )
            )
        except Exception as exc:
            logger.exception("GitHub PR creation failed")
            return {
                "success": False,
                "error": f"GitHub API error: {exc}",
                "pr_url": None,
            }

        if not pr_url:
            return {"success": False, "error": "GitHub PR creation returned no URL", "pr_url": None}

        return {"success": True, "pr_url": pr_url, "pr_existing": pr_existing, "error": None}

    def _git(
        self,
        command: list[str],
        *,
        cwd: Path,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            capture_output=True,
            timeout=_GIT_TIMEOUT,
            check=False,
        )
        if check and result.returncode != 0:
            raise RuntimeError(
                result.stderr.strip()
                or result.stdout.strip()
                or f"command failed: {shlex.join(command)}"
            )
        return result

    # ------------------------------------------------------------------
    # Tool registry
    # ------------------------------------------------------------------

    def build_tools(self) -> list[StructuredTool]:
        tools: list[StructuredTool] = [
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
                func=self.search_files,
                name="search_files",
                description="Search files in the workspace with ripgrep.",
                args_schema=SearchFilesInput,
            ),
            StructuredTool.from_function(
                func=self.git_status,
                name="git_status",
                description="Show git status inside the workspace repository.",
                args_schema=GitStatusInput,
            ),
            StructuredTool.from_function(
                func=self.git_diff,
                name="git_diff",
                description="Show the current git diff inside the workspace repository.",
                args_schema=GitDiffInput,
            ),
            StructuredTool.from_function(
                func=self.http_request,
                name="http_request",
                description=(
                    "Make an HTTP request (GET, POST, PUT, DELETE, etc.) to an external API. "
                    "Private and internal IP addresses are blocked. "
                    "Use for API calls with custom headers, methods, params, or request bodies."
                ),
                args_schema=HttpRequestInput,
            ),
            StructuredTool.from_function(
                func=self.fetch_url,
                name="fetch_url",
                description=(
                    "Fetch a web page and convert it to readable markdown. "
                    "Use for documentation pages, external references, or any public URL. "
                    "Only use URLs provided in the task or discovered during exploration."
                ),
                args_schema=FetchUrlInput,
            ),
        ]

        if self.runtime_config.allow_write_files:
            tools.extend(
                [
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
                ]
            )

        if self.runtime_config.allow_run_command:
            tools.append(
                StructuredTool.from_function(
                    func=self.run_command,
                    name="run_command",
                    description=(
                        "Run a shell command inside the workspace, subject to sandbox policy."
                    ),
                    args_schema=RunCommandInput,
                )
            )

        if self.runtime_config.allow_commit_and_push and self.task and self.sandbox:
            tools.append(
                StructuredTool.from_function(
                    func=self.commit_and_open_pr,
                    name="commit_and_open_pr",
                    description=(
                        "Commit all changes, push to the branch, and open a GitHub draft PR. "
                        "Call this as the FINAL step after verifying your implementation is correct."
                    ),
                    args_schema=CommitAndOpenPrInput,
                )
            )

        return tools

    def build_tool_map(self) -> dict[str, StructuredTool]:
        return {tool.name: tool for tool in self.build_tools()}
