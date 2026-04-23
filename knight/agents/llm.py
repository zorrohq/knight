from typing import Literal

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

from knight.agents.runtime_config import ResolvedAgentSettings

ModelTier = Literal["high", "low", "default"]


def _resolve_model(runtime_config: ResolvedAgentSettings, tier: ModelTier) -> str:
    """Return the model name for a tier, falling back to default."""
    if tier == "high":
        return runtime_config.model_high or runtime_config.model_default
    if tier == "low":
        return runtime_config.model_low or runtime_config.model_default
    return runtime_config.model_default


def create_agent_model(
    runtime_config: ResolvedAgentSettings,
    tier: ModelTier = "default",
) -> BaseChatModel | None:
    model = _resolve_model(runtime_config, tier)
    if not runtime_config.provider or not model:
        return None

    return init_chat_model(
        model,
        model_provider=runtime_config.provider,
        temperature=runtime_config.temperature,
    )
