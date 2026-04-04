from config import LLM_PROVIDER

from .base import LLMProvider
from .ollama_provider import OllamaProvider

_llm_cache: dict[str, LLMProvider] = {}


def get_llm(model_name: str) -> LLMProvider:
    """Cached LLM provider instance to avoid recreating connections."""
    if LLM_PROVIDER == "azure":
        cache_key = "__azure__"
    else:
        cache_key = model_name

    if cache_key not in _llm_cache:
        if LLM_PROVIDER == "ollama":
            instance: LLMProvider = OllamaProvider(model_name)
        elif LLM_PROVIDER == "azure":
            from .azure_provider import AzureProvider

            instance = AzureProvider(model_name)
        else:
            raise ValueError(f"Unknown LLM provider: {LLM_PROVIDER}")
        _llm_cache[cache_key] = instance
    return _llm_cache[cache_key]


def cleanup_llm_cache() -> None:
    """Clear LLM cache (call on server shutdown)."""
    global _llm_cache
    _llm_cache.clear()


__all__ = ["get_llm", "cleanup_llm_cache", "LLMProvider"]
