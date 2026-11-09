"""Intake: the SKU, the photo checks and the repeat photo guard behind `POST /items`.

The SKU is the lister's initials, the store's date and that day's sequence for those initials,
such as RT10272601 for the first item RT took in on October 27, 2026. The box-size suffix is added
later, when a manager packs the item.
"""

import hashlib
import io
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from PIL import Image, ImageOps
from pydantic import BaseModel
from sqlalchemy.dialects.postgresql import ARRAY, distinct_on, insert
from sqlmodel import Session, col

from app.models import (
    Destination,
    Item,
    ItemCard,
    SkuSequence,
    TriageEntry,
    TriageOutcome,
)

# Blessings Abound's stores are in Kansas City, so a day's sequence starts at the store's midnight.
STORE_TIMEZONE = ZoneInfo("America/Chicago")
# Phone photos run to about 12 MB at most, so 15 MB leaves room without letting in anything huge.
MAX_PHOTO_BYTES = 15 * 1024 * 1024
MAX_PHOTO_MB = MAX_PHOTO_BYTES // (1024 * 1024)
# The formats the vision step can open, by Pillow's name for each, and the type each is stored as.
PHOTO_TYPES = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
# A photo is stored at most this many pixels on its long side, which is still more than the photo
# check and the vision model use. A full-size phone photo can be over the hosted bucket's 10 MB
# limit, and one this size is at most a few MB.
STORED_LONG_SIDE = 2048
# A photo within that size but bigger than this is shrunk too, in case it is a heavy PNG.
STORED_MAX_BYTES = 4 * 1024 * 1024
STORED_JPEG_QUALITY = 90
# Used when a name has no letters to take initials from.
NO_INITIALS = "XX"


def get_now() -> datetime:
    """The time of the intake, a dependency so tests can pick the day."""
    return datetime.now(UTC)


def initials(name: str) -> str:
    """Two capital letters from a person's name, for the start of their SKUs.

    The first letters of the first and last words, so "Rosa Maria Torres" is RT. A one-word name
    gives its first two letters, and accents are dropped, so "Ángel" is AN. Two people with the
    same initials share them, and their items still get different SKUs, see `next_sku`.
    """
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    words = re.findall(r"[A-Za-z]+", folded)
    if not words:
        return NO_INITIALS
    letters = (words[0] + NO_INITIALS)[:2] if len(words) == 1 else words[0][0] + words[-1][0]
    return letters.upper()


def store_date(now: datetime) -> date:
    return now.astimezone(STORE_TIMEZONE).date()


def sku_prefix(person_initials: str, day: date) -> str:
    return f"{person_initials}{day:%m%d%y}"


def next_sku(session: Session, prefix: str) -> str:
    """The next SKU for the prefix, numbered from 01 within the day.

    The count is kept per prefix in `sku_sequences`, and bumping it locks that row until the
    transaction ends, so two intakes at once wait for each other and never share a number, and an
    intake that fails rolls its number back. Past 99 the number grows to three digits.
    """
    statement = (
        insert(SkuSequence)
        .values(prefix=prefix, last_value=1)
        .on_conflict_do_update(
            index_elements=[col(SkuSequence.prefix)],
            set_={"last_value": col(SkuSequence.last_value) + 1},
        )
        .returning(col(SkuSequence.last_value))
    )
    value = session.connection().execute(statement).scalar_one()
    return f"{prefix}{value:02d}"


class PhotoError(ValueError):
    """A photo that can't be taken in, with the message to show staff."""


@dataclass(frozen=True)
class CheckedPhoto:
    data: bytes
    content_type: str
    sha256: str


def check_photo(data: bytes, number: int) -> CheckedPhoto:
    """Refuse an empty, oversized or unreadable photo, and fingerprint and size the rest.

    The type comes from the file's own bytes rather than its name or the browser's label, so a PDF
    renamed to .jpg is refused too. `data` may be one byte over the limit, which is how a caller
    reading at most that much learns the photo is too big. The fingerprint is of the photo as sent,
    so sending the same file again matches whether or not it was shrunk for storage.
    """
    if not data:
        raise PhotoError(f"Photo {number} is empty.")
    if len(data) > MAX_PHOTO_BYTES:
        raise PhotoError(f"Photo {number} is over {MAX_PHOTO_MB} MB, so choose a smaller copy.")
    try:
        with Image.open(io.BytesIO(data), formats=list(PHOTO_TYPES)) as image:
            kind = image.format
            image.verify()
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError) as error:
        raise PhotoError(f"Photo {number} isn't a JPEG, PNG or WebP image.") from error
    assert kind in PHOTO_TYPES
    sha256 = hashlib.sha256(data).hexdigest()
    try:
        stored = _shrunk_for_storage(data)
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError) as error:
        raise PhotoError(f"Photo {number} isn't a JPEG, PNG or WebP image.") from error
    if stored is None:
        return CheckedPhoto(data, PHOTO_TYPES[kind], sha256)
    return CheckedPhoto(stored, "image/jpeg", sha256)


def _shrunk_for_storage(data: bytes) -> bytes | None:
    """An upright JPEG of a photo too big to store as it is, or None for one that fits."""
    with Image.open(io.BytesIO(data)) as image:
        if max(image.size) <= STORED_LONG_SIDE and len(data) <= STORED_MAX_BYTES:
            return None
        # Scaling before anything else lets Pillow decode a large JPEG at a fraction of its size.
        image.thumbnail((STORED_LONG_SIDE, STORED_LONG_SIDE))
        # The EXIF orientation isn't kept in the new file, so the turn it asks for is made here.
        upright = ImageOps.exif_transpose(image).convert("RGB")
    output = io.BytesIO()
    upright.save(output, format="JPEG", quality=STORED_JPEG_QUALITY)
    return output.getvalue()


class RejectedMatch(BaseModel):
    """An earlier item with one of the same photos, whose latest triage call was a rejection."""

    item_id: UUID
    sku: str
    brand: str | None
    product: str | None
    rejection_reason: str
    destination: Destination
    rejected_at: datetime


def rejected_matches(session: Session, hashes: list[str]) -> list[RejectedMatch]:
    """The rejected items that share a photo with these, newest rejection first.

    An item counts only while its latest triage row is a rejection, so one that staff said yes to
    again is not flagged.
    """
    latest = (
        sa.select(
            col(TriageEntry.item_id),
            col(TriageEntry.outcome),
            col(TriageEntry.rejection_reason),
            col(TriageEntry.destination),
            col(TriageEntry.recorded_at),
        )
        .ext(distinct_on(col(TriageEntry.item_id)))
        .order_by(
            col(TriageEntry.item_id), col(TriageEntry.recorded_at).desc(), col(TriageEntry.id)
        )
        .subquery()
    )
    query = (
        sa.select(
            col(Item.id).label("item_id"),
            col(Item.sku),
            col(ItemCard.brand),
            col(ItemCard.product),
            latest.c.rejection_reason,
            latest.c.destination,
            latest.c.recorded_at.label("rejected_at"),
        )
        .join(latest, latest.c.item_id == col(Item.id))
        .outerjoin(ItemCard, col(ItemCard.item_id) == col(Item.id))
        # Shares at least one hash, which the GIN index on the column answers.
        .where(col(Item.photo_hashes).op("&&")(sa.literal(hashes, ARRAY(sa.Text))))
        .where(latest.c.outcome == TriageOutcome.REJECTED)
        .order_by(latest.c.recorded_at.desc(), col(Item.id))
    )
    rows = session.connection().execute(query).mappings()
    return [RejectedMatch.model_validate(dict(row)) for row in rows]
