from config import LLM_PROVIDER

from .base import LLMProvider
from .ollama_provider import OllamaProvider

_llm_cache: dict[str, LLMProvider] = {}


def get_llm(model_name: str) -> LLMProvider:
    """Cached LLM provider instance to avoid recreating connections."""
    if model_name not in _llm_cache:
        if LLM_PROVIDER == "ollama":
            instance: LLMProvider = OllamaProvider(model_name)
        else:
            raise ValueError(f"Unknown LLM provider: {LLM_PROVIDER}")
        _llm_cache[model_name] = instance
    return _llm_cache[model_name]


def cleanup_llm_cache() -> None:
    """Clear LLM cache (call on server shutdown)."""
    global _llm_cache
    _llm_cache.clear()


__all__ = ["get_llm", "cleanup_llm_cache", "LLMProvider"]
