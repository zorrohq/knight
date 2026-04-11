from knight.agents.graph import AgentGraphRunner
from knight.agents.models import AgentRunResult, AgentTaskRequest
from knight.runtime.logging_config import ResolvedLoggingSettings


class CodingAgentService:
    def __init__(self) -> None:
        self.runner = AgentGraphRunner()

    def run(
        self,
        task: AgentTaskRequest,
        sandbox: dict[str, object] | None = None,
        log_config: ResolvedLoggingSettings | None = None,
    ) -> AgentRunResult:
        return self.runner.run(task, sandbox=sandbox, log_config=log_config)
