"""The Settings page's values, its manager-only routes, and the pricing that reads them."""

import importlib.util
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.appraisal import get_photo_storage
from app.auth import get_token_verifier
from app.db import get_session
from app.main import app
from app.models import Role, SettingKey, StoreSetting
from app.settings import PricingRules, get_settings
from app.storage import LocalStorage
from app.store_settings import STALE, StoreSettings, pricing_rules, read_store_settings
from tests.test_appraisal import (
    MANAGER_TOKEN,
    STAFF_TOKEN,
    StubVerifier,
    add_card,
    add_profile,
    appraise,
    as_token,
    listings,
    model_replies,
    upload,
    use_search,
)

VERSIONS = Path(__file__).parents[1] / "alembic" / "versions"
# Each migration that adds a section seeds a frozen copy of its default.
SEEDING_MIGRATIONS = [
    next(VERSIONS.glob("*_add_settings_table.py")),
    next(VERSIONS.glob("*_add_manager_approval_and_storage.py")),
]
DEFAULTS = StoreSettings().model_dump(mode="json")
SHIPPING = DEFAULTS["shipping_weight"]

SECTIONS = {
    "box_sizes": "/settings/box-sizes",
    "seasonal_calendar": "/settings/seasonal-calendar",
    "worth_listing": "/settings/worth-listing",
    "fees": "/settings/fees",
    "ask_to_sale": "/settings/ask-to-sale",
    "shipping_weight": "/settings/shipping-weight",
    "channel_b_fees": "/settings/channel-b-fees",
}
CHANGED = {
    "box_sizes": {
        "boxes": [{"kind": "box", "length_in": 14.25, "width_in": 10, "height_in": 4}],
    },
    "seasonal_calendar": {
        "seasons": [
            {"name": "Coats", "category": "apparel", "match_words": ["coat"], "months": [10, 11]}
        ]
    },
    "worth_listing": {"threshold_cents": 2500},
    "fees": {"fee_rate": 0.15, "per_order_fee_cents": 30, "supplies_cents": 200},
    "ask_to_sale": {"apparel": 0.7, "electronics_games": 0.9},
    "shipping_weight": SHIPPING | {"max_length_plus_girth_in": 108},
    "channel_b_fees": {
        "fee_rate": 0.25,
        "small_sale_fee_cents": 300,
        "small_sale_below_cents": 2000,
        "supplies_cents": 100,
    },
}
CHANNEL_B = DEFAULTS["channel_b_fees"]


@pytest.fixture
def client(session: Session, tmp_path: Path) -> Iterator[TestClient]:
    tokens = {
        STAFF_TOKEN: add_profile(session, "staff1"),
        MANAGER_TOKEN: add_profile(session, "manager1", Role.MANAGER),
    }
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_photo_storage] = lambda: LocalStorage(tmp_path)
    app.dependency_overrides[get_token_verifier] = lambda: StubVerifier(tokens)
    yield TestClient(app, headers=as_token(MANAGER_TOKEN))
    app.dependency_overrides.clear()


def load_page(client: TestClient) -> dict[str, Any]:
    response = client.get("/settings")
    assert response.status_code == 200, response.text
    return response.json()


def save(client: TestClient, section: str, value: Any, expected: str | None = None) -> Any:
    return client.put(SECTIONS[section], json={"value": value, "expected_updated_at": expected})


def saved(client: TestClient, section: str, value: Any) -> dict[str, Any]:
    current = load_page(client)[section]["updated_at"]
    response = save(client, section, value, current)
    assert response.status_code == 200, response.text
    return response.json()


def problems(response: Any) -> list[str]:
    assert response.status_code == 422, response.text
    return [problem["msg"] for problem in response.json()["detail"]]


def test_a_manager_sees_every_section_at_its_default(client: TestClient) -> None:
    page = load_page(client)
    assert {key: section["value"] for key, section in page.items()} == DEFAULTS
    assert all(section["updated_at"] is None for section in page.values())
    assert all(section["updated_by_name"] is None for section in page.values())


def test_the_migrations_seed_the_defaults() -> None:
    seeded: dict[str, Any] = {}
    for path in SEEDING_MIGRATIONS:
        spec = importlib.util.spec_from_file_location(path.stem, path)
        assert spec is not None and spec.loader is not None
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        assert not set(migration.SEED) & set(seeded)
        seeded |= migration.SEED
    assert seeded == DEFAULTS
    assert set(seeded) == {key.value for key in SettingKey}


def test_seeded_rows_read_as_the_defaults(session: Session) -> None:
    for key, value in DEFAULTS.items():
        session.add(StoreSetting(key=SettingKey(key), value=value))
    session.commit()
    assert read_store_settings(session) == StoreSettings()


def test_the_pricing_defaults_are_the_numbers_the_pipeline_was_tuned_with(
    session: Session,
) -> None:
    assert pricing_rules(session) == PricingRules() == get_settings().pricing


@pytest.mark.parametrize("section", list(SECTIONS))
def test_a_manager_can_change_each_section(client: TestClient, section: str) -> None:
    page = saved(client, section, CHANGED[section])
    assert page[section]["value"] == CHANGED[section]
    assert page[section]["updated_by_name"] == "Manager1"
    assert page[section]["updated_at"] is not None
    assert load_page(client)[section] == page[section]
    others = {key for key in SECTIONS if key != section}
    assert all(page[key]["value"] == DEFAULTS[key] for key in others)


READS = ["/settings", "/settings/box-sizes", "/settings/seasonal-calendar"]
ROUTES = [("get", path) for path in READS] + [("put", path) for path in SECTIONS.values()]


@pytest.mark.parametrize(("method", "path"), ROUTES)
def test_staff_cannot_read_or_change_settings(
    client: TestClient, session: Session, method: str, path: str
) -> None:
    body = {"value": {}, "expected_updated_at": None} if method == "put" else None
    response = client.request(method, path, json=body, headers=as_token(STAFF_TOKEN))
    assert response.status_code == 403
    assert response.json()["detail"] == "Only a manager can do this."
    assert TestClient(app).request(method, path, json=body).status_code == 401
    assert session.exec(select(StoreSetting)).all() == []


def box(length: float, width: float, height: float | None = None) -> dict[str, Any]:
    kind = "mailer" if height is None else "box"
    return {"kind": kind, "length_in": length, "width_in": width, "height_in": height}


def season(**changes: Any) -> dict[str, Any]:
    coats = {"name": "Coats", "category": "apparel", "match_words": ["coat"], "months": [10]}
    return coats | changes


@pytest.mark.parametrize(
    ("section", "value", "message"),
    [
        ("box_sizes", {"boxes": [box(10, 8)]}, "Keep at least one box"),
        ("box_sizes", {"boxes": [box(10, 8, 6), box(10, 8, 6)]}, "10x8x6 is in the list twice."),
        ("box_sizes", {"boxes": [box(10, 8, None) | {"kind": "box"}]}, "A box needs a height."),
        ("box_sizes", {"boxes": [box(10, 8, 6), box(13, 10) | {"height_in": 2}]}, "flat"),
        ("box_sizes", {"boxes": [box(10, 0, 6)]}, "more than 0 inches"),
        ("box_sizes", {"boxes": [box(10.3, 8, 6)]}, "nearest quarter inch"),
        ("box_sizes", {"boxes": [box(8, 10, 6)]}, "Write the 8x10x6 box as 10x8x6"),
        ("box_sizes", {"boxes": [box(60, 30, 20)]}, "over the 130 inch shipping limit"),
        ("seasonal_calendar", {"seasons": [season(name=" ")]}, "Every season needs a name."),
        ("seasonal_calendar", {"seasons": [season(match_words=[])]}, "at least one word"),
        ("seasonal_calendar", {"seasons": [season(match_words=["coat", " Coat"])]}, "same word"),
        ("seasonal_calendar", {"seasons": [season(months=[])]}, "at least one month"),
        ("seasonal_calendar", {"seasons": [season(months=[13])]}, "isn't 1 to 12"),
        ("seasonal_calendar", {"seasons": [season(months=[10, 10])]}, "same month twice"),
        ("seasonal_calendar", {"seasons": [season(months=list(range(1, 13)))]}, "every month"),
        ("seasonal_calendar", {"seasons": [season(), season(name="coats")]}, "twice"),
        ("seasonal_calendar", {"seasons": [season(category="books")]}, "apparel"),
        ("worth_listing", {"threshold_cents": 0}, "more than $0"),
        ("fees", {"fee_rate": 1, "per_order_fee_cents": 40, "supplies_cents": 150}, "under 100%"),
        ("fees", {"fee_rate": 0.1, "per_order_fee_cents": -1, "supplies_cents": 150}, "below $0"),
        ("ask_to_sale", {"apparel": 0, "electronics_games": 0.94}, "more than 0 and at most 2"),
        ("ask_to_sale", {"apparel": 0.6, "electronics_games": 2.5}, "at most 2"),
        ("shipping_weight", SHIPPING | {"ounce_tiers_oz": [8, 4]}, "smallest"),
        ("shipping_weight", SHIPPING | {"ounce_tiers_oz": [16]}, "under 16"),
        ("shipping_weight", SHIPPING | {"max_weight_oz": 12}, "weight limit"),
        ("shipping_weight", SHIPPING | {"dim_weight_divisor": 0}, "divisor"),
        ("shipping_weight", SHIPPING | {"max_length_plus_girth_in": 50}, "16x12x8"),
        ("worth_listing", {"threshold_cents": 3000, "threshold": 1}, "Extra inputs"),
        ("fees", {"fee_rate": 0.1, "supplies_cents": 150}, "Field required"),
        ("channel_b_fees", CHANNEL_B | {"fee_rate": -0.1}, "at least 0%"),
        ("channel_b_fees", CHANNEL_B | {"small_sale_fee_cents": -1}, "below $0"),
        ("channel_b_fees", CHANNEL_B | {"small_sale_below_cents": -1}, "below $0"),
    ],
)
def test_an_invalid_value_is_refused_with_a_clear_reason(
    client: TestClient, session: Session, section: str, value: Any, message: str
) -> None:
    assert any(message in problem for problem in problems(save(client, section, value)))
    assert session.exec(select(StoreSetting)).all() == []


def test_a_box_is_checked_against_a_saved_shipping_limit(client: TestClient) -> None:
    saved(client, "shipping_weight", CHANGED["shipping_weight"])
    messages = problems(save(client, "box_sizes", {"boxes": [box(40, 20, 15)]}))
    assert messages == [
        "Value error, The 40x20x15 box measures 110 inches in length plus girth, which is over "
        "the 108 inch shipping limit."
    ]


def test_season_words_are_kept_trimmed_and_lowercase(client: TestClient) -> None:
    page = saved(client, "seasonal_calendar", {"seasons": [season(match_words=[" Puffer "])]})
    assert page["seasonal_calendar"]["value"]["seasons"][0]["match_words"] == ["puffer"]


def test_a_save_from_a_stale_page_is_refused(client: TestClient) -> None:
    first = save(client, "worth_listing", {"threshold_cents": 2500})
    assert first.status_code == 200, first.text
    loaded_at = first.json()["worth_listing"]["updated_at"]

    second = save(client, "worth_listing", {"threshold_cents": 2000})
    assert second.status_code == 409
    assert second.json()["detail"] == STALE

    third = save(client, "worth_listing", {"threshold_cents": 2000}, loaded_at)
    assert third.status_code == 200, third.text
    assert third.json()["worth_listing"]["updated_at"] != loaded_at
    assert save(client, "worth_listing", {"threshold_cents": 1500}, loaded_at).status_code == 409
    assert load_page(client)["worth_listing"]["value"] == {"threshold_cents": 2000}


def test_the_box_size_list_follows_the_settings(client: TestClient) -> None:
    response = client.get("/settings/box-sizes")
    assert response.status_code == 200, response.text
    assert [option["code"] for option in response.json()] == [
        "10x13",
        "12x15.5",
        "14.5x19",
        "8x6x4",
        "10x8x6",
        "12x12x6",
        "16x12x8",
    ]
    saved(client, "box_sizes", CHANGED["box_sizes"])
    assert client.get("/settings/box-sizes").json() == [
        {"code": "14.25x10x4", "kind": "box", "length_in": 14.25, "width_in": 10, "height_in": 4}
    ]


def test_the_seasonal_calendar_follows_the_settings(client: TestClient) -> None:
    assert client.get("/settings/seasonal-calendar").json() == DEFAULTS["seasonal_calendar"]
    saved(client, "seasonal_calendar", CHANGED["seasonal_calendar"])
    assert client.get("/settings/seasonal-calendar").json() == CHANGED["seasonal_calendar"]


def appraise_jacket(client: TestClient, *dollars: float) -> dict[str, Any]:
    model_replies()
    use_search(listings(*dollars))
    staff_client = TestClient(app, headers=as_token(STAFF_TOKEN))
    item = upload(staff_client)
    add_card(staff_client, item["id"])
    return appraise(staff_client, item["id"])


def test_the_worth_listing_rule_reads_the_saved_threshold_and_fees(client: TestClient) -> None:
    before = appraise_jacket(client, *[80] * 12)
    assert before["recommendation"] == "yes"
    typical = before["price_typical_cents"]

    saved(client, "worth_listing", {"threshold_cents": typical + 1})
    saved(client, "fees", {"fee_rate": 0.2, "per_order_fee_cents": 0, "supplies_cents": 0})
    after = appraise_jacket(client, *[80] * 12)

    assert after["recommendation"] == "no"
    assert after["price_typical_cents"] == typical
    assert after["net_after_fees_cents"] == typical - round(typical * 0.2)
    rules = after["rules_config"]["pricing"]
    assert rules["worth_listing_threshold_cents"] == typical + 1
    assert rules["fee_rate"] == 0.2
    assert rules["per_order_fee_cents"] == rules["supplies_cents"] == 0


def test_the_price_reads_the_saved_ask_to_sale_factor(client: TestClient) -> None:
    before = appraise_jacket(client, *[80] * 12)
    saved(client, "ask_to_sale", {"apparel": 0.5, "electronics_games": 0.94})
    after = appraise_jacket(client, *[80] * 12)
    assert before["price_typical_cents"] == round(8000 * 0.645)
    assert after["price_typical_cents"] == 4000
    assert after["rules_config"]["pricing"]["ask_to_sale_factor"] == 0.5
