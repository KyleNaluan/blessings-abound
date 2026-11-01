import base64
import io
import json

import httpx2
import pytest
from PIL import Image

from app.ai import OpenAICompatibleChat
from app.models import Category, Confidence
from app.vision import (
    ItemCardError,
    Photo,
    UnreadablePhotoError,
    build_messages,
    parse_item_card,
    prepare_photo,
    read_item_card,
)

CARD = {
    "category": "apparel",
    "brand": "Levi's",
    "product": "jeans",
    "visible_text": "501",
    "search_query": "Levi's 501 jeans",
    "model_confidence": "high",
}
PHOTO = Photo(b"\xff\xd8fake")


def provider(name: str, replies: list[str | int]) -> tuple[OpenAICompatibleChat, list[dict]]:
    """A provider that answers with each reply in turn, where an int is an HTTP error status."""
    seen: list[dict] = []
    queue = list(replies)

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(json.loads(request.content))
        reply = queue.pop(0)
        if isinstance(reply, int):
            return httpx2.Response(reply, json={"error": {"message": "stubbed"}})
        return httpx2.Response(200, json={"choices": [{"message": {"content": reply}}]})

    chat = OpenAICompatibleChat(
        f"https://{name}.example.com/v1", "m", "secret", httpx2.MockTransport(handler)
    )
    return chat, seen


class StubReply:
    """A provider whose reply has no text, as a null message content comes through."""

    name = "empty"

    def complete(self, messages: list[dict], *, json_mode: bool = False) -> str:
        return None  # type: ignore[return-value]


def test_valid_json_on_the_first_try() -> None:
    primary, seen = provider("primary", [json.dumps(CARD)])
    fallback, fallback_seen = provider("fallback", [])

    result = read_item_card([PHOTO], [primary, fallback])

    assert result.card.category is Category.APPAREL
    assert result.card.model_confidence is Confidence.HIGH
    assert result.attempts_on_provider == 1
    assert not result.used_fallback
    assert result.failures == []
    assert fallback_seen == []
    (body,) = seen
    assert body["response_format"] == {"type": "json_object"}
    image = body["messages"][0]["content"][1]["image_url"]["url"]
    assert image == "data:image/jpeg;base64," + base64.b64encode(PHOTO.data).decode()


def test_bad_parse_then_a_good_retry_stays_on_the_primary() -> None:
    primary, seen = provider("primary", ["I think it is a jacket", json.dumps(CARD)])
    fallback, fallback_seen = provider("fallback", [])

    result = read_item_card([PHOTO], [primary, fallback])

    assert result.attempts_on_provider == 2
    assert not result.used_fallback
    assert len(result.failures) == 1
    assert len(seen) == 2
    assert fallback_seen == []


def test_bad_twice_falls_back_to_the_second_provider() -> None:
    wrong_category = json.dumps(CARD | {"category": "furniture"})
    primary, seen = provider("primary", ["not json", wrong_category])
    fallback, _ = provider("fallback", [json.dumps(CARD)])

    result = read_item_card([PHOTO], [primary, fallback])

    assert result.used_fallback
    assert result.provider == fallback.name
    assert len(seen) == 2


def test_an_http_error_skips_the_retry_and_falls_back() -> None:
    primary, seen = provider("primary", [429])
    fallback, _ = provider("fallback", [json.dumps(CARD)])

    result = read_item_card([PHOTO], [primary, fallback])

    assert result.used_fallback
    assert len(seen) == 1
    assert "HTTP 429" in result.failures[0]


def test_fallback_failure_is_a_clear_error() -> None:
    primary, _ = provider("primary", ["nope", "still nope"])
    fallback, _ = provider("fallback", ["nope", 500])

    with pytest.raises(ItemCardError) as error:
        read_item_card([PHOTO], [primary, fallback])

    message = str(error.value)
    assert "could not read an item card" in message
    assert len(error.value.attempts) == 4
    assert "primary.example.com/m attempt 2: bad JSON" in message
    assert "fallback.example.com/m attempt 2: HTTP 500" in message
    assert "secret" not in message


def test_no_provider_is_an_error() -> None:
    with pytest.raises(ItemCardError, match="no provider is configured"):
        read_item_card([PHOTO], [])


def test_parse_tolerates_a_fence_and_a_think_block() -> None:
    wrapped = "<think>maybe jeans</think>\n```json\n" + json.dumps(CARD) + "\n```"
    assert parse_item_card(wrapped).search_query == "Levi's 501 jeans"


def test_parse_rejects_unknown_keys_and_missing_fields() -> None:
    with pytest.raises(ValueError):
        parse_item_card(json.dumps(CARD | {"price": "$20"}))
    with pytest.raises(ValueError):
        parse_item_card(json.dumps({"category": "apparel"}))


def test_parse_drops_what_only_staff_may_enter() -> None:
    card = parse_item_card(json.dumps(CARD | {"condition": "new_with_tags", "size": "M"}))
    assert not hasattr(card, "condition")
    assert "size" not in card.model_dump()


def test_parse_rejects_an_empty_search_query() -> None:
    with pytest.raises(ValueError):
        parse_item_card(json.dumps(CARD | {"search_query": "  "}))


def test_prepare_photo_makes_an_upright_jpeg_within_the_size_limit() -> None:
    source = io.BytesIO()
    exif = Image.Exif()
    exif[0x0112] = 6  # Rotated a quarter turn, as a phone held upright saves it.
    Image.new("RGBA", (2000, 1000), "red").convert("RGB").save(source, format="JPEG", exif=exif)

    with Image.open(io.BytesIO(prepare_photo(source.getvalue()).data)) as prepared:
        assert prepared.format == "JPEG"
        assert prepared.size == (480, 960)


def test_prepare_photo_refuses_bytes_that_are_not_an_image() -> None:
    with pytest.raises(UnreadablePhotoError):
        prepare_photo(b"not an image")


def test_a_reply_with_no_text_counts_as_a_bad_parse() -> None:
    chat = StubReply()
    with pytest.raises(ItemCardError, match="bad JSON"):
        read_item_card([PHOTO], [chat])


def test_staff_notes_go_into_the_prompt() -> None:
    (message,) = build_messages([PHOTO], "tag is torn")
    assert "Staff notes: tag is torn" in message["content"][0]["text"]
