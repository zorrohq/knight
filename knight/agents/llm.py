from langchain.chat_models import init_chat_model

from knight.agents.config import settings


def create_agent_model():
    if not settings.agent_provider or not settings.agent_model:
        return None

    return init_chat_model(
        settings.agent_model,
        model_provider=settings.agent_provider,
        temperature=settings.agent_temperature,
    )
