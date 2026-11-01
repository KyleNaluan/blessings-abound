"""Vision and language model provider behind one interface.

Any OpenAI-compatible chat-completions endpoint works, chosen with AI_BASE_URL, AI_MODEL and
AI_API_KEY. A second endpoint in AI_FALLBACK_BASE_URL, AI_FALLBACK_MODEL and AI_FALLBACK_API_KEY
takes over when the first one fails, see app/vision.py. Images go in as OpenAI-style content
parts, for example {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}}.
"""

from typing import Any, Protocol

import httpx2

from app.settings import Settings, get_settings

Message = dict[str, Any]


class ChatModel(Protocol):
    name: str

    def complete(self, messages: list[Message], *, json_mode: bool = False) -> str: ...


class OpenAICompatibleChat:
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str,
        transport: httpx2.BaseTransport | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.model = model
        self.name = f"{httpx2.URL(base_url).host}/{model}"
        self.client = httpx2.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            transport=transport,
            timeout=timeout,
        )

    def complete(self, messages: list[Message], *, json_mode: bool = False) -> str:
        body: dict[str, Any] = {"model": self.model, "messages": messages}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        response = self.client.post("/chat/completions", json=body)
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]


class AINotConfiguredError(RuntimeError):
    pass


def get_chat_model(settings: Settings | None = None) -> ChatModel:
    settings = settings or get_settings()
    if not (settings.ai_base_url and settings.ai_model and settings.ai_api_key):
        raise AINotConfiguredError(
            "set AI_BASE_URL, AI_MODEL and AI_API_KEY to use the AI provider"
        )
    return OpenAICompatibleChat(settings.ai_base_url, settings.ai_model, settings.ai_api_key)


def get_fallback_chat_model(settings: Settings | None = None) -> ChatModel | None:
    """The second provider, or None when it is not configured."""
    settings = settings or get_settings()
    base_url = settings.ai_fallback_base_url
    model = settings.ai_fallback_model
    api_key = settings.ai_fallback_api_key
    if base_url and model and api_key:
        return OpenAICompatibleChat(base_url, model, api_key)
    missing = [
        name
        for name, value in (
            ("AI_FALLBACK_BASE_URL", base_url),
            ("AI_FALLBACK_MODEL", model),
            ("AI_FALLBACK_API_KEY", api_key),
        )
        if not value
    ]
    if len(missing) == 3:
        return None
    raise AINotConfiguredError("set " + ", ".join(missing) + " to use the AI fallback provider")
