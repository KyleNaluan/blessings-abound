"""The two mock channel services on their own, run against real Postgres."""

import hashlib
import hmac
import json
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import httpx2
import pytest
from sqlalchemy import Connection

from app.listing_drafts import CHANNEL_CATEGORIES
from app.models import Channel
from mock_channel import channel_a, channel_b, service
from mock_channel.service import ChannelSettings
from tests.channel_harness import APPS, KEYS, Market

A, B = Channel.CHANNEL_A, Channel.CHANNEL_B
SPECS = {A: channel_a.SPEC, B: channel_b.SPEC}

JACKET = {
    "title": "Carhartt canvas jacket",
    "description": "Brown canvas, pre-owned.",
    "condition": "pre_owned",
    "price_cents": 4800,
    "brand": "Carhartt",
    "size": "L",
    "color": "brown",
    "specifics": {"material": "canvas"},
}
# A jacket's category in each channel's own list.
JACKET_CATEGORY = {A: "Unisex Clothing", B: "Unisex"}


class Webhooks:
    """Stands in for the app, answering each sale webhook with a set status."""

    def __init__(self) -> None:
        self.status = 204
        self.requests: list[httpx2.Request] = []
        self.client = httpx2.Client(transport=httpx2.MockTransport(self.answer))

    def answer(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        return httpx2.Response(self.status)


@pytest.fixture
def webhooks() -> Webhooks:
    return Webhooks()


@pytest.fixture
def market(connection: Connection, webhooks: Webhooks) -> Iterator[Market]:
    market = Market(connection, webhook_client=webhooks.client)
    yield market
    market.close()


def list_item(market: Market, channel: Channel = A, **changes: Any) -> Any:
    body = {
        "external_ref": str(uuid4()),
        "category": JACKET_CATEGORY[channel],
        **JACKET,
        **changes,
    }
    return market.adapters[channel].client.post("/listings", json=body)


def listed(market: Market, channel: Channel = A) -> dict[str, Any]:
    response = list_item(market, channel)
    assert response.status_code == 201, response.text
    return response.json()


def test_publishing_twice_with_one_external_ref_returns_one_listing(market: Market) -> None:
    ref = str(uuid4())

    first = list_item(market, external_ref=ref)
    second = list_item(market, external_ref=ref, price_cents=9900)

    assert (first.status_code, second.status_code) == (201, 200)
    assert first.json()["id"] == second.json()["id"]
    assert second.json()["price_cents"] == JACKET["price_cents"]
    assert first.json()["status"] == "active"


@pytest.mark.parametrize(
    ("channel", "changes", "message"),
    [
        (B, {"category": "Video Games"}, "Channel B has no Video Games category."),
        (B, {"brand": None}, "Channel B needs a brand."),
        (A, {"title": "x" * 81}, "Channel A titles are at most 80 characters."),
        (A, {"category": "Unisex"}, "Channel A has no Unisex category."),
    ],
)
def test_each_channel_enforces_its_own_rules(
    market: Market, channel: Channel, changes: dict[str, Any], message: str
) -> None:
    response = list_item(market, channel, **changes)

    assert response.status_code == 422
    assert response.json()["detail"] == message


def test_channel_a_takes_electronics_without_a_brand(market: Market) -> None:
    response = list_item(market, A, category="Video Games", brand=None)

    assert response.status_code == 201, response.text


@pytest.mark.parametrize("channel", [A, B])
def test_each_channel_has_the_categories_the_drafts_choose_from(channel: Channel) -> None:
    drafted = {
        name for (on, _), names in CHANNEL_CATEGORIES.items() if on is channel for name in names
    }

    assert set(SPECS[channel].categories) == drafted


def test_the_seller_api_needs_the_channel_key(market: Market) -> None:
    shop = market.shops[A]

    assert shop.get("/api/listings").status_code == 401
    wrong = shop.get("/api/listings", headers={"Authorization": "Bearer nope"})
    assert wrong.status_code == 401
    assert shop.get(
        "/api/listings", headers={"Authorization": f"Bearer {KEYS[B]}"}
    ).status_code == (401)


def test_a_channel_with_no_key_set_turns_its_seller_api_off(market: Market) -> None:
    APPS[A].dependency_overrides[service.get_channel_settings] = lambda: ChannelSettings()

    response = market.adapters[A].client.get("/listings")

    assert response.status_code == 503
    assert response.json()["detail"] == "Channel A has no seller key set."


def test_ending_a_listing_is_safe_to_repeat_but_a_sold_one_cannot_end(market: Market) -> None:
    seller = market.adapters[A].client
    listing = listed(market)
    sold = listed(market)
    market.buy(A, sold["id"], send_webhook=False)

    first = seller.post(f"/listings/{listing['id']}/end")
    second = seller.post(f"/listings/{listing['id']}/end")
    refused = seller.post(f"/listings/{sold['id']}/end")
    missing = seller.post(f"/listings/{uuid4()}/end")

    assert first.json()["status"] == second.json()["status"] == "ended"
    assert first.json()["ended_at"] == second.json()["ended_at"]
    assert (refused.status_code, refused.json()["detail"]) == (
        409,
        "This listing has already sold.",
    )
    assert missing.status_code == 404


def test_cancelling_an_order_refunds_it_and_takes_the_listing_down(market: Market) -> None:
    seller = market.adapters[A].client
    listing = listed(market)
    order = market.buy(A, listing["id"], send_webhook=False)

    first = seller.post(f"/orders/{order['id']}/cancel")
    second = seller.post(f"/orders/{order['id']}/cancel")
    missing = seller.post(f"/orders/{uuid4()}/cancel")

    assert first.status_code == 200, first.text
    assert first.json()["status"] == second.json()["status"] == "cancelled"
    assert market.listing(A, listing["id"])["status"] == "ended"
    assert market.adapters[A].active_listings() == []
    assert missing.status_code == 404
    market.set_offline(A)
    assert seller.post(f"/orders/{order['id']}/cancel").status_code == 503


def test_the_listings_filter_shows_only_active_ones(market: Market) -> None:
    active = listed(market)
    market.buy(A, listed(market)["id"], send_webhook=False)

    rows = market.adapters[A].active_listings()

    assert [row.id for row in rows] == [active["id"]]


def test_a_listing_sells_once(market: Market) -> None:
    listing = listed(market)
    market.buy(A, listing["id"], send_webhook=False)

    again = market.shops[A].post("/purchases", json={"listing_id": listing["id"]})

    assert again.status_code == 409
    assert again.json()["detail"] == "This item is no longer available."
    assert market.listing(A, listing["id"])["status"] == "sold"


def test_a_sale_sends_a_signed_webhook_and_a_2xx_acknowledges_it(
    market: Market, webhooks: Webhooks
) -> None:
    listing = listed(market)

    order = market.buy(A, listing["id"])

    [request] = webhooks.requests
    assert str(request.url) == "http://testserver/channels/channel_a/sales"
    body = request.content
    expected = hmac.new(KEYS[A].encode(), body, hashlib.sha256).hexdigest()
    assert request.headers["X-Channel-Signature"] == f"sha256={expected}"
    sent = json.loads(body)
    assert sent["id"] == order["id"]
    assert sent["external_ref"] == listing["external_ref"]
    assert sent["price_cents"] == JACKET["price_cents"]
    assert market.adapters[A].unacknowledged_orders() == []


def test_an_unanswered_webhook_leaves_the_order_for_polling(
    market: Market, webhooks: Webhooks
) -> None:
    webhooks.status = 500
    listing = listed(market)

    order = market.buy(A, listing["id"])

    [pending] = market.adapters[A].unacknowledged_orders()
    assert pending.id == order["id"]
    market.adapters[A].acknowledge_order(pending.id)
    assert market.adapters[A].unacknowledged_orders() == []


def test_a_purchase_can_leave_the_webhook_out(market: Market, webhooks: Webhooks) -> None:
    market.buy(A, listed(market)["id"], send_webhook=False)

    assert webhooks.requests == []
    assert len(market.adapters[A].unacknowledged_orders()) == 1


def test_an_offline_channel_refuses_sellers_and_shoppers(market: Market) -> None:
    listing = listed(market)

    market.set_offline(A)

    assert market.adapters[A].client.get("/listings").status_code == 503
    purchase = market.shops[A].post("/purchases", json={"listing_id": listing["id"]})
    assert purchase.status_code == 503
    assert "offline right now" in market.shops[A].get("/").text
    market.set_offline(A, False)
    assert market.adapters[A].client.get("/listings").status_code == 200


def test_the_switches_need_the_channel_key(market: Market) -> None:
    shop = market.shops[B]

    assert shop.get("/admin").status_code == 401
    assert shop.get("/admin", auth=("demo", KEYS[A])).status_code == 401
    page = shop.get("/admin", auth=("demo", KEYS[B]))
    assert page.status_code == 200
    assert "Channel B is <strong>online</strong>." in page.text


def test_the_storefront_shows_what_is_for_sale_and_buys_it(
    market: Market, webhooks: Webhooks
) -> None:
    shop = market.shops[A]
    assert "Nothing is for sale right now." in shop.get("/").text
    listing = listed(market)

    page = shop.get("/")
    bought = shop.post(
        f"/buy/{listing['id']}", data={"send_webhook": "true"}, follow_redirects=False
    )
    again = shop.post(f"/buy/{listing['id']}", data={})

    assert "Carhartt canvas jacket" in page.text
    assert "$48.00" in page.text
    assert f'action="/buy/{listing["id"]}"' in page.text
    assert bought.status_code == 303
    assert bought.headers["location"].startswith("/?order=")
    assert len(webhooks.requests) == 1
    thanks = shop.get(bought.headers["location"])
    assert "your order is in" in thanks.text
    assert "Carhartt canvas jacket" not in thanks.text
    assert again.status_code == 409
    assert "This item is no longer available." in again.text


def test_the_storefront_escapes_what_sellers_write(market: Market) -> None:
    list_item(market, title="<script>alert(1)</script>")

    page = market.shops[A].get("/").text

    assert "<script>alert" not in page
    assert "&lt;script&gt;" in page


def test_the_storefront_can_buy_without_a_webhook(market: Market, webhooks: Webhooks) -> None:
    listing = listed(market)

    bought = market.shops[A].post(f"/buy/{listing['id']}", data={}, follow_redirects=False)

    assert "next poll" in market.shops[A].get(bought.headers["location"]).text
    assert webhooks.requests == []
    assert len(market.adapters[A].unacknowledged_orders()) == 1


def test_the_health_check_needs_no_key(market: Market) -> None:
    assert market.shops[B].get("/health").json() == {"status": "ok"}
