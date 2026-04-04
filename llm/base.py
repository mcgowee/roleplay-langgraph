from typing import Protocol


class LLMProvider(Protocol):
    def invoke(self, prompt: str) -> str: ...
