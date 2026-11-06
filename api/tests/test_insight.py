"""The sales insight chat, with each metric function run on a small history built by hand.

The metric functions are tested on their own, so each number can be worked out here. The chat
itself is tested through the API with the model stubbed, so no test reaches a real model.
"""

import json
from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.insight import (
    NO_FUNCTION,
    InsightFact,
    MetricName,
    MetricQuery,
    MetricResult,
    get_insight_providers,
    run_metric,
    unreturned_numbers,
)
from app.main import app
from app.models import Category, Channel, Recommendation, TriageOutcome
from app.settings import SyntheticSales
from app.synthetic_sales import History, load
from tests.channel_harness import Market
from tests.test_appraisal import StubChat
from tests.test_approval import client, manager  # noqa: F401, the fixtures these tests build on
from tests.test_dashboards import game, synthetic_listing
from tests.test_sync import listed_item, market, run_scheduler  # noqa: F401
from tests.test_synthetic_sales import item

PARAMS = SyntheticSales()
APPAREL, GAMES = Category.APPAREL, Category.ELECTRONICS_GAMES


def small_history(session: Session) -> None:
    """Four apparel listings at $40, one at $12 and one game at $120, two of them unsold."""
    items = [item(1), item(2), item(3), item(4), game(5), item(6)]
    listings = [
        synthetic_listing(1, 4),
        synthetic_listing(2, 10),
        synthetic_listing(3, None),
        synthetic_listing(4, 30, price_cents=1200),
        synthetic_listing(5, 2, price_cents=12000),
        synthetic_listing(6, None, price_cents=1200),
    ]
    load(session, History(seed=0, items=items, listings=listings))


def run(session: Session, function: MetricName, **inputs: Any) -> MetricResult:
    return run_metric(session, PARAMS, MetricQuery(function=function, **inputs))


def facts(result: MetricResult) -> dict[str, str]:
    return {fact.label: fact.value for fact in result.facts}


def test_time_to_sell_counts_one_category_and_band(session: Session) -> None:
    small_history(session)

    result = run(session, MetricName.TIME_TO_SELL, category=APPAREL, price_band=2)

    found = facts(result)
    assert found["Listings"] == "Apparel, priced $30 to $49.99"
    assert (found["Listed"], found["Sold within 90 days"], found["Share sold"]) == ("3", "2", "67%")
    # The middle of 4 and 10 days.
    assert found["Middle days to sell"] == "7 days"
    assert found["Days a listing runs before it ends unsold"] == "90"
    assert found["Items forwarded"] == "5 January 2026 to 5 January 2026"
    assert result.sentence == (
        "In the synthetic history, 2 of the 3 apparel listings priced $30 to $49.99 sold within "
        "90 days, which is 67%, and the middle one of those took 7 days to sell."
    )


def test_time_to_sell_with_no_inputs_takes_every_listing(session: Session) -> None:
    small_history(session)

    found = facts(run(session, MetricName.TIME_TO_SELL))

    assert found["Listings"] == "Every category, at every price"
    assert (found["Listed"], found["Sold within 90 days"], found["Share sold"]) == ("6", "4", "67%")
    # The middle of 2, 4, 10 and 30 days, between two sales.
    assert found["Middle days to sell"] == "7 days"


def test_time_to_sell_says_when_a_band_had_nothing_listed(session: Session) -> None:
    small_history(session)

    result = run(session, MetricName.TIME_TO_SELL, category=GAMES, price_band=0)

    assert facts(result)["Middle days to sell"] == "None sold"
    assert result.sentence == (
        "The synthetic history has no electronics and games listings priced Under $15."
    )


def test_time_to_sell_by_band_finds_the_fastest_and_slowest_band(session: Session) -> None:
    small_history(session)

    result = run(session, MetricName.TIME_TO_SELL_BY_BAND, category=APPAREL)

    found = facts(result)
    assert found["Under $15"] == "30 days middle, 1 of 2 sold"
    assert found["$30 to $49.99"] == "7 days middle, 2 of 3 sold"
    assert found["$100 to $249.99"] == "None listed"
    assert (found["Fastest to sell"], found["Slowest to sell"]) == ("$30 to $49.99", "Under $15")
    assert result.sentence == (
        "In the synthetic history, in apparel, listings priced $30 to $49.99 sold fastest, at a "
        "middle 7 days over 2 sales, and listings priced Under $15 sold slowest, at a middle 30 "
        "days over 1 sale."
    )


def test_seasonality_gives_the_rate_for_a_month_and_the_busiest_and_quietest(
    session: Session,
) -> None:
    # One listing up 10 days in March that sold on its tenth day, and one listed on March 30
    # that never sold, up for 2 days in March, 30 in April, 31 in May and 27 in June.
    load(
        session,
        History(
            seed=0,
            items=[item(1), item(2)],
            listings=[
                synthetic_listing(1, 9),
                synthetic_listing(2, None, listed_on=date(2026, 3, 30)),
            ],
        ),
    )

    march = run(session, MetricName.SEASONALITY, category=APPAREL, month=3)

    # 1 sale over 12 listing days, for every 100 listings a week, is 58.3.
    assert facts(march)["March"] == ("58.3 sales for every 100 listings up a week, from 1 sale")
    assert "February" not in facts(march)
    assert march.sentence == (
        "In the synthetic history, March had 58.3 sales for every 100 listings up a week in "
        "apparel."
    )

    year = facts(run(session, MetricName.SEASONALITY))
    assert year["April"] == "0.0 sales for every 100 listings up a week, from 0 sales"
    assert year["July"] == "No listings up"
    # A tie at no sales goes to the earliest month.
    assert (year["Busiest month"], year["Quietest month"]) == ("March", "April")


def test_the_triage_funnel_adds_up_both_categories(session: Session) -> None:
    rejected = {"outcome": TriageOutcome.REJECTED}
    items = [
        item(1),
        item(2, overridden=True, **rejected),
        item(3, recommendation=Recommendation.CHECK, **rejected),
        game(4),
    ]
    listings = [synthetic_listing(1, 5), synthetic_listing(4, None)]
    load(session, History(seed=0, items=items, listings=listings))

    both = run(session, MetricName.TRIAGE_FUNNEL)

    found = facts(both)
    assert found["Forwarded to Ecommerce"] == "4"
    assert found["Accepted by staff"] == "2, 50% of forwarded"
    assert found["Listed"] == "2, 50% of forwarded"
    assert found["Sold within 90 days"] == "1, 25% of forwarded"
    # A check has no side, so it isn't a call.
    assert found["Staff calls against a yes or a no"] == "1 of 3, 33%"
    apparel = facts(run(session, MetricName.TRIAGE_FUNNEL, category=APPAREL))
    assert apparel["Forwarded to Ecommerce"] == "3"


def test_with_no_history_loaded_the_history_functions_say_so(session: Session) -> None:
    for function in (
        MetricName.TIME_TO_SELL,
        MetricName.TIME_TO_SELL_BY_BAND,
        MetricName.SEASONALITY,
        MetricName.TRIAGE_FUNNEL,
    ):
        result = run(session, function)
        assert result.facts == []
        assert not result.has_numbers
        assert result.sentence == (
            "No synthetic history is loaded, so there are no numbers to answer from yet."
        )


def test_live_sales_and_sync_count_a_sale_on_a_mock_channel(
    client: TestClient,  # noqa: F811
    manager: TestClient,  # noqa: F811
    market: Market,  # noqa: F811
    session: Session,
) -> None:
    assert run(session, MetricName.LIVE_SALES).sentence == (
        "No item has come through intake yet, so there are no live sales to count."
    )
    assert not run(session, MetricName.SYNC_HEALTH).has_numbers
    # The synthetic history never reaches the live side.
    small_history(session)
    _, listings = listed_item(client, manager, session, market)
    market.buy(Channel.CHANNEL_A, listings[Channel.CHANNEL_A]["channel_listing_id"])
    run_scheduler(session, market)

    live = run(session, MetricName.LIVE_SALES)
    sync = run(session, MetricName.SYNC_HEALTH)

    found = facts(live)
    assert found["Forwarded to Ecommerce"] == "1"
    assert found["Items sold"] == "1, 100% of forwarded"
    # Listed on both channels, and sold on one.
    assert (found["Listings a mock channel confirmed"], found["Of those listings, sold"]) == (
        "2",
        "1",
    )
    assert live.sentence == (
        "In Turnstone, 1 item has come through intake, 1 listed on the mock channels and 1 sold, "
        "from test sales rather than real buyers."
    )
    found = facts(sync)
    assert (found["Listings confirmed by a channel"], found["Sales heard by webhook"]) == ("2", "1")
    assert found["Sold on both channels"] == "0 open, 0 settled"
    assert sync.sentence == (
        "On the mock channels, sync has had 2 listings confirmed, heard about 1 sale and taken 1 "
        "listing down, and 0 disagreements are still open on Needs Attention."
    )


def test_the_number_check_takes_numbers_from_the_facts_and_the_inputs() -> None:
    query = MetricQuery(function=MetricName.SEASONALITY, month=12)
    found = [InsightFact(label="December", value="3.6 sales, from 1,204 listing days")]

    assert unreturned_numbers("3.6 sales in month 12 over 1204 days", query, found) == []
    assert unreturned_numbers("About 4 in 2025, or 3.60", query, found) == ["2025", "3.60", "4"]


# The chat through the API, with the model stubbed.


def pick(function: str, **inputs: object) -> str:
    return json.dumps({"function": function, "category": None, "price_band": None} | inputs)


def worded(answer: str) -> str:
    return json.dumps({"answer": answer})


def use_chat(*replies: str | int) -> StubChat:
    chat = StubChat(*replies)
    app.dependency_overrides[get_insight_providers] = lambda: [chat]
    return chat


def ask(manager: TestClient, question: str) -> dict[str, Any]:  # noqa: F811
    response = manager.post("/dashboards/ask", json={"question": question})
    assert response.status_code == 200, response.text
    return response.json()


def test_only_a_manager_can_ask(
    client: TestClient,  # noqa: F811
    session: Session,
) -> None:
    chat = use_chat(pick("time_to_sell"))

    refused = client.post("/dashboards/ask", json={"question": "How fast do things sell?"})

    assert refused.status_code == 403
    assert refused.json()["detail"] == "Only a manager can do this."
    assert chat.calls == []


def test_an_answer_shows_the_function_and_inputs_it_came_from(
    manager: TestClient,  # noqa: F811
    session: Session,
) -> None:
    small_history(session)
    chat = use_chat(
        pick("time_to_sell", category="apparel", price_band=2),
        worded(
            "In the synthetic history, 2 of 3 apparel listings at $30 to $49.99 sold, and the "
            "middle one took 7 days."
        ),
    )

    body = ask(manager, "  How fast does apparel around $40 sell?  ")

    assert body["question"] == "How fast does apparel around $40 sell?"
    assert body["answer"].startswith("In the synthetic history, 2 of 3 apparel listings")
    assert body["written_by"] == "model"
    assert body["fallback_reason"] is None
    assert body["query"] == {
        "function": "time_to_sell",
        "category": "apparel",
        "price_band": 2,
        "month": None,
    }
    assert body["call"] == 'time_to_sell(category="apparel", price_band=2)'
    assert body["source"] == "history"
    assert {"label": "Middle days to sell", "value": "7 days"} in body["facts"]
    assert body["model_name"] == "primary"
    # The question goes to both calls, and the second sees only what the function returned.
    pick_call, word_call = chat.calls
    assert pick_call[-1] == {"role": "user", "content": "How fast does apparel around $40 sell?"}
    assert '"time_to_sell", taking category, price_band' in pick_call[0]["content"]
    assert "- Middle days to sell: 7 days" in word_call[0]["content"]
    assert 'Function: time_to_sell(category="apparel", price_band=2)' in word_call[0]["content"]
    assert "synthetic history, not the store's own sales" in word_call[0]["content"]


def test_a_number_the_function_didnt_return_is_refused(
    manager: TestClient,  # noqa: F811
    session: Session,
) -> None:
    small_history(session)
    use_chat(
        pick("time_to_sell", category="apparel", price_band=2),
        worded("Apparel at $40 sells in about 11 days, 3 times faster than games."),
    )

    body = ask(manager, "How fast does apparel around $40 sell?")

    # The question's own $40 isn't a number the function returned either.
    assert body["rejected_numbers"] == ["11", "40"]
    assert body["fallback_reason"] == "flagged"
    assert body["written_by"] == "code"
    assert body["answer"] == (
        "In the synthetic history, 2 of the 3 apparel listings priced $30 to $49.99 sold within "
        "90 days, which is 67%, and the middle one of those took 7 days to sell."
    )
    assert body["call"] == 'time_to_sell(category="apparel", price_band=2)'


def test_a_question_no_function_covers_gets_a_plain_answer_saying_so(
    manager: TestClient,  # noqa: F811
    session: Session,
) -> None:
    small_history(session)
    chat = use_chat(pick("none"))

    body = ask(manager, "Who is our best volunteer?")

    assert body["answer"] == NO_FUNCTION
    assert body["written_by"] == "code"
    assert (body["query"], body["call"], body["source"], body["facts"]) == (None, None, None, [])
    # Nothing is worded, so the model is asked only to pick.
    assert len(chat.calls) == 1


def test_inputs_a_function_doesnt_take_are_dropped(
    manager: TestClient,  # noqa: F811
    session: Session,
) -> None:
    small_history(session)
    use_chat(
        pick("time_to_sell_by_band", category="apparel", price_band=3, month=4),
        worded("In the synthetic history, apparel at $30 to $49.99 sold fastest."),
    )

    body = ask(manager, "Which price sells fastest for apparel?")

    assert body["call"] == 'time_to_sell_by_band(category="apparel")'
    assert body["query"]["price_band"] is None
    assert body["query"]["month"] is None


def test_a_pick_of_a_band_that_doesnt_exist_is_tried_again(
    manager: TestClient,  # noqa: F811
    session: Session,
) -> None:
    small_history(session)
    chat = use_chat(
        pick("time_to_sell", price_band=9),
        pick("time_to_sell", price_band=0),
        worded("In the synthetic history, 1 of 2 listings under $15 sold."),
    )

    body = ask(manager, "How do cheap things sell?")

    assert body["call"] == "time_to_sell(price_band=0)"
    assert len(chat.calls) == 3


def test_a_live_answer_says_where_its_numbers_come_from(
    manager: TestClient,  # noqa: F811
    session: Session,
) -> None:
    chat = use_chat(pick("live_sales"))

    body = ask(manager, "How many items have sold for real?")

    assert body["source"] == "live"
    assert body["call"] == "live_sales()"
    # With nothing to count, the fixed sentence answers without asking the model to word it.
    assert body["answer"] == (
        "No item has come through intake yet, so there are no live sales to count."
    )
    assert body["fallback_reason"] is None
    assert len(chat.calls) == 1


def test_when_the_wording_fails_the_fixed_sentence_answers(
    manager: TestClient,  # noqa: F811
    session: Session,
) -> None:
    small_history(session)
    use_chat(pick("triage_funnel"), "not json", "still not json")

    body = ask(manager, "How many items make it to a sale?")

    assert body["written_by"] == "code"
    assert body["fallback_reason"] == "model_failed"
    assert body["answer"].startswith(
        "In the synthetic history, across both categories, 6 items were forwarded"
    )


def test_with_no_model_or_a_model_that_cant_pick_nothing_is_answered(
    manager: TestClient,  # noqa: F811
    session: Session,
) -> None:
    app.dependency_overrides[get_insight_providers] = lambda: []
    missing = manager.post("/dashboards/ask", json={"question": "How fast do things sell?"})
    assert missing.status_code == 503
    assert "isn't set up" in missing.json()["detail"]

    use_chat(503)
    down = manager.post("/dashboards/ask", json={"question": "How fast do things sell?"})
    assert down.status_code == 502
    assert down.json()["detail"].startswith("The language model couldn't be reached")


@pytest.mark.parametrize("question", ["", "   ", "x" * 301])
def test_an_empty_or_long_question_is_refused(
    manager: TestClient,  # noqa: F811
    session: Session,
    question: str,
) -> None:
    chat = use_chat(pick("time_to_sell"))

    response = manager.post("/dashboards/ask", json={"question": question})

    assert response.status_code == 422
    assert chat.calls == []
