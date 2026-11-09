"""Intake through the API: the SKU, the photo checks, the repeat photo flag and the triage log."""

import hashlib
import importlib.util
import io
import threading
from datetime import UTC, date, datetime
from types import ModuleType
from typing import Any
from uuid import UUID

import httpx2
import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi.testclient import TestClient
from PIL import ExifTags, Image
from sqlalchemy import Connection
from sqlmodel import Session, col, select

from app import appraisal, photo_check
from app.appraisal import get_photo_storage
from app.db import get_engine
from app.intake import MAX_PHOTO_BYTES, get_now, initials, next_sku, store_date
from app.main import app
from app.models import Decision, Item, Profile, SkuSequence, TriageEntry
from app.settings import get_settings
from app.storage import LocalStorage, SupabaseStorage
from tests import test_schema
from tests.test_appraisal import (  # noqa: F401, the fixtures these tests build on
    MANAGER_TOKEN,
    OTHER_STAFF_TOKEN,
    REJECTION,
    add_card,
    appraise,
    as_token,
    client,
    decide,
    jpeg,
    post_item,
    sharp_photo,
    storage,
    upload,
)
from tests.test_store_settings import VERSIONS

# The afternoon of the day the appraisal tests run on, in Kansas City.
NOW = datetime(2026, 11, 4, 20, 0, tzinfo=UTC)


@pytest.fixture
def staff(client: TestClient) -> TestClient:  # noqa: F811
    """Staff1 signed in, with the models and searches stubbed as in the appraisal tests."""
    return client


@pytest.fixture
def photo_storage(storage: LocalStorage) -> LocalStorage:  # noqa: F811
    return storage


def at(moment: datetime) -> None:
    app.dependency_overrides[get_now] = lambda: moment


def image(kind: str) -> bytes:
    output = io.BytesIO()
    sharp_photo().save(output, format=kind)
    return output.getvalue()


def appraised(staff: TestClient, *photos: bytes, **form: str | bool) -> tuple[str, str]:
    """An item taken in with these photos, carded and appraised, as its id and appraisal id."""
    response = post_item(staff, *(photos or (jpeg(),)), **form)
    assert response.status_code == 201, response.text
    item_id = response.json()["id"]
    add_card(staff, item_id)
    return item_id, appraise(staff, item_id)["id"]


def rejected(staff: TestClient, *photos: bytes) -> str:
    item_id, appraisal_id = appraised(staff, *photos)
    assert decide(staff, item_id, appraisal_id, "no").status_code == 201
    return item_id


def triage_rows(session: Session, item_id: str) -> list[TriageEntry]:
    query = select(TriageEntry).where(TriageEntry.item_id == UUID(item_id))
    return list(session.exec(query.order_by(col(TriageEntry.recorded_at))).all())


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Rosa María Torres", "RT"),
        ("rob tate", "RT"),
        ("Jean-Luc Picard", "JP"),
        ("Staff1", "ST"),
        ("Ángel", "AN"),
        ("Q", "QX"),
        ("李明", "XX"),
        ("", "XX"),
    ],
)
def test_initials_come_from_the_first_and_last_words(name: str, expected: str) -> None:
    assert initials(name) == expected


def test_the_day_is_the_stores_day() -> None:
    # 9 PM in Kansas City is already the next day in UTC.
    assert store_date(datetime(2026, 11, 5, 3, 0, tzinfo=UTC)) == date(2026, 11, 4)
    assert store_date(datetime(2026, 11, 5, 6, 0, tzinfo=UTC)) == date(2026, 11, 5)


def test_each_item_that_day_gets_the_next_number(staff: TestClient) -> None:
    at(NOW)
    assert [upload(staff)["sku"] for _ in range(3)] == ["ST11042601", "ST11042602", "ST11042603"]


def test_a_new_day_starts_again_at_one(staff: TestClient) -> None:
    at(NOW)
    assert upload(staff)["sku"] == "ST11042601"
    at(datetime(2026, 11, 5, 3, 0, tzinfo=UTC))
    assert upload(staff)["sku"] == "ST11042602"
    at(datetime(2026, 11, 5, 15, 0, tzinfo=UTC))
    assert upload(staff)["sku"] == "ST11052601"


def test_two_people_with_the_same_initials_share_the_days_numbers(
    staff: TestClient, session: Session
) -> None:
    at(NOW)
    other = TestClient(app, headers=as_token(OTHER_STAFF_TOKEN))
    first, second = upload(staff), upload(other)
    assert [first["sku"], second["sku"]] == ["ST11042601", "ST11042602"]
    listers = {session.get_one(Item, UUID(item["id"])).lister_id for item in (first, second)}
    assert len(listers) == 2


def test_a_number_given_out_in_a_failed_intake_is_given_back(session: Session) -> None:
    assert next_sku(session, "AB010126") == "AB01012601"
    session.rollback()
    assert next_sku(session, "AB010126") == "AB01012601"


def test_two_intakes_at_once_wait_for_each_other_and_get_different_numbers() -> None:
    # Two real connections, so the second intake waits on the first's lock as it would live. The
    # prefix is a day no store reaches, so it never meets a developer's own data.
    prefix = "ZZ123199"
    engine = get_engine()
    taken: list[str] = []
    try:
        with Session(engine) as first, Session(engine) as second:
            taken.append(next_sku(first, prefix))

            def take_second() -> None:
                taken.append(next_sku(second, prefix))
                second.commit()

            thread = threading.Thread(target=take_second)
            thread.start()
            thread.join(timeout=0.5)
            assert thread.is_alive(), "the second intake didn't wait for the first"
            first.commit()
            thread.join(timeout=10)
            assert not thread.is_alive()
        assert taken == [f"{prefix}01", f"{prefix}02"]
    finally:
        with engine.begin() as connection:
            connection.execute(sa.delete(SkuSequence).where(col(SkuSequence.prefix) == prefix))


def test_intake_keeps_up_to_four_photos_with_their_hashes_and_the_notes(
    staff: TestClient, session: Session, photo_storage: LocalStorage
) -> None:
    photos = [jpeg(), image("PNG"), image("WEBP"), jpeg()]
    response = post_item(staff, *photos, notes="  Missing one button  ")
    assert response.status_code == 201, response.text
    item = response.json()
    assert [photo_storage.read(key) for key in item["photo_keys"]] == photos
    assert item["store_department"] == "clothing"
    assert item["notes"] == "Missing one button"
    row = session.get_one(Item, UUID(item["id"]))
    assert row.photo_hashes == [hashlib.sha256(photo).hexdigest() for photo in photos]


def test_photos_are_stored_as_the_type_their_bytes_show(
    staff: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    types: list[str] = []
    real_save = LocalStorage.save

    def save(self: LocalStorage, key: str, data: bytes, content_type: str) -> None:
        types.append(content_type)
        real_save(self, key, data, content_type)

    monkeypatch.setattr(LocalStorage, "save", save)
    # Each is sent labeled as a JPEG.
    assert post_item(staff, image("PNG"), image("WEBP"), jpeg()).status_code == 201
    assert types == ["image/png", "image/webp", "image/jpeg"]


def test_blank_notes_are_no_notes(staff: TestClient) -> None:
    assert upload(staff, notes="   ")["notes"] is None


def test_intake_needs_a_known_store_department(staff: TestClient) -> None:
    files = [("photos", ("item.jpg", jpeg(), "image/jpeg"))]
    assert staff.post("/items", files=files).status_code == 422
    assert post_item(staff, jpeg(), store_department="toys").status_code == 422
    assert upload(staff, store_department="electronics_games")["store_department"] == (
        "electronics_games"
    )


@pytest.mark.parametrize(
    ("photos", "message"),
    [
        ([jpeg() for _ in range(5)], "Add at most 4 photos of the item."),
        ([b""], "Photo 1 is empty."),
        ([jpeg(), b""], "Photo 2 is empty."),
        ([b"\xff" * (MAX_PHOTO_BYTES + 1)], "Photo 1 is over 15 MB, so choose a smaller copy."),
        ([b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n"], "Photo 1 isn't a JPEG, PNG or WebP image."),
        ([image("GIF")], "Photo 1 isn't a JPEG, PNG or WebP image."),
        ([jpeg()[:200]], "Photo 1 isn't a JPEG, PNG or WebP image."),
    ],
    ids=["five", "empty", "second-empty", "too-big", "pdf", "gif", "cut-short"],
)
def test_photos_that_cannot_be_taken_in_are_refused_and_nothing_is_kept(
    staff: TestClient,
    session: Session,
    photo_storage: LocalStorage,
    photos: list[bytes],
    message: str,
) -> None:
    response = post_item(staff, *photos)
    assert response.status_code == 422
    assert response.json()["detail"] == message
    assert session.exec(select(Item)).all() == []
    assert not photo_storage.root.exists() or not any(photo_storage.root.iterdir())


def test_a_photo_at_the_size_limit_passes_the_size_check(staff: TestClient) -> None:
    photo = jpeg()
    padded = photo + b"\0" * (MAX_PHOTO_BYTES - len(photo))
    assert len(padded) == MAX_PHOTO_BYTES
    assert post_item(staff, padded).status_code == 201


# The hosted bucket's file size limit.
BUCKET_LIMIT = 10 * 1024 * 1024
# What Supabase Storage answers for a file over that limit.
TOO_LARGE = {
    "statusCode": "413",
    "error": "Payload too large",
    "message": "The object exceeded the maximum allowed size",
    "code": "EntityTooLarge",
}


class Bucket:
    """A stand-in for the hosted Supabase Storage bucket, which refuses a file over its limit."""

    def __init__(self) -> None:
        self.limit = BUCKET_LIMIT
        self.down = False
        self.objects: dict[str, tuple[bytes, str]] = {}

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        if self.down:
            return httpx2.Response(503)
        if request.method == "GET":
            return httpx2.Response(200, content=self.objects[request.url.path][0])
        if len(request.content) > self.limit:
            return httpx2.Response(400, json=TOO_LARGE)
        self.objects[request.url.path] = (request.content, request.headers["Content-Type"])
        return httpx2.Response(200, json={"Key": request.url.path})


@pytest.fixture
def bucket(staff: TestClient) -> Bucket:
    bucket = Bucket()
    hosted = SupabaseStorage(
        "https://example.supabase.co", "key", "item-photos", httpx2.MockTransport(bucket.handle)
    )
    app.dependency_overrides[get_photo_storage] = lambda: hosted
    return bucket


def phone_photo() -> bytes:
    """A 4119 by 2740 photo that a phone saved on its side, over the bucket's limit as it is."""
    noise = Image.effect_noise((4119, 2740), 50)
    flipped = noise.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    photo = Image.merge("RGB", (noise, flipped, noise.transpose(Image.Transpose.FLIP_TOP_BOTTOM)))
    exif = Image.Exif()
    # Turn it a quarter clockwise to show it upright, as a phone held upright says.
    exif[ExifTags.Base.Orientation] = 6
    output = io.BytesIO()
    photo.save(output, format="JPEG", quality=95, exif=exif)
    return output.getvalue()


def test_a_full_size_phone_photo_is_stored_smaller_and_upright(
    staff: TestClient, session: Session, bucket: Bucket
) -> None:
    photo = phone_photo()
    assert len(photo) > BUCKET_LIMIT
    response = post_item(staff, photo)
    assert response.status_code == 201, response.text
    ((stored, content_type),) = bucket.objects.values()
    assert content_type == "image/jpeg"
    with Image.open(io.BytesIO(stored)) as image:
        assert image.size == (1362, 2048)
    # Sending the same file again still matches it.
    row = session.get_one(Item, UUID(response.json()["id"]))
    assert row.photo_hashes == [hashlib.sha256(photo).hexdigest()]
    # And the card is read from the stored photo.
    add_card(staff, response.json()["id"])


def test_a_photo_the_bucket_still_refuses_is_named_and_no_item_is_made(
    staff: TestClient, session: Session, bucket: Bucket
) -> None:
    small, larger = jpeg(), jpeg((400, 300))
    bucket.limit = len(small)
    response = post_item(staff, small, larger)
    assert response.status_code == 422
    assert response.json()["detail"] == "Photo 2 is too big to store, so choose a smaller copy."
    assert session.exec(select(Item)).all() == []


def test_a_photo_that_cant_be_saved_just_now_is_a_prompt_to_try_again(
    staff: TestClient, session: Session, bucket: Bucket
) -> None:
    bucket.down = True
    response = post_item(staff, jpeg())
    assert response.status_code == 502
    assert response.json()["detail"] == "We couldn't save the photos just now. Try again."
    assert session.exec(select(Item)).all() == []


def test_an_unexpected_error_still_reaches_the_web_app_as_a_message(
    staff: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*args: object) -> None:
        raise RuntimeError("the database went away")

    monkeypatch.setattr(appraisal, "rejected_matches", broken)
    origin = get_settings().cors_origins[0]
    headers = dict(staff.headers) | {"Origin": origin}
    browser = TestClient(app, raise_server_exceptions=False, headers=headers)
    response = post_item(browser, jpeg())
    assert response.status_code == 500
    # Without this header the browser hides the answer, and the page says the API is unreachable.
    assert response.headers["access-control-allow-origin"] == origin
    assert response.json()["detail"] == "Something went wrong on the server. Try again."


def dark_jpeg() -> bytes:
    output = io.BytesIO()
    Image.eval(sharp_photo(), lambda value: value // 8).save(output, format="JPEG")
    return output.getvalue()


def test_a_photo_to_retake_is_a_prompt_and_nothing_is_kept(
    staff: TestClient, session: Session, photo_storage: LocalStorage
) -> None:
    response = post_item(staff, jpeg(), dark_jpeg())
    assert response.status_code == 409
    assert response.json()["detail"] == {
        "kind": "retake",
        "message": "A photo may be hard to price from.",
        "photos": [{"number": 2, "reason": photo_check.TOO_DARK}],
    }
    assert session.exec(select(Item)).all() == []
    assert not photo_storage.root.exists() or not any(photo_storage.root.iterdir())


def test_each_photo_to_retake_is_named(staff: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(appraisal, "photo_retake_reason", lambda data: "It's blurry.")
    response = post_item(staff, jpeg(), jpeg(), jpeg())
    detail = response.json()["detail"]
    assert detail["message"] == "Some photos may be hard to price from."
    assert [photo["number"] for photo in detail["photos"]] == [1, 2, 3]


def test_staff_can_keep_a_photo_the_check_finds_fault_with(
    staff: TestClient, session: Session
) -> None:
    response = post_item(staff, dark_jpeg(), keep_photos=True)
    assert response.status_code == 201, response.text
    assert len(session.get_one(Item, UUID(response.json()["id"])).photo_keys) == 1


def test_the_retake_prompt_comes_before_the_repeat_photo_flag(staff: TestClient) -> None:
    photo = dark_jpeg()
    rejected_id = upload(staff, photo, keep_photos=True)["id"]
    add_card(staff, rejected_id)
    assert decide(staff, rejected_id, appraise(staff, rejected_id)["id"], "no").status_code == 201
    assert post_item(staff, photo).json()["detail"]["kind"] == "retake"
    repeat = post_item(staff, photo, keep_photos=True)
    assert repeat.status_code == 409
    assert repeat.json()["detail"]["kind"] == "repeat_photo"
    assert post_item(staff, photo, keep_photos=True, allow_repeat=True).status_code == 201


def test_a_photo_of_a_rejected_item_is_flagged_and_nothing_is_kept(
    staff: TestClient, session: Session
) -> None:
    photo = jpeg()
    first_id = rejected(staff, jpeg(), photo)
    response = post_item(staff, photo)
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["message"] == "A photo matches an item that was rejected before."
    [match] = detail["matches"]
    item = session.get_one(Item, UUID(first_id))
    assert match["item_id"] == first_id
    assert match["sku"] == item.sku
    assert match["product"] == "canvas jacket"
    assert match["rejection_reason"] == REJECTION["rejection_reason"]
    assert match["destination"] == REJECTION["destination"]
    assert datetime.fromisoformat(match["rejected_at"]).utcoffset() is not None
    assert len(session.exec(select(Item)).all()) == 1


def test_staff_can_take_a_flagged_item_in_anyway(staff: TestClient) -> None:
    photo = jpeg()
    rejected(staff, photo)
    item = upload(staff, photo, allow_repeat=True)
    assert item["status"] == "intake"


def test_a_photo_of_an_item_said_yes_to_is_not_flagged(staff: TestClient) -> None:
    photo = jpeg()
    item_id, appraisal_id = appraised(staff, photo)
    assert decide(staff, item_id, appraisal_id).status_code == 201
    assert post_item(staff, photo).status_code == 201


def test_an_item_said_yes_to_after_a_no_is_not_flagged(staff: TestClient) -> None:
    photo = jpeg()
    item_id, appraisal_id = appraised(staff, photo)
    assert decide(staff, item_id, appraisal_id, "no").status_code == 201
    assert decide(staff, item_id, appraisal_id).status_code == 201
    assert post_item(staff, photo).status_code == 201


def test_a_yes_writes_an_accepted_triage_row(staff: TestClient, session: Session) -> None:
    item_id, appraisal_id = appraised(staff, store_department="electronics_games")
    response = decide(staff, item_id, appraisal_id)
    assert response.status_code == 201, response.text
    assert response.json()["destination"] is None
    [row] = triage_rows(session, item_id)
    decision = session.get_one(Decision, UUID(response.json()["id"]))
    lister = session.exec(select(Profile).where(Profile.username == "staff1")).one()
    assert row.decision_id == decision.id
    assert row.submitted_by == lister.auth_user_id
    assert row.store_department == "electronics_games"
    assert row.outcome == "accepted"
    assert (row.rejection_reason, row.destination) == (None, None)
    assert row.recorded_at == decision.decided_at


def test_a_no_writes_the_reason_and_destination_to_the_triage_log(
    staff: TestClient, session: Session
) -> None:
    item_id, appraisal_id = appraised(staff)
    response = decide(
        staff,
        item_id,
        appraisal_id,
        "no",
        rejection_reason="  Seasonal, try again in spring  ",
        destination="seasonal_storage",
    )
    assert response.status_code == 201, response.text
    assert response.json()["rejection_reason"] == "Seasonal, try again in spring"
    assert response.json()["destination"] == "seasonal_storage"
    [row] = triage_rows(session, item_id)
    assert row.outcome == "rejected"
    assert row.rejection_reason == "Seasonal, try again in spring"
    assert row.destination == "seasonal_storage"
    assert row.store_department == "clothing"


def test_each_decision_adds_a_triage_row(staff: TestClient, session: Session) -> None:
    item_id, appraisal_id = appraised(staff)
    assert decide(staff, item_id, appraisal_id, "no").status_code == 201
    assert decide(staff, item_id, appraisal_id).status_code == 201
    assert [row.outcome for row in triage_rows(session, item_id)] == ["rejected", "accepted"]


def test_the_submitter_is_who_took_the_item_in_not_who_decided(
    staff: TestClient, session: Session
) -> None:
    item_id, appraisal_id = appraised(staff)
    manager = TestClient(app, headers=as_token(MANAGER_TOKEN))
    assert decide(manager, item_id, appraisal_id, "no").status_code == 201
    [row] = triage_rows(session, item_id)
    assert row.submitted_by == session.get_one(Item, UUID(item_id)).lister_id


YES_HAS_NEITHER = "Only a no has a rejection reason and a destination."


@pytest.mark.parametrize(
    ("choice", "body", "message"),
    [
        ("no", {"rejection_reason": None}, "Say why it isn't being listed."),
        ("no", {"rejection_reason": "   "}, "Say why it isn't being listed."),
        ("no", {"destination": None}, "Choose where the item goes instead."),
        ("no", {"rejection_reason": "x" * 201}, "Keep the reason to 200 characters."),
        ("yes", {"rejection_reason": "Worn"}, YES_HAS_NEITHER),
        ("yes", {"destination": "store_floor"}, YES_HAS_NEITHER),
    ],
    ids=["no-reason", "blank-reason", "no-destination", "long-reason", "yes-reason", "yes-place"],
)
def test_a_no_needs_a_reason_and_destination_and_a_yes_has_neither(
    staff: TestClient, session: Session, choice: str, body: dict[str, Any], message: str
) -> None:
    item_id, appraisal_id = appraised(staff)
    response = decide(staff, item_id, appraisal_id, choice, **body)
    assert response.status_code == 422
    assert response.json()["detail"] == message
    assert session.exec(select(Decision)).all() == []
    assert triage_rows(session, item_id) == []


def test_a_destination_must_be_known(staff: TestClient) -> None:
    item_id, appraisal_id = appraised(staff)
    assert decide(staff, item_id, appraisal_id, "no", destination="dumpster").status_code == 422


def test_recent_decisions_show_where_a_rejected_item_went(staff: TestClient) -> None:
    yes_id, yes_appraisal = appraised(staff)
    assert decide(staff, yes_id, yes_appraisal).status_code == 201
    no_id = rejected(staff)
    destinations = {row["item_id"]: row["destination"] for row in staff.get("/decisions").json()}
    assert destinations == {yes_id: None, no_id: "store_floor"}


def intake_migration() -> ModuleType:
    path = next(VERSIONS.glob("*_add_intake_skus_photo_hashes_and_triage_log.py"))
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


@pytest.mark.parametrize("name", ["Rosa María Torres", "Staff1", "Q", "李明", "Jean-Luc Picard"])
def test_the_migration_takes_initials_the_way_intake_does(name: str) -> None:
    assert intake_migration()._initials(name) == initials(name)


def test_the_migration_gives_placeholder_skus_real_ones_and_carries_the_counts_on(
    connection: Connection,
) -> None:
    rosa = test_schema.add_profile(connection, "rosa", display_name="Rosa María Torres")
    rob = test_schema.add_profile(connection, "rob", display_name="Rob Tate")

    def item(lister: UUID, sku: str, created_at: str) -> UUID:
        return test_schema.add_item(connection, lister, sku=sku, created_at=created_at)

    # A real SKU kept from before a downgrade, whose number stays taken.
    item(rob, "RT10272601", "2026-10-27T15:00:00Z")
    placeholders = {
        "late": item(rosa, "PLACEHOLDER-3", "2026-10-28T03:00:00Z"),
        "first": item(rosa, "PLACEHOLDER-1", "2026-10-27T16:00:00Z"),
        "next": item(rob, "PLACEHOLDER-2", "2026-10-27T17:00:00Z"),
        "day": item(rosa, "PLACEHOLDER-4", "2026-10-28T15:00:00Z"),
    }
    with Operations.context(MigrationContext.configure(connection)):
        intake_migration()._give_real_skus()
    skus = {
        name: connection.execute(
            sa.text("SELECT sku FROM items WHERE id = :id"), {"id": item_id}
        ).scalar_one()
        for name, item_id in placeholders.items()
    }
    # 03:00 UTC on the 28th is still the evening of the 27th in Kansas City.
    assert skus == {
        "first": "RT10272602",
        "next": "RT10272603",
        "late": "RT10272604",
        "day": "RT10282601",
    }
    counts = connection.execute(sa.text("SELECT prefix, last_value FROM sku_sequences")).all()
    assert dict(counts) == {"RT102726": 4, "RT102826": 1}
