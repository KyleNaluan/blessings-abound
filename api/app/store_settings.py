"""The values the Settings page keeps out of code, and the manager-only routes that change them.

Each section is one row of `settings`, checked by its model here on every write. A section with no
row reads as its default, which is the value the migration seeded. Where each default comes from is
in docs/settings.md.
"""

from datetime import UTC, datetime
from enum import StrEnum
from itertools import pairwise
from typing import Annotated, Any, Self

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, BeforeValidator, ConfigDict, ValidationError, model_validator
from sqlmodel import Session, col, select

from app.auth import ManagerProfile
from app.db import get_session
from app.models import Category, Profile, SettingKey, StoreSetting
from app.settings import PricingRules, get_settings

router = APIRouter(prefix="/settings")

SessionDep = Annotated[Session, Depends(get_session)]

# The pricing values on the Settings page start from the numbers the pipeline was tuned with.
_TUNED = PricingRules()
MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
STALE = (
    "Another manager changed these settings after you opened the page. Reload the page to see "
    "their change, then make yours again."
)


class Section(BaseModel):
    # A misspelled field is refused rather than dropped, so a save never loses a value quietly.
    model_config = ConfigDict(extra="forbid", frozen=True)


def _inches(value: float) -> str:
    """12.0 as 12 and 15.5 as 15.5, the way box sizes are written."""
    return f"{value:g}"


class PackageKind(StrEnum):
    BOX = "box"
    MAILER = "mailer"


class BoxSize(Section):
    """A standard box, measured L x W x H, or a flat mailer, measured W x L."""

    kind: PackageKind
    length_in: float
    width_in: float
    height_in: float | None = None

    @property
    def code(self) -> str:
        """The size as it is written on the box, which #42 adds to the SKU."""
        if self.height_in is None:
            return f"{_inches(self.width_in)}x{_inches(self.length_in)}"
        return f"{_inches(self.length_in)}x{_inches(self.width_in)}x{_inches(self.height_in)}"

    @model_validator(mode="after")
    def check_sides(self) -> Self:
        sides = [self.length_in, self.width_in]
        if self.kind is PackageKind.BOX:
            if self.height_in is None:
                raise ValueError("A box needs a height.")
            sides.append(self.height_in)
        elif self.height_in is not None:
            raise ValueError("A mailer is flat, so leave its height empty.")
        if any(side <= 0 for side in sides):
            raise ValueError("Every side has to be more than 0 inches.")
        if any((side * 4) % 1 for side in sides):
            raise ValueError("Measure every side to the nearest quarter inch.")
        if self.kind is PackageKind.BOX and self.width_in > self.length_in:
            flipped = f"{_inches(self.width_in)}x{_inches(self.length_in)}"
            raise ValueError(
                f"Write the {self.code} box as {flipped}x{_inches(self.height_in or 0)}, with the "
                "longer side of the opening first."
            )
        return self

    def length_plus_girth_in(self) -> float:
        """USPS's size measure: the longest side plus the distance around the other two."""
        sides = sorted((self.length_in, self.width_in, self.height_in or 0), reverse=True)
        return sides[0] + 2 * (sides[1] + sides[2])


def _default_boxes() -> list[BoxSize]:
    # Uline's stock 200 lb test boxes and the common poly mailer sizes, see docs/settings.md.
    return [
        BoxSize(kind=PackageKind.MAILER, width_in=10, length_in=13),
        BoxSize(kind=PackageKind.MAILER, width_in=12, length_in=15.5),
        BoxSize(kind=PackageKind.MAILER, width_in=14.5, length_in=19),
        BoxSize(kind=PackageKind.BOX, length_in=8, width_in=6, height_in=4),
        BoxSize(kind=PackageKind.BOX, length_in=10, width_in=8, height_in=6),
        BoxSize(kind=PackageKind.BOX, length_in=12, width_in=12, height_in=6),
        BoxSize(kind=PackageKind.BOX, length_in=16, width_in=12, height_in=8),
    ]


class BoxSizes(Section):
    boxes: list[BoxSize]

    @model_validator(mode="after")
    def check_list(self) -> Self:
        if not any(box.kind is PackageKind.BOX for box in self.boxes):
            raise ValueError("Keep at least one box, because an item can't be stored without one.")
        codes = [box.code for box in self.boxes]
        for code in codes:
            if codes.count(code) > 1:
                raise ValueError(f"{code} is in the list twice.")
        return self


def _clean_words(value: Any) -> Any:
    if isinstance(value, list):
        return [word.strip().lower() if isinstance(word, str) else word for word in value]
    return value


def _strip(value: Any) -> Any:
    return value.strip() if isinstance(value, str) else value


class Season(Section):
    """Items of one kind, and the months worth listing them in. Other months hold them."""

    name: Annotated[str, BeforeValidator(_strip)]
    category: Category
    # Words in the item card that mark an item as this kind, such as coat or parka.
    match_words: Annotated[list[str], BeforeValidator(_clean_words)]
    months: list[int]

    @model_validator(mode="after")
    def check_season(self) -> Self:
        if not self.name:
            raise ValueError("Every season needs a name.")
        label = f'"{self.name}"'
        if not self.match_words or not all(self.match_words):
            raise ValueError(f"{label} needs at least one word to match, with no empty words.")
        if len(set(self.match_words)) < len(self.match_words):
            raise ValueError(f"{label} lists the same word twice.")
        if not self.months:
            raise ValueError(f"{label} needs at least one month to list in.")
        if any(month < 1 or month > 12 for month in self.months):
            raise ValueError(f"{label} has a month that isn't 1 to 12.")
        if len(set(self.months)) < len(self.months):
            raise ValueError(f"{label} lists the same month twice.")
        if len(self.months) == 12:
            raise ValueError(
                f"{label} is listed in every month, so it never holds an item. Remove it instead."
            )
        return self


def _season(name: str, words: list[str], months: list[int]) -> Season:
    return Season(name=name, category=Category.APPAREL, match_words=words, months=months)


def _default_seasons() -> list[Season]:
    # Written for Kansas City from published resale guides and NOAA normals, see docs/settings.md.
    # The narrower seasons come first, so a holiday sweater isn't read as any sweater.
    return [
        _season("Halloween costumes", ["costume", "halloween"], [8, 9, 10]),
        _season("Holiday sweaters", ["christmas", "ugly sweater", "holiday"], [10, 11, 12]),
        _season("Football gear", ["football", "nfl", "chiefs"], [8, 9, 10, 11, 12, 1]),
        _season(
            "Coats and jackets",
            ["coat", "jacket", "parka", "puffer", "peacoat", "overcoat"],
            [8, 9, 10, 11, 12, 1],
        ),
        _season("Sweaters", ["sweater", "cardigan", "turtleneck", "fleece"], [9, 10, 11, 12, 1, 2]),
        _season("Boots", ["boot"], [9, 10, 11, 12, 1]),
        _season("Swimwear", ["swimsuit", "swim", "bikini"], [3, 4, 5, 6, 7]),
        _season("Shorts", ["shorts"], [3, 4, 5, 6, 7, 8]),
        _season("Sandals", ["sandal", "flip flop"], [3, 4, 5, 6, 7]),
    ]


class SeasonalCalendar(Section):
    """An item that matches no season can be listed in any month."""

    seasons: list[Season]

    @model_validator(mode="after")
    def check_names(self) -> Self:
        names = [season.name.lower() for season in self.seasons]
        for season in self.seasons:
            if names.count(season.name.lower()) > 1:
                raise ValueError(f'"{season.name}" is in the calendar twice.')
        return self


class WorthListing(Section):
    threshold_cents: int

    @model_validator(mode="after")
    def check_threshold(self) -> Self:
        if self.threshold_cents <= 0:
            raise ValueError("The worth-listing price has to be more than $0.")
        return self


class Fees(Section):
    """What a sale costs on Channel A, which is also what the worth-listing net subtracts."""

    fee_rate: float
    per_order_fee_cents: int
    supplies_cents: int

    @model_validator(mode="after")
    def check_fees(self) -> Self:
        if not 0 <= self.fee_rate < 1:
            raise ValueError("The fee rate has to be at least 0% and under 100%.")
        if self.per_order_fee_cents < 0 or self.supplies_cents < 0:
            raise ValueError("The per-order fee and the supplies can't be below $0.")
        return self


MAX_ASK_TO_SALE = 2.0


class AskToSale(Section):
    """The share of an asking price expected at sale, one factor per category."""

    apparel: float
    electronics_games: float

    @model_validator(mode="after")
    def check_factors(self) -> Self:
        for factor in (self.apparel, self.electronics_games):
            if not 0 < factor <= MAX_ASK_TO_SALE:
                raise ValueError(
                    f"An ask-to-sale factor has to be more than 0 and at most {MAX_ASK_TO_SALE:g}."
                )
        return self


class ShippingWeight(Section):
    """USPS Ground Advantage's rules, which the weight a manager enters in #42 is held to."""

    # Up to the last tier, a weight rounds up to the next tier, and past it to the next pound.
    ounce_tiers_oz: list[float]
    max_weight_oz: int
    max_length_plus_girth_in: float
    # Past this many cubic inches, a box pays for its size when that is more than its weight.
    dim_weight_min_cubic_in: int
    dim_weight_divisor: int

    @model_validator(mode="after")
    def check_rules(self) -> Self:
        tiers = self.ounce_tiers_oz
        if not tiers or tiers[0] <= 0 or any(b <= a for a, b in pairwise(tiers)):
            raise ValueError("The ounce tiers have to be above 0 and go from smallest to largest.")
        if tiers[-1] >= 16:
            raise ValueError("The last ounce tier has to be under 16 oz, where pound prices start.")
        if self.max_weight_oz <= tiers[-1]:
            raise ValueError("The weight limit has to be above the last ounce tier.")
        if self.max_length_plus_girth_in <= 0:
            raise ValueError("The length plus girth limit has to be more than 0 inches.")
        if self.dim_weight_min_cubic_in < 0 or self.dim_weight_divisor <= 0:
            raise ValueError(
                "The size-based weight needs a starting volume of at least 0 and a divisor above 0."
            )
        return self


class StoreSettings(BaseModel):
    """Every section at once, which is how the sections are checked against each other.

    The defaults are what a section reads as with no row, and what the migration seeded. A section's
    own fields have none, so a save that leaves a field out is refused rather than reset.
    """

    model_config = ConfigDict(frozen=True)

    box_sizes: BoxSizes = BoxSizes(boxes=_default_boxes())
    seasonal_calendar: SeasonalCalendar = SeasonalCalendar(seasons=_default_seasons())
    worth_listing: WorthListing = WorthListing(threshold_cents=_TUNED.worth_listing_threshold_cents)
    fees: Fees = Fees(
        fee_rate=_TUNED.fee_rate,
        per_order_fee_cents=_TUNED.per_order_fee_cents,
        supplies_cents=_TUNED.supplies_cents,
    )
    ask_to_sale: AskToSale = AskToSale(
        apparel=_TUNED.ask_to_sale_factor, electronics_games=_TUNED.games_ask_to_sale_factor
    )
    # USPS Ground Advantage: ounce tiers up to 15.999 oz, then pounds up to 70 lb.
    shipping_weight: ShippingWeight = ShippingWeight(
        ounce_tiers_oz=[4, 8, 12, 15.999],
        max_weight_oz=70 * 16,
        max_length_plus_girth_in=130,
        dim_weight_min_cubic_in=1728,
        dim_weight_divisor=139,
    )

    @model_validator(mode="after")
    def boxes_can_ship(self) -> Self:
        limit = self.shipping_weight.max_length_plus_girth_in
        for box in self.box_sizes.boxes:
            if box.kind is PackageKind.BOX and box.length_plus_girth_in() > limit:
                raise ValueError(
                    f"The {box.code} box measures {box.length_plus_girth_in():g} inches in length "
                    f"plus girth, which is over the {limit:g} inch shipping limit."
                )
        return self


def _stored_values(rows: list[StoreSetting]) -> dict[str, Any]:
    return {row.key.value: row.value for row in rows}


def read_store_settings(session: Session) -> StoreSettings:
    """The current values, with any section that has no row at its default."""
    return StoreSettings.model_validate(_stored_values(list(session.exec(select(StoreSetting)))))


def pricing_rules(session: Session) -> PricingRules:
    """The pipeline's rules, with the values a manager can change taken from Settings."""
    current = read_store_settings(session)
    return get_settings().pricing.model_copy(
        update={
            "worth_listing_threshold_cents": current.worth_listing.threshold_cents,
            "fee_rate": current.fees.fee_rate,
            "per_order_fee_cents": current.fees.per_order_fee_cents,
            "supplies_cents": current.fees.supplies_cents,
            "ask_to_sale_factor": current.ask_to_sale.apparel,
            "games_ask_to_sale_factor": current.ask_to_sale.electronics_games,
        }
    )


class SectionRead[T: Section](BaseModel):
    value: T
    # When the row was last written, which a save sends back, or empty when there is no row.
    updated_at: datetime | None
    # Empty while the section still holds the value the migration seeded.
    updated_by_name: str | None


class BoxSizesRead(SectionRead[BoxSizes]):
    pass


class SeasonalCalendarRead(SectionRead[SeasonalCalendar]):
    pass


class WorthListingRead(SectionRead[WorthListing]):
    pass


class FeesRead(SectionRead[Fees]):
    pass


class AskToSaleRead(SectionRead[AskToSale]):
    pass


class ShippingWeightRead(SectionRead[ShippingWeight]):
    pass


class SettingsRead(BaseModel):
    box_sizes: BoxSizesRead
    seasonal_calendar: SeasonalCalendarRead
    worth_listing: WorthListingRead
    fees: FeesRead
    ask_to_sale: AskToSaleRead
    shipping_weight: ShippingWeightRead


class SectionUpdate[T: Section](BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: T
    # The updated_at the page loaded, so a save can't undo another manager's change unseen.
    expected_updated_at: datetime | None


class BoxSizesUpdate(SectionUpdate[BoxSizes]):
    pass


class SeasonalCalendarUpdate(SectionUpdate[SeasonalCalendar]):
    pass


class WorthListingUpdate(SectionUpdate[WorthListing]):
    pass


class FeesUpdate(SectionUpdate[Fees]):
    pass


class AskToSaleUpdate(SectionUpdate[AskToSale]):
    pass


class ShippingWeightUpdate(SectionUpdate[ShippingWeight]):
    pass


class BoxSizeOption(BaseModel):
    """One choice in a box size list, with the size written out as it goes on the SKU."""

    code: str
    kind: PackageKind
    length_in: float
    width_in: float
    height_in: float | None


def _settings_page(session: Session) -> SettingsRead:
    rows = session.exec(
        select(StoreSetting, Profile.display_name).outerjoin(
            Profile, col(StoreSetting.updated_by) == col(Profile.auth_user_id)
        )
    ).all()
    current = StoreSettings.model_validate(_stored_values([row for row, _ in rows]))
    stored = {row.key: (row.updated_at, name) for row, name in rows}

    def section(key: SettingKey) -> dict[str, Any]:
        updated_at, name = stored.get(key, (None, None))
        return {
            "value": getattr(current, key.value),
            "updated_at": updated_at,
            "updated_by_name": name,
        }

    return SettingsRead.model_validate({key.value: section(key) for key in SettingKey})


def _save(session: Session, manager: Profile, key: SettingKey, update: SectionUpdate[Any]) -> None:
    # Every row is locked, so a section checked against the others can't race a change to them.
    rows = list(
        session.exec(select(StoreSetting).order_by(col(StoreSetting.key)).with_for_update())
    )
    row = next((row for row in rows if row.key is key), None)
    if (row.updated_at if row else None) != update.expected_updated_at:
        raise HTTPException(status.HTTP_409_CONFLICT, STALE)
    value = update.value.model_dump(mode="json")
    try:
        StoreSettings.model_validate(_stored_values(rows) | {key.value: value})
    except ValidationError as error:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            [
                {"loc": ["body", "value"], "msg": problem["msg"], "type": problem["type"]}
                for problem in error.errors(include_url=False)
            ],
        ) from error
    if row is None:
        row = StoreSetting(key=key, value=value)
    else:
        row.value = value
    row.updated_by = manager.auth_user_id
    # Stamped here rather than by now(), which repeats within a transaction, so every save moves the
    # time a stale page is caught by.
    row.updated_at = datetime.now(UTC)
    session.add(row)
    session.commit()


@router.get("", operation_id="get_settings")
def get_settings_page(manager: ManagerProfile, session: SessionDep) -> SettingsRead:
    return _settings_page(session)


@router.get("/box-sizes", operation_id="list_box_sizes")
def list_box_sizes(manager: ManagerProfile, session: SessionDep) -> list[BoxSizeOption]:
    """The box size choices, in the order the Settings page lists them."""
    return [
        BoxSizeOption(code=box.code, **box.model_dump())
        for box in read_store_settings(session).box_sizes.boxes
    ]


@router.get("/seasonal-calendar", operation_id="get_seasonal_calendar")
def get_seasonal_calendar(manager: ManagerProfile, session: SessionDep) -> SeasonalCalendar:
    return read_store_settings(session).seasonal_calendar


@router.put("/box-sizes", operation_id="save_box_sizes")
def save_box_sizes(
    update: BoxSizesUpdate, manager: ManagerProfile, session: SessionDep
) -> SettingsRead:
    _save(session, manager, SettingKey.BOX_SIZES, update)
    return _settings_page(session)


@router.put("/seasonal-calendar", operation_id="save_seasonal_calendar")
def save_seasonal_calendar(
    update: SeasonalCalendarUpdate, manager: ManagerProfile, session: SessionDep
) -> SettingsRead:
    _save(session, manager, SettingKey.SEASONAL_CALENDAR, update)
    return _settings_page(session)


@router.put("/worth-listing", operation_id="save_worth_listing")
def save_worth_listing(
    update: WorthListingUpdate, manager: ManagerProfile, session: SessionDep
) -> SettingsRead:
    _save(session, manager, SettingKey.WORTH_LISTING, update)
    return _settings_page(session)


@router.put("/fees", operation_id="save_fees")
def save_fees(update: FeesUpdate, manager: ManagerProfile, session: SessionDep) -> SettingsRead:
    _save(session, manager, SettingKey.FEES, update)
    return _settings_page(session)


@router.put("/ask-to-sale", operation_id="save_ask_to_sale")
def save_ask_to_sale(
    update: AskToSaleUpdate, manager: ManagerProfile, session: SessionDep
) -> SettingsRead:
    _save(session, manager, SettingKey.ASK_TO_SALE, update)
    return _settings_page(session)


@router.put("/shipping-weight", operation_id="save_shipping_weight")
def save_shipping_weight(
    update: ShippingWeightUpdate, manager: ManagerProfile, session: SessionDep
) -> SettingsRead:
    _save(session, manager, SettingKey.SHIPPING_WEIGHT, update)
    return _settings_page(session)
