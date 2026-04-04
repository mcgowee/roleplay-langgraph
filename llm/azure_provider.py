from langchain_openai import AzureChatOpenAI

from config import AZURE_ENDPOINT, AZURE_API_KEY, AZURE_DEPLOYMENT, AZURE_API_VERSION


class AzureProvider:
    """Azure OpenAI provider. Ignores model_name — uses the configured deployment."""

    def __init__(self, model_name: str) -> None:
        # model_name is accepted for interface compatibility but ignored.
        # All calls go to the single Azure deployment.
        self._llm = AzureChatOpenAI(
            azure_endpoint=AZURE_ENDPOINT,
            api_key=AZURE_API_KEY,
            azure_deployment=AZURE_DEPLOYMENT,
            api_version=AZURE_API_VERSION,
        )

    def invoke(self, prompt: str) -> str:
        # AzureChatOpenAI.invoke() returns an AIMessage, not a plain string.
        # Extract .content to match the str return type.
        result = self._llm.invoke(prompt)
        return result.content
