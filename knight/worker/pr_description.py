from knight.agents.llm import create_agent_model
from knight.agents.models import AgentTaskRequest
from knight.agents.runtime_config import AgentConfigResolver
from knight.runtime.repository_identity import normalize_repository_identity
from knight.worker.config import settings


class PRDescriptionService:
    def generate(
        self,
        *,
        task: AgentTaskRequest,
        diff_text: str,
    ) -> str:
        repository_identity = normalize_repository_identity(
            repository_url=task.repository_url,
            repository_local_path=task.repository_local_path,
        ) or None
        runtime_config = AgentConfigResolver().resolve(repository=repository_identity)
        model = create_agent_model(runtime_config)
        trimmed_diff = diff_text[: settings.worker_commit_max_diff_chars]

        if model is None:
            return self._append_issue_ref(self._fallback_description(task), task)

        prompt = (
            "Write a concise pull request description as a changelog summarising the changes made. "
            "Use markdown. Include a short '## Summary' section (2-4 bullet points) and a "
            "'## Changes' section listing the key modifications. "
            "Do not repeat the task instructions verbatim. Focus on what changed and why.\n\n"
            f"Task: {task.instructions or 'none'}\n"
            f"Issue: {task.issue_id or 'none'}\n"
            f"Diff:\n{trimmed_diff}"
        )
        response = model.invoke(prompt)
        content = response.content
        if isinstance(content, str) and content.strip():
            return self._append_issue_ref(content.strip(), task)
        return self._append_issue_ref(self._fallback_description(task), task)

    def _issue_ref(self, task: AgentTaskRequest) -> str:
        if not task.issue_id or "#" not in task.issue_id:
            return ""
        number = task.issue_id.split("#", 1)[-1]
        return f"Closes #{number}" if number.isdigit() else ""

    def _append_issue_ref(self, body: str, task: AgentTaskRequest) -> str:
        ref = self._issue_ref(task)
        if not ref:
            return body
        return f"{body}\n\n---\n\n{ref}"

    def _fallback_description(self, task: AgentTaskRequest) -> str:
        return f"Automated changes by Knight.\n\n{task.instructions or ''}".strip()
