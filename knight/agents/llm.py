from langchain.chat_models import init_chat_model

from knight.agents.runtime_config import ResolvedAgentSettings


def create_agent_model(runtime_config: ResolvedAgentSettings):
    if not runtime_config.provider or not runtime_config.model:
        return None

    return init_chat_model(
        runtime_config.model,
        model_provider=runtime_config.provider,
        temperature=runtime_config.temperature,
    )
