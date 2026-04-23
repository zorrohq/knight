import json

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
        commit_msg, _ = self.generate_both(task=task, diff_text=diff_text)
        return commit_msg

    def generate_both(
        self,
        *,
        task: AgentTaskRequest,
        diff_text: str,
    ) -> tuple[str, str]:
        """Return (commit_message, changelog_bullets) from a single LLM call."""
        repository_identity = normalize_repository_identity(
            repository_url=task.repository_url,
            repository_local_path=task.repository_local_path,
        ) or None
        runtime_config = AgentConfigResolver().resolve(repository=repository_identity)
        model = create_agent_model(runtime_config, tier="low")
        trimmed_diff = diff_text[: settings.worker_commit_max_diff_chars]

        if model is None or not trimmed_diff.strip():
            return self._fallback_message(task), "- Automated changes by Knight."

        prompt = (
            "Based on the task and git diff below, produce a JSON object with exactly two keys:\n"
            '  "commit": a single imperative-mood commit message subject line (<=72 chars)\n'
            '  "changelog": a markdown bullet list of what changed (max 8 items, plain "- item" format)\n\n'
            "Return only the JSON object, no markdown fences or extra text.\n\n"
            f"Task type: {task.task_type}\n"
            f"Issue id: {task.issue_id or 'none'}\n"
            f"Instructions: {task.instructions or 'none'}\n"
            f"Diff:\n{trimmed_diff}"
        )

        try:
            response = model.invoke(prompt)
            content = response.content if isinstance(response.content, str) else ""
            data = json.loads(content.strip())
            commit_msg = str(data.get("commit", "")).strip().splitlines()[0].strip()
            changelog = str(data.get("changelog", "")).strip()
            if commit_msg and changelog:
                return commit_msg, changelog
        except Exception:
            pass

        return self._fallback_message(task), "- Automated changes by Knight."

    def _fallback_message(self, task: AgentTaskRequest) -> str:
        issue_suffix = f" for {task.issue_id}" if task.issue_id else ""
        return f"Apply {task.task_type} changes{issue_suffix}"
