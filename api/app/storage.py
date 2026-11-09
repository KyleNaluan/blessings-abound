"""Photo storage: a local folder in development and tests, Supabase Storage when configured."""

from pathlib import Path
from typing import Protocol

import httpx2

from app.settings import Settings, get_settings


class PhotoTooLargeError(Exception):
    """The storage refused a photo for its size, which trying again won't change."""


class Storage(Protocol):
    def save(self, key: str, data: bytes, content_type: str) -> None: ...

    def read(self, key: str) -> bytes: ...


class LocalStorage:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root.resolve()):
            raise ValueError(f"storage key escapes the storage folder: {key}")
        return path

    def save(self, key: str, data: bytes, content_type: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def read(self, key: str) -> bytes:
        return self._path(key).read_bytes()


class SupabaseStorage:
    """Talks to the Supabase Storage REST API with the service role key."""

    def __init__(
        self,
        url: str,
        service_role_key: str,
        bucket: str,
        transport: httpx2.BaseTransport | None = None,
    ) -> None:
        self.bucket = bucket
        self.client = httpx2.Client(
            base_url=f"{url.rstrip('/')}/storage/v1",
            headers={"Authorization": f"Bearer {service_role_key}", "apikey": service_role_key},
            transport=transport,
        )

    def save(self, key: str, data: bytes, content_type: str) -> None:
        response = self.client.post(
            f"/object/{self.bucket}/{key}",
            content=data,
            headers={"Content-Type": content_type, "x-upsert": "true"},
        )
        if _too_large(response):
            raise PhotoTooLargeError(f"{len(data)} bytes is over the bucket's size limit")
        response.raise_for_status()

    def read(self, key: str) -> bytes:
        response = self.client.get(f"/object/{self.bucket}/{key}")
        response.raise_for_status()
        return response.content


def _too_large(response: httpx2.Response) -> bool:
    """Whether the upload was over the bucket's size limit.

    Supabase answers that with a 400 whose body gives 413 as its status code.
    """
    if response.status_code == 413:
        return True
    if response.status_code != 400:
        return False
    try:
        body = response.json()
    except ValueError:
        return False
    return isinstance(body, dict) and str(body.get("statusCode")) == "413"


def get_storage(settings: Settings | None = None) -> Storage:
    settings = settings or get_settings()
    if settings.supabase_url and settings.supabase_service_role_key:
        return SupabaseStorage(
            settings.supabase_url,
            settings.supabase_service_role_key,
            settings.supabase_storage_bucket,
        )
    return LocalStorage(settings.local_storage_dir)
