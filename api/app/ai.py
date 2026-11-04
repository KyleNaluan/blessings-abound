"""Vision and language model provider behind one interface.

Any OpenAI-compatible chat-completions endpoint works, chosen with AI_BASE_URL, AI_MODEL and
AI_API_KEY. A second endpoint in AI_FALLBACK_BASE_URL, AI_FALLBACK_MODEL and AI_FALLBACK_API_KEY
takes over when the first one fails, see app/vision.py. Images go in as OpenAI-style content
parts, for example {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}}.
"""

import json
import logging
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx2
from pydantic import ValidationError

from app.settings import Settings, get_settings

logger = logging.getLogger(__name__)

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


class ModelReplyError(RuntimeError):
    """Every provider failed, with one line per attempt in `attempts`."""

    def __init__(
        self, attempts: list[str], summary: str = "could not get a usable reply from the model"
    ) -> None:
        super().__init__(f"{summary}: " + "; ".join(attempts))
        self.attempts = attempts


@dataclass
class JsonReply[T]:
    value: T
    provider: str
    # 1 for a first-try success, 2 after the retry.
    attempts_on_provider: int
    used_fallback: bool
    failures: list[str] = field(default_factory=list)


def strip_reply(reply: str) -> str:
    """The JSON in a reply, without a think block or a markdown fence around it."""
    text = re.sub(r"<think>.*?</think>", "", reply, flags=re.DOTALL).strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL)
    return fenced.group(1) if fenced else text


def complete_json[T](
    messages: list[Message],
    providers: Sequence[ChatModel],
    parse: Callable[[str], T],
) -> JsonReply[T]:
    """Ask each provider in order, giving each one a retry on a reply `parse` refuses.

    A transport or HTTP error moves straight to the next provider, because a retry of the same
    request would meet the same outage or rate limit.
    """
    failures: list[str] = []
    for index, provider in enumerate(providers):
        for attempt in (1, 2):
            try:
                reply = provider.complete(messages, json_mode=True)
            except (httpx2.HTTPError, KeyError, IndexError, json.JSONDecodeError) as error:
                failures.append(f"{provider.name} attempt {attempt}: {describe_error(error)}")
                break
            try:
                value = parse(reply)
            except (ValidationError, ValueError, TypeError) as error:
                failures.append(
                    f"{provider.name} attempt {attempt}: bad JSON ({describe_error(error)})"
                )
                continue
            if failures:
                logger.warning("the model needed more than one try: %s", "; ".join(failures))
            return JsonReply(value, provider.name, attempt, index > 0, failures)
    raise ModelReplyError(failures or ["no provider is configured"])


def describe_error(error: Exception) -> str:
    if isinstance(error, httpx2.HTTPStatusError):
        return f"HTTP {error.response.status_code}"
    if isinstance(error, ValidationError):
        return f"{error.error_count()} validation errors"
    return type(error).__name__
