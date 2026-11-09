from pathlib import Path

import httpx2
import pytest

from app.settings import Settings
from app.storage import LocalStorage, PhotoTooLargeError, SupabaseStorage, get_storage


def test_local_storage_round_trip(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    storage.save("items/1/front.jpg", b"jpeg bytes", "image/jpeg")
    assert storage.read("items/1/front.jpg") == b"jpeg bytes"


def test_local_storage_rejects_keys_outside_its_folder(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        LocalStorage(tmp_path).save("../outside.jpg", b"", "image/jpeg")


def test_supabase_storage_uses_the_storage_rest_api() -> None:
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(200, content=b"jpeg bytes")

    storage = SupabaseStorage(
        "https://example.supabase.co", "service-key", "photos", httpx2.MockTransport(handler)
    )
    storage.save("items/1/front.jpg", b"jpeg bytes", "image/jpeg")
    assert storage.read("items/1/front.jpg") == b"jpeg bytes"

    upload, download = requests
    assert upload.method == "POST"
    assert (
        str(upload.url) == "https://example.supabase.co/storage/v1/object/photos/items/1/front.jpg"
    )
    assert upload.headers["Authorization"] == "Bearer service-key"
    assert upload.headers["Content-Type"] == "image/jpeg"
    assert download.method == "GET"


def test_get_storage_picks_supabase_only_when_configured(tmp_path: Path) -> None:
    local = Settings(local_storage_dir=tmp_path, supabase_url=None, supabase_service_role_key=None)
    assert isinstance(get_storage(local), LocalStorage)
    configured = Settings(supabase_url="https://example.supabase.co", supabase_service_role_key="k")
    assert isinstance(get_storage(configured), SupabaseStorage)


@pytest.mark.parametrize(
    "response",
    [
        httpx2.Response(400, json={"statusCode": "413", "error": "Payload too large"}),
        httpx2.Response(413),
    ],
    ids=["supabase-body", "plain-413"],
)
def test_supabase_storage_says_when_a_photo_is_over_the_buckets_limit(
    response: httpx2.Response,
) -> None:
    storage = SupabaseStorage(
        "https://example.supabase.co", "key", "photos", httpx2.MockTransport(lambda _: response)
    )
    with pytest.raises(PhotoTooLargeError):
        storage.save("items/1/front.jpg", b"jpeg bytes", "image/jpeg")


def test_supabase_storage_raises_any_other_refusal() -> None:
    refusal = httpx2.Response(400, json={"statusCode": "400", "error": "Bad Request"})
    storage = SupabaseStorage(
        "https://example.supabase.co", "key", "photos", httpx2.MockTransport(lambda _: refusal)
    )
    with pytest.raises(httpx2.HTTPStatusError):
        storage.save("items/1/front.jpg", b"jpeg bytes", "image/jpeg")
