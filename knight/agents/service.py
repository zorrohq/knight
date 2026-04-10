from knight.agents.graph import AgentGraphRunner
from knight.agents.models import AgentRunResult, AgentTaskRequest


class CodingAgentService:
    def __init__(self) -> None:
        self.runner = AgentGraphRunner()

    def run(
        self,
        task: AgentTaskRequest,
        sandbox: dict[str, object] | None = None,
    ) -> AgentRunResult:
        return self.runner.run(task, sandbox=sandbox)
