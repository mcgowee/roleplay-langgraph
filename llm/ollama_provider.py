from langchain_community.llms import Ollama

from config import OLLAMA_HOST


class OllamaProvider:
    def __init__(self, model_name: str) -> None:
        self._llm = Ollama(model=model_name, base_url=OLLAMA_HOST)

    def invoke(self, prompt: str) -> str:
        return self._llm.invoke(prompt)
