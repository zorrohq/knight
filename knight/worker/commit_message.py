from knight.agents.llm import create_agent_model
from knight.agents.models import AgentTaskRequest
from knight.agents.runtime_config import AgentConfigResolver
from knight.runtime.repository_identity import normalize_repository_identity
from knight.worker.config import settings


class CommitMessageService:
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
            return self._fallback_message(task)

        prompt = (
            "Write a concise git commit message in imperative mood. "
            "Return only the commit message subject line.\n\n"
            f"Task type: {task.task_type}\n"
            f"Issue id: {task.issue_id or 'none'}\n"
            f"Instructions: {task.instructions or 'none'}\n"
            f"Diff:\n{trimmed_diff}"
        )
        response = model.invoke(prompt)
        content = response.content
        if isinstance(content, str):
            message = content.strip().splitlines()[0].strip()
            if message:
                return message
        return self._fallback_message(task)

    def _fallback_message(self, task: AgentTaskRequest) -> str:
        issue_suffix = f" for {task.issue_id}" if task.issue_id else ""
        return f"Apply {task.task_type} changes{issue_suffix}"
