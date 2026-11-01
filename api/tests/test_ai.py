import json

import httpx2
import pytest

from app.ai import AINotConfiguredError, OpenAICompatibleChat, get_chat_model
from app.settings import Settings


def test_chat_completion_request_shape() -> None:
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(200, json={"choices": [{"message": {"content": "a denim jacket"}}]})

    model = OpenAICompatibleChat(
        "https://ai.example.com/v1", "vision-model", "secret", httpx2.MockTransport(handler)
    )
    messages = [{"role": "user", "content": "What is this item?"}]
    assert model.complete(messages) == "a denim jacket"

    (request,) = requests
    assert str(request.url) == "https://ai.example.com/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer secret"
    assert json.loads(request.content) == {"model": "vision-model", "messages": messages}


def test_get_chat_model_requires_configuration() -> None:
    with pytest.raises(AINotConfiguredError):
        get_chat_model(Settings(ai_base_url=None, ai_model=None, ai_api_key=None))


def test_fallback_model_is_optional() -> None:
    from app.ai import get_fallback_chat_model

    assert get_fallback_chat_model(Settings(ai_fallback_base_url=None)) is None
    configured = Settings(
        ai_fallback_base_url="https://fallback.example.com/v1",
        ai_fallback_model="m",
        ai_fallback_api_key="k",
    )
    assert get_fallback_chat_model(configured) is not None


def test_partial_fallback_configuration_raises() -> None:
    from app.ai import get_fallback_chat_model

    partial = Settings(
        ai_fallback_base_url="https://fallback.example.com/v1",
        ai_fallback_model="m",
        ai_fallback_api_key=None,
    )
    with pytest.raises(AINotConfiguredError) as excinfo:
        get_fallback_chat_model(partial)
    message = str(excinfo.value)
    assert "AI_FALLBACK_API_KEY" in message
    assert "AI_FALLBACK_BASE_URL" not in message
    assert "AI_FALLBACK_MODEL" not in message
