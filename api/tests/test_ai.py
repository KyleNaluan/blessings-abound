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
