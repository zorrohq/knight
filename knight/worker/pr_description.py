from knight.agents.llm import create_agent_model
from knight.agents.models import AgentTaskRequest
from knight.agents.runtime_config import AgentConfigResolver
from knight.runtime.repository_identity import normalize_repository_identity
from knight.worker.config import settings


class ChangelogService:
    """Generates a bullet-list changelog from a git diff.

    Used for both new PR bodies and update comments on existing PRs.
    """

    def generate(self, *, task: AgentTaskRequest, diff_text: str) -> str:
        repository_identity = normalize_repository_identity(
            repository_url=task.repository_url,
            repository_local_path=task.repository_local_path,
        ) or None
        runtime_config = AgentConfigResolver().resolve(repository=repository_identity)
        model = create_agent_model(runtime_config, tier="low")
        trimmed_diff = diff_text[: settings.worker_commit_max_diff_chars]

        if model is None or not trimmed_diff.strip():
            return self._fallback(task)

        prompt = (
            "Based on the git diff below, write a concise bullet-point list of what changed. "
            "Use plain markdown list items (- item). No headings, no summary section, no preamble. "
            "Be specific: mention file names, functions, or UI elements affected. "
            "Maximum 8 bullet points.\n\n"
            f"Diff:\n{trimmed_diff}"
        )
        response = model.invoke(prompt)
        content = response.content
        if isinstance(content, str) and content.strip():
            return content.strip()
        return self._fallback(task)

    def _fallback(self, task: AgentTaskRequest) -> str:
        return "- Automated changes by Knight."

    def for_pr_body(self, *, task: AgentTaskRequest, diff_text: str) -> str:
        """Changelog formatted for a PR body, with issue close reference appended."""
        changelog = self.generate(task=task, diff_text=diff_text)
        ref = self._issue_ref(task)
        if ref:
            return f"{changelog}\n\n---\n\n{ref}"
        return changelog

    def _issue_ref(self, task: AgentTaskRequest) -> str:
        if not task.issue_id or "#" not in task.issue_id:
            return ""
        number = task.issue_id.split("#", 1)[-1]
        return f"Closes #{number}" if number.isdigit() else ""
