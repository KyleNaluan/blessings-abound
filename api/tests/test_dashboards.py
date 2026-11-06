"""The sales insight dashboards, over a small synthetic history and real sales on the mock channels.

The synthetic history is built by hand, so each number the views give can be worked out here.
The live side runs the way the app does, with an item approved, listed on both channels and
bought on a storefront, through the same fixtures as the sync tests.
"""

from datetime import date, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.models import Category, Channel, Recommendation, StoreDepartment, TriageOutcome
from app.settings import SyntheticSales
from app.synthetic_sales import History, Item, Listing, load, price_band
from tests.channel_harness import Market
from tests.test_approval import client, manager  # noqa: F401, the fixtures these tests build on
from tests.test_sync import listed_item, market, run_scheduler  # noqa: F401
from tests.test_synthetic_sales import item

A, B = Channel.CHANNEL_A, Channel.CHANNEL_B
PARAMS = SyntheticSales()
# A Monday in March, so a 10-day run stays inside the month.
DAY = date(2026, 3, 2)


def synthetic_listing(
    number: int, days_to_sell: int | None, price_cents: int = 4000, listed_on: date = DAY
) -> Listing:
    sold_on = None if days_to_sell is None else listed_on + timedelta(days=days_to_sell)
    return Listing(
        id=number,
        item_id=number,
        channel=A,
        price_cents=price_cents,
        listed_on=listed_on,
        sold_on=sold_on,
        ended_on=listed_on + timedelta(days=PARAMS.max_days) if sold_on is None else None,
    )


def game(number: int, **changes: object) -> Item:
    return item(
        number,
        store_department=StoreDepartment.ELECTRONICS_GAMES,
        category=Category.ELECTRONICS_GAMES,
        **changes,
    )


def dashboards(manager: TestClient) -> dict[str, Any]:  # noqa: F811
    response = manager.get("/dashboards")
    assert response.status_code == 200, response.text
    return response.json()


def synthetic_row(body: dict[str, Any], category: Category, cents: int) -> dict[str, Any]:
    [row] = [
        row
        for row in body["time_to_sell"]["synthetic"]
        if row["category"] == category and row["band"] == price_band(PARAMS, cents)
    ]
    return row


def test_only_a_manager_sees_the_dashboards(
    client: TestClient,  # noqa: F811
    manager: TestClient,  # noqa: F811
) -> None:
    refused = client.get("/dashboards")

    assert refused.status_code == 403
    assert refused.json()["detail"] == "Only a manager can do this."
    assert manager.get("/dashboards").status_code == 200


def test_with_nothing_loaded_every_view_is_empty_rather_than_made_up(
    manager: TestClient,  # noqa: F811
) -> None:
    body = dashboards(manager)

    assert body["history"] is None
    assert body["time_to_sell"] == {"synthetic": [], "live": []}
    assert body["seasonality"] == []
    assert body["triage_funnel"]["synthetic"] == []
    assert body["triage_funnel"]["live"] == {
        "forwarded": 0,
        "accepted": 0,
        "listed": 0,
        "sold": 0,
        "called": 0,
        "against_recommendation": 0,
    }
    health = body["sync_health"]
    assert health["first_event_at"] is None
    assert health["published"] == health["sales_by_webhook"] == health["oversold_items"] == 0
    assert [flag["open"] + flag["resolved"] for flag in health["flags"]] == [0, 0, 0]


def test_the_price_bands_come_from_the_history_settings(
    manager: TestClient,  # noqa: F811
) -> None:
    bands = dashboards(manager)["price_bands"]

    edges = list(PARAMS.price_band_edges_cents)
    assert [band["low_cents"] for band in bands] == [None, *edges]
    assert [band["high_cents"] for band in bands] == [*edges, None]
    assert [band["band"] for band in bands] == list(range(len(edges) + 1))


def test_time_to_sell_is_the_middle_of_the_sold_listings_by_category_and_band(
    manager: TestClient,  # noqa: F811
    session: Session,
) -> None:
    items = [item(1), item(2), item(3), item(4), game(5)]
    listings = [
        synthetic_listing(1, 4),
        synthetic_listing(2, 10),
        synthetic_listing(3, None),
        synthetic_listing(4, 30, price_cents=1200),
        synthetic_listing(5, 2, price_cents=12000),
    ]
    load(session, History(seed=0, items=items, listings=listings))

    body = dashboards(manager)

    assert body["history"] == {
        "first_forwarded_on": "2026-01-05",
        "last_forwarded_on": "2026-01-05",
        "items": 5,
        "listings": 5,
        "sales": 4,
        "run_days": PARAMS.max_days,
    }
    # Every category and band is listed, so a band with nothing in it still shows as empty.
    assert len(body["time_to_sell"]["synthetic"]) == 2 * len(body["price_bands"])
    apparel = synthetic_row(body, Category.APPAREL, 4000)
    assert (apparel["listed"], apparel["sold"], apparel["median_days"]) == (3, 2, 7)
    cheap = synthetic_row(body, Category.APPAREL, 1200)
    assert (cheap["listed"], cheap["sold"], cheap["median_days"]) == (1, 1, 30)
    games = synthetic_row(body, Category.ELECTRONICS_GAMES, 12000)
    assert (games["listed"], games["sold"], games["median_days"]) == (1, 1, 2)
    empty = synthetic_row(body, Category.ELECTRONICS_GAMES, 4000)
    assert (empty["listed"], empty["sold"], empty["median_days"]) == (0, 0, None)
    # The synthetic history never reaches the live side.
    assert body["time_to_sell"]["live"] == []
    assert body["triage_funnel"]["live"]["forwarded"] == 0


def test_seasonality_takes_each_months_sales_over_the_days_listings_were_up(
    manager: TestClient,  # noqa: F811
    session: Session,
) -> None:
    # One listing up 10 days in March that sold on its tenth day, and one listed late in March
    # that never sold, so its 90 days run into June.
    items = [item(1), item(2)]
    listings = [
        synthetic_listing(1, 9),
        synthetic_listing(2, None, listed_on=date(2026, 3, 30)),
    ]
    load(session, History(seed=0, items=items, listings=listings))

    rows = {(row["category"], row["month"]): row for row in dashboards(manager)["seasonality"]}

    assert len(rows) == 24
    march = rows[(Category.APPAREL, 3)]
    # Ten days for the first, the day of its sale included, and two for the second.
    assert (march["sales"], march["listing_days"]) == (1, 12)
    assert march["sales_per_100_weekly"] == pytest.approx(1 / 12 * 100 * 7)
    april = rows[(Category.APPAREL, 4)]
    assert (april["sales"], april["listing_days"], april["sales_per_100_weekly"]) == (0, 30, 0)
    # The run ends 90 days after March 30, on June 28, which is its first day down.
    assert rows[(Category.APPAREL, 6)]["listing_days"] == 27
    assert rows[(Category.APPAREL, 7)]["sales_per_100_weekly"] is None
    assert rows[(Category.ELECTRONICS_GAMES, 3)]["sales_per_100_weekly"] is None


def test_the_funnel_counts_each_stage_and_the_calls_against_the_recommendation(
    manager: TestClient,  # noqa: F811
    session: Session,
) -> None:
    rejected = {"outcome": TriageOutcome.REJECTED}
    items = [
        item(1),
        item(2),
        # A yes turned down and a no taken on are both against the recommendation.
        item(3, overridden=True, **rejected),
        item(4, recommendation=Recommendation.NO, overridden=False, **rejected),
        item(5, recommendation=Recommendation.NO, overridden=True),
        # A check has no side, so it isn't a call on a recommendation.
        item(6, recommendation=Recommendation.CHECK, **rejected),
        game(7),
    ]
    listings = [
        synthetic_listing(1, 5),
        synthetic_listing(2, None),
        synthetic_listing(5, None),
        synthetic_listing(7, 3),
    ]
    load(session, History(seed=0, items=items, listings=listings))

    funnel = {row["category"]: row for row in dashboards(manager)["triage_funnel"]["synthetic"]}

    assert funnel[Category.APPAREL] == {
        "category": Category.APPAREL,
        "forwarded": 6,
        "accepted": 3,
        "listed": 3,
        "sold": 1,
        "called": 5,
        "against_recommendation": 2,
    }
    games = funnel[Category.ELECTRONICS_GAMES]
    assert (games["forwarded"], games["listed"], games["sold"]) == (1, 1, 1)


def test_a_sale_on_a_mock_channel_shows_on_the_live_side_only(
    client: TestClient,  # noqa: F811
    manager: TestClient,  # noqa: F811
    market: Market,  # noqa: F811
    session: Session,
) -> None:
    load(session, History(seed=0, items=[item(1)], listings=[synthetic_listing(1, 4)]))
    _, listings = listed_item(client, manager, session, market)
    market.buy(A, listings[A]["channel_listing_id"])
    run_scheduler(session, market)

    body = dashboards(manager)

    [live] = body["time_to_sell"]["live"]
    assert live["category"] == Category.APPAREL
    assert live["band"] == price_band(PARAMS, listings[A]["price_cents"])
    # Both channels confirmed a listing, and one of them sold.
    assert (live["listed"], live["sold"]) == (2, 1)
    assert live["median_hours"] >= 0
    assert body["triage_funnel"]["live"] == {
        "forwarded": 1,
        "accepted": 1,
        "listed": 1,
        "sold": 1,
        "called": 1,
        "against_recommendation": 0,
    }
    health = body["sync_health"]
    assert (health["published"], health["sales_by_webhook"], health["sales_by_polling"]) == (
        2,
        1,
        0,
    )
    assert health["delisted"] == 1
    assert health["oversold_items"] == 0
    assert health["first_event_at"] is not None
    # The live sale doesn't change the synthetic numbers.
    assert body["history"]["sales"] == 1
    assert synthetic_row(body, Category.APPAREL, 4000)["sold"] == 1


def test_a_double_sale_shows_as_an_open_disagreement_and_an_oversold_item(
    client: TestClient,  # noqa: F811
    manager: TestClient,  # noqa: F811
    market: Market,  # noqa: F811
    session: Session,
) -> None:
    _, listings = listed_item(client, manager, session, market)
    # A's webhook is lost, so B sells too, and taking A down finds it already sold.
    market.buy(A, listings[A]["channel_listing_id"], send_webhook=False)
    market.buy(B, listings[B]["channel_listing_id"])

    health = dashboards(manager)["sync_health"]

    flags = {flag["conflict"]: flag for flag in health["flags"]}
    assert flags["double_sale"] == {"conflict": "double_sale", "open": 1, "resolved": 0}
    assert flags["stale_listing"]["open"] == flags["unknown_listing"]["open"] == 0
    assert health["oversold_items"] == 1
    assert health["delist_found_sold"] == 1
