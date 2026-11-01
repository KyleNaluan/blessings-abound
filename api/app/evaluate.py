"""Score the pricing pipeline against independent sold prices, and raw asking prices the same way.

Run `uv run python -m app.evaluate` in api/ to replay the committed item cards and search responses
and rewrite the results, which spends no searches and needs no keys. See docs/evaluation.md.

`--read-cards` asks the vision model for any card that is missing, and `--live-searches N` allows
up to N new SerpApi searches. A search that is already saved is never repeated, so deleting a card
or a response file is how to redo one.
"""

import argparse
import hashlib
import json
import re
import statistics
import time
from datetime import date
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import NAMESPACE_URL, uuid5

import httpx2
import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
from sqlmodel import Session

from app.ai import ChatModel, get_chat_model, get_fallback_chat_model
from app.comps import Comp, EbaySearch, parse_comps, serpapi_ebay_search, strip_private_fields
from app.db import get_engine
from app.models import Category, CompSearch, Condition, Department, ItemCard
from app.pipeline import needs_confirmation, price_item, staff_notes
from app.pricing import HIGH_PERCENTILE, LOW_PERCENTILE, TYPICAL_PERCENTILE, percentile
from app.settings import get_settings
from app.vision import ItemCardDraft, prepare_photo, read_item_card

EVAL_DIR = Path(__file__).resolve().parents[1] / "eval"
ITEMS_FILE = EVAL_DIR / "items.json"
CARDS_DIR = EVAL_DIR / "cards"
SEARCHES_DIR = EVAL_DIR / "serpapi"
PHOTOS_DIR = EVAL_DIR / "photos"
RESULTS_FILE = EVAL_DIR / "results.json"
REPORT_FILE = Path(__file__).resolve().parents[2] / "docs" / "evaluation.md"

# The share of the free plan set aside for this set, counted by the saved responses.
SEARCH_BUDGET = 80
# Groq's free tokens per minute cover about 3 photos a minute, see docs/architecture.md.
SECONDS_BETWEEN_CARDS = 22
COMMONS_USER_AGENT = "TurnstoneEval/0.1 (https://github.com/KyleNaluan/blessings-abound)"
# Outcomes that say the run itself went wrong, rather than that the item has no price.
FAILED_SEARCH_OUTCOMES = {"budget_spent", "not_configured", "search_failed"}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class StaffEntries(_Strict):
    """What staff would enter for the item, because the model never supplies these."""

    condition: Condition = Condition.PRE_OWNED
    department: Department | None = None
    size: str | None = None
    size_type: str | None = None
    tested_working: bool | None = None
    complete_in_box: bool | None = None
    accessories_included: str | None = None


class PhotoSource(_Strict):
    file: str
    url: str
    page: str
    sha1: str
    license: str
    author: str


class PriceGuideReference(_Strict):
    """A published sold price from a price guide, linked wherever it is shown."""

    kind: Literal["price_guide"]
    source: str
    tier: str
    price_cents: int = Field(gt=0)
    url: str
    recorded_on: date
    sales_volume: str


class HandRecordedReference(_Strict):
    """A sold price a person read from a sold-items search in their own browser."""

    kind: Literal["hand_recorded"]
    source: str
    price_cents: int = Field(gt=0)
    search_url: str
    recorded_on: date
    recorded_by: str


Reference = Annotated[PriceGuideReference | HandRecordedReference, Field(discriminator="kind")]


class EvalItem(_Strict):
    id: str
    name: str
    category: Category
    staff: StaffEntries
    photo: PhotoSource
    reference: Reference
    note: str | None = None


class SavedCard(_Strict):
    provider: str
    card: ItemCardDraft


class Prices(_Strict):
    low_cents: int | None
    typical_cents: int | None
    high_cents: int | None
    comps_count: int
    in_range: bool
    error_percent: float | None


class ItemScore(_Strict):
    id: str
    category: Category
    reference_cents: int
    search_query: str
    queries_searched: list[str]
    model_confidence: str
    needed_confirmation: bool
    pipeline_confidence: str
    pipeline_recommendation: str
    pipeline: Prices
    baseline: Prices


class Summary(_Strict):
    items: int
    priced: int
    in_range: int
    in_range_rate: float | None
    median_error_percent: float | None


class Group(_Strict):
    pipeline: Summary
    baseline: Summary
    pipeline_beats_baseline_on_in_range: bool | None
    pipeline_beats_baseline_on_median_error: bool | None


class Results(_Strict):
    groups: dict[str, Group]
    # The same comps with the ask-to-sale factor undone, to show what the factor does. Not a rule.
    pipeline_before_factor: Summary
    median_ask_over_reference: float | None
    searches_saved: int
    rules: dict[str, Any]
    items: list[ItemScore]


class EvaluationStopped(RuntimeError):
    """The run can't finish, so nothing is scored rather than scoring part of the set."""


def load_items(path: Path = ITEMS_FILE) -> list[EvalItem]:
    return TypeAdapter(list[EvalItem]).validate_json(path.read_bytes())


def score(reference_cents: int, low: int | None, typical: int | None, high: int | None) -> Prices:
    """Prices with no count yet. No price at all is never in range and has no error."""
    if low is None or typical is None or high is None:
        return Prices(
            low_cents=None,
            typical_cents=None,
            high_cents=None,
            comps_count=0,
            in_range=False,
            error_percent=None,
        )
    return Prices(
        low_cents=low,
        typical_cents=typical,
        high_cents=high,
        comps_count=0,
        in_range=low <= reference_cents <= high,
        error_percent=round(abs(typical - reference_cents) / reference_cents * 100, 1),
    )


def baseline_prices(comps: list[Comp], reference_cents: int) -> Prices:
    """The middle half and median of every listing returned, with no filter, trim or factor."""
    prices = sorted(comp.price_cents for comp in comps if comp.price_cents > 0)
    if not prices:
        return score(reference_cents, None, None, None)
    low, typical, high = (
        round(percentile(prices, fraction))
        for fraction in (LOW_PERCENTILE, TYPICAL_PERCENTILE, HIGH_PERCENTILE)
    )
    prices_scored = score(reference_cents, low, typical, high)
    return prices_scored.model_copy(update={"comps_count": len(prices)})


def summarize(rows: list[Prices]) -> Summary:
    """In range counts every item, and median error can only count the items that got a price."""
    errors = [row.error_percent for row in rows if row.error_percent is not None]
    in_range = sum(row.in_range for row in rows)
    return Summary(
        items=len(rows),
        priced=len(errors),
        in_range=in_range,
        in_range_rate=round(in_range / len(rows), 3) if rows else None,
        median_error_percent=round(statistics.median(errors), 1) if errors else None,
    )


def compare(scores: list[ItemScore]) -> Group:
    pipeline = summarize([item.pipeline for item in scores])
    baseline = summarize([item.baseline for item in scores])
    errors = (pipeline.median_error_percent, baseline.median_error_percent)
    return Group(
        pipeline=pipeline,
        baseline=baseline,
        pipeline_beats_baseline_on_in_range=pipeline.in_range > baseline.in_range
        if scores
        else None,
        pipeline_beats_baseline_on_median_error=errors[0] < errors[1]
        if errors[0] is not None and errors[1] is not None
        else None,
    )


def before_factor(row: ItemScore, factor: float) -> Prices:
    """The pipeline's prices with the ask-to-sale factor undone."""
    prices = row.pipeline
    if prices.low_cents is None or prices.typical_cents is None or prices.high_cents is None:
        return prices
    return score(
        row.reference_cents,
        round(prices.low_cents / factor),
        round(prices.typical_cents / factor),
        round(prices.high_cents / factor),
    )


def slim_response(response: dict[str, Any]) -> dict[str, Any]:
    """Keep what scoring reads, which leaves out the key, sellers and SerpApi's archive links."""
    stripped = strip_private_fields(response)
    fields = ("title", "price", "condition", "link", "product_id")
    return {
        "search_parameters": stripped.get("search_parameters"),
        "total_results": (stripped.get("search_information") or {}).get("total_results"),
        "organic_results": [
            {name: result[name] for name in fields if name in result}
            for result in stripped.get("organic_results") or []
        ],
    }


class SavedSearches:
    """An EbaySearch that answers from the saved responses, and only searches when allowed to."""

    def __init__(
        self,
        directory: Path = SEARCHES_DIR,
        live: EbaySearch | None = None,
        allowed: int = 0,
        budget: int = SEARCH_BUDGET,
    ) -> None:
        self.directory = directory
        self.live = live
        self.allowed = allowed
        self.budget = budget
        self.spent = 0

    def path(self, query: str, condition: str) -> Path:
        slug = re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-")[:60]
        digest = hashlib.sha256(f"{query}\n{condition}".encode()).hexdigest()[:8]
        return self.directory / f"{slug}-{digest}.json"

    def saved_count(self) -> int:
        return len(list(self.directory.glob("*.json")))

    def __call__(self, query: str, condition: str) -> dict[str, Any]:
        path = self.path(query, condition)
        if path.exists():
            return json.loads(path.read_text())
        if self.live is None:
            raise EvaluationStopped(
                f'No saved search for "{query}", so run again with --live-searches to allow one.'
            )
        if self.spent >= self.allowed:
            raise EvaluationStopped(
                f'--live-searches {self.allowed} is used up, before "{query}" could be searched.'
            )
        if self.saved_count() >= self.budget:
            raise EvaluationStopped(f"This set's budget of {self.budget} searches is spent.")
        response = slim_response(self.live(query, condition))
        self.spent += 1
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(response, indent=1, ensure_ascii=False) + "\n")
        return response


def card_path(item: EvalItem, directory: Path = CARDS_DIR) -> Path:
    return directory / f"{item.id}.json"


def load_card(item: EvalItem, directory: Path = CARDS_DIR) -> SavedCard:
    path = card_path(item, directory)
    if not path.exists():
        raise EvaluationStopped(f"No saved card for {item.id}, so run again with --read-cards.")
    return SavedCard.model_validate_json(path.read_bytes())


def download_photo(item: EvalItem, directory: Path = PHOTOS_DIR) -> bytes:
    """The fixed photo, checked against its recorded hash and kept out of the repo."""
    path = directory / f"{item.id}{Path(item.photo.file).suffix.lower()}"
    if path.exists():
        data = path.read_bytes()
    else:
        response = httpx2.get(
            item.photo.url,
            headers={"User-Agent": COMMONS_USER_AGENT},
            follow_redirects=True,
            timeout=60,
        )
        response.raise_for_status()
        data = response.content
    # Commons records SHA-1, and this only checks that the file is the one recorded.
    actual = hashlib.sha1(data, usedforsecurity=False).hexdigest()
    if actual != item.photo.sha1:
        raise EvaluationStopped(f"The photo for {item.id} has changed at its source.")
    directory.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


def read_missing_cards(
    items: list[EvalItem], providers: list[ChatModel], directory: Path = CARDS_DIR
) -> int:
    """Ask the vision model for each missing card, with the staff entries as notes."""
    missing = [item for item in items if not card_path(item, directory).exists()]
    directory.mkdir(parents=True, exist_ok=True)
    for index, item in enumerate(missing):
        if index:
            time.sleep(SECONDS_BETWEEN_CARDS)
        notes = staff_notes(item.staff.model_dump(mode="json"), None)
        result = read_item_card([prepare_photo(download_photo(item))], providers, notes)
        saved = SavedCard(provider=result.provider, card=result.card)
        card_path(item, directory).write_text(saved.model_dump_json(indent=2) + "\n")
    return len(missing)


def _item_card(item: EvalItem, draft: ItemCardDraft) -> ItemCard:
    return ItemCard(
        item_id=uuid5(NAMESPACE_URL, f"turnstone-eval:{item.id}"),
        **draft.model_dump(),
        **item.staff.model_dump(),
    )


def score_item(item: EvalItem, session: Session, searches: SavedSearches) -> ItemScore:
    """The model's card goes straight to pricing, with no staff correction of its search."""
    draft = load_card(item).card
    result = price_item(_item_card(item, draft), session, searches)
    search = result.rules_config["search"]
    if search["outcome"] in FAILED_SEARCH_OUTCOMES:
        raise EvaluationStopped(f"The search for {item.id} ended with {search['outcome']}.")

    reference = item.reference.price_cents
    pipeline = score(
        reference, result.price_low_cents, result.price_typical_cents, result.price_high_cents
    ).model_copy(update={"comps_count": result.comps_count})
    # The first query's page, which is what someone looking up the item would see first.
    raw = parse_comps(searches(search["queries"][0], search["condition"]))
    return ItemScore(
        id=item.id,
        category=item.category,
        reference_cents=reference,
        search_query=draft.search_query,
        queries_searched=search["queries"],
        model_confidence=draft.model_confidence.value,
        needed_confirmation=needs_confirmation(draft.brand, draft.model_confidence),
        pipeline_confidence=result.confidence.value,
        pipeline_recommendation=result.recommendation.value,
        pipeline=pipeline,
        baseline=baseline_prices(raw, reference),
    )


def evaluate(items: list[EvalItem], session: Session, searches: SavedSearches) -> Results:
    scores = [score_item(item, session, searches) for item in items]
    groups = {"all": compare(scores)}
    for category in Category:
        groups[category.value] = compare([row for row in scores if row.category is category])
    rules = get_settings().pricing
    undone = [before_factor(row, rules.ask_to_sale_factor) for row in scores]
    ratios = [
        prices.typical_cents / row.reference_cents
        for prices, row in zip(undone, scores, strict=True)
        if prices.typical_cents is not None
    ]
    return Results(
        groups=groups,
        pipeline_before_factor=summarize(undone),
        median_ask_over_reference=round(statistics.median(ratios), 2) if ratios else None,
        searches_saved=searches.saved_count(),
        rules=rules.model_dump(),
        items=scores,
    )


def _money(cents: int | None) -> str:
    return "none" if cents is None else f"${cents / 100:,.2f}"


def _range(prices: Prices) -> str:
    if prices.low_cents is None:
        return "no price"
    return f"{_money(prices.low_cents)} to {_money(prices.high_cents)}"


def _percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f}%"


def _yes_no(value: bool | None) -> str:
    return "n/a" if value is None else "yes" if value else "no"


def _in_range(prices: Prices) -> str:
    return "yes" if prices.in_range else "no"


def _source_link(item: EvalItem) -> str:
    reference = item.reference
    if isinstance(reference, PriceGuideReference):
        return f"[{reference.source}]({reference.url}), {reference.tier}, {reference.sales_volume}"
    return f"[{reference.source}]({reference.search_url}), recorded by {reference.recorded_by}"


def _summary_row(label: str, summary: Summary) -> str:
    rate = "n/a" if summary.in_range_rate is None else f"{summary.in_range_rate * 100:.1f}%"
    return (
        f"| {label} | {summary.items} | {summary.priced} | {summary.in_range} | {rate} "
        f"| {_percent(summary.median_error_percent)} |"
    )


def _scored_category_names(results: Results) -> tuple[list[str], list[str]]:
    scored = [c.value for c in Category if results.groups[c.value].pipeline.items]
    unscored = [c.value for c in Category if not results.groups[c.value].pipeline.items]
    return scored, unscored


def render_report(items: list[EvalItem], results: Results) -> str:
    """The results as Markdown, generated so that a change shows up in review."""
    by_id = {item.id: item for item in items}
    overall = results.groups["all"]
    scored, unscored = _scored_category_names(results)
    lines = [
        "# Pricing evaluation",
        "",
        "This page is generated by `uv run python -m app.evaluate` in `api/`, so edit the script "
        "or `api/eval/items.json` instead of this page.",
        "",
    ]
    if unscored:
        names = ", ".join(unscored)
        lines += [
            f"**Not scored yet: {names}.** These results say nothing about pricing in that "
            "category, so they can't stand for the whole pipeline.",
            "",
        ]
    lines += [
        "## Results",
        "",
        "| Method | Items | Priced | In range | In-range rate | Median error |",
        "| --- | --- | --- | --- | --- | --- |",
        _summary_row("Pipeline", overall.pipeline),
        _summary_row("Baseline, raw asking prices", overall.baseline),
        _summary_row("Pipeline with the factor undone, not a rule", results.pipeline_before_factor),
        "",
        f"The pipeline beats the baseline on in-range rate: "
        f"{_yes_no(overall.pipeline_beats_baseline_on_in_range)}.",
        f"The pipeline beats the baseline on median error: "
        f"{_yes_no(overall.pipeline_beats_baseline_on_median_error)}.",
        f"Before the ask-to-sale factor, the pipeline's typical asking price is a median "
        f"{results.median_ask_over_reference} times the reference.",
        f"Scored categories: {', '.join(scored) or 'none'}.",
        f"Item cards that would have stopped for staff confirmation: "
        f"{sum(row.needed_confirmation for row in results.items)} of {len(results.items)}.",
        f"Searches saved for this set: {results.searches_saved} of {SEARCH_BUDGET}.",
        "",
        "## How it is scored",
        "",
        "- The pipeline is the vision model's item card, unedited, passed through `price_item`.",
        "- The baseline is the 25th, 50th and 75th percentile of every listing on the first "
        "search's page, with no filter, trim or ask-to-sale factor.",
        "- An item is in range when its reference price falls between the low and the high.",
        "- An item with no price counts as out of range, and median error covers priced items.",
        "- Error is the distance from the typical price to the reference, as a percent of the "
        "reference.",
        "- The rules were not changed for this set, and items were fixed before the first run.",
        "",
        "## Limits",
        "",
        "- This is a small set, so one or two items can move each number.",
        "- PriceCharting's prices come from completed eBay sales through its own calculation, so "
        "they are sold prices from the same marketplace as the comps, not from another market.",
        "- Whether PriceCharting's prices include shipping was not checked, and comps omit it.",
        "- A loose console can differ from a listing in what comes with it, such as a controller.",
        "- Most photos are clean studio shots on white, which are easier than a thrift store's.",
        "- PriceCharting's prices are cited here for scoring only, and the app never reads them.",
        "- Live searches here go through the saved responses, so they do not add `comp_searches` "
        "rows and are not counted against `SERPAPI_MONTHLY_BUDGET`.",
        "",
        "## Items",
        "",
        "Prices were recorded by hand from each linked page, on the date shown, and the script "
        "never fetches them.",
        "",
        "| Item | Reference | Source | Recorded | Pipeline range | Typical | In range | Error "
        "| Baseline range | Typical | In range | Error |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in results.items:
        item = by_id[row.id]
        lines.append(
            f"| {item.name} | {_money(row.reference_cents)} | {_source_link(item)} "
            f"| {item.reference.recorded_on} | {_range(row.pipeline)} "
            f"| {_money(row.pipeline.typical_cents)} | {_in_range(row.pipeline)} "
            f"| {_percent(row.pipeline.error_percent)} | {_range(row.baseline)} "
            f"| {_money(row.baseline.typical_cents)} | {_in_range(row.baseline)} "
            f"| {_percent(row.baseline.error_percent)} |"
        )
    lines += [
        "",
        "## Searches",
        "",
        "| Item | Search from the card | Model confidence | Searches | Comps kept | Pipeline "
        "confidence | Recommendation |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in results.items:
        lines.append(
            f"| {by_id[row.id].name} | {row.search_query} | {row.model_confidence} "
            f"| {len(row.queries_searched)} | {row.pipeline.comps_count} "
            f"| {row.pipeline_confidence} | {row.pipeline_recommendation} |"
        )
    lines += ["", "## Photos and item notes", "", "| Item | Photo | Author | License | Note |"]
    lines.append("| --- | --- | --- | --- | --- |")
    for item in items:
        photo = item.photo
        lines.append(
            f"| {item.name} | [{photo.file}]({photo.page.replace(' ', '%20')}) | {photo.author} "
            f"| {photo.license} | {item.note or ''} |"
        )
    return "\n".join(lines) + "\n"


def results_json(results: Results) -> str:
    return results.model_dump_json(indent=2) + "\n"


def run(session: Session, searches: SavedSearches) -> Results:
    items = load_items()
    results = evaluate(items, session, searches)
    RESULTS_FILE.write_text(results_json(results))
    REPORT_FILE.write_text(render_report(items, results))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--read-cards", action="store_true", help="read missing cards by model")
    parser.add_argument(
        "--live-searches", type=int, default=0, help="new SerpApi searches this run may spend"
    )
    args = parser.parse_args()

    settings = get_settings()
    if args.read_cards:
        fallback = get_fallback_chat_model()
        providers = [get_chat_model(), *([fallback] if fallback else [])]
        print(f"Read {read_missing_cards(load_items(), providers)} cards.")

    live = None
    if args.live_searches:
        if not settings.serpapi_api_key:
            raise SystemExit("Set SERPAPI_API_KEY to allow live searches.")
        live = serpapi_ebay_search(settings.serpapi_api_key)
    searches = SavedSearches(live=live, allowed=args.live_searches)

    # Every row is rolled back, so replaying saved searches can't count against the app's budget.
    with get_engine().connect() as connection:
        transaction = connection.begin()
        connection.execute(sa.delete(CompSearch))
        with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
            try:
                results = run(session, searches)
            except EvaluationStopped as error:
                print(f"Searches spent this run: {searches.spent}.")
                raise SystemExit(str(error)) from None
            finally:
                transaction.rollback()

    overall = results.groups["all"]
    print(f"Searches spent this run: {searches.spent}, saved in all: {results.searches_saved}.")
    print(f"Pipeline: {overall.pipeline.model_dump()}")
    print(f"Baseline: {overall.baseline.model_dump()}")
    print(f"Wrote {RESULTS_FILE} and {REPORT_FILE}.")


if __name__ == "__main__":
    main()
