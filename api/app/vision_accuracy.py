"""Score how well the saved item cards read brand, category and product, apart from pricing.

Run `uv run python -m app.vision_accuracy` in api/ to compare the saved cards in api/eval/cards/
with api/eval/vision_labels.json and rewrite the results. It makes no model call and needs no keys.
See docs/vision-accuracy.md for the matching rule.
"""

import hashlib
import re
import unicodedata
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from pydantic import TypeAdapter

from app.evaluate import (
    EVAL_DIR,
    EvalItem,
    EvaluationStopped,
    PhotoSource,
    SavedCard,
    _Strict,
    load_card,
    load_fresh_items,
    load_items,
)
from app.models import Category
from app.vision import PROMPT, ItemCardDraft

LABELS_FILE = EVAL_DIR / "vision_labels.json"
RESULTS_FILE = EVAL_DIR / "vision_results.json"
REPORT_FILE = Path(__file__).resolve().parents[2] / "docs" / "vision-accuracy.md"

Outcome = Literal["correct", "near_miss", "wrong", "missing"]
OUTCOMES: tuple[Outcome, ...] = ("correct", "near_miss", "wrong", "missing")

# Each alternative is a list of phrases that must all appear for that alternative to match.
Terms = list[list[str]]


class VisionLabel(_Strict):
    id: str
    category: Category
    # None means the item has no brand anyone could name, and the accepted lists are then empty.
    brand: str | None
    brand_accepted: list[str]
    brand_near: list[str]
    product: str
    product_right: Terms
    product_near: Terms
    product_wrong: list[str]
    labelled_by: str
    checked_by: str | None
    photo: PhotoSource


class ItemResult(_Strict):
    id: str
    provider: str
    brand_label: str | None
    brand_read: str | None
    brand: Outcome
    category_label: Category
    category_read: Category
    category: Outcome
    product_label: str
    product_read: str
    product: Outcome


class Accuracy(_Strict):
    items: int
    correct: int
    near_miss: int
    wrong: int
    missing: int
    accuracy: float | None


class VisionResults(_Strict):
    labels: int
    labels_checked_by_a_person: int
    prompt_sha256: str
    providers: dict[str, int]
    brand: Accuracy
    category: Accuracy
    product: Accuracy
    items: list[ItemResult]


RULE_LINES = [
    "Accuracy is the share of cards marked correct, and a near miss counts against it, so the "
    "headline number never gives partial credit.",
    "Text is compared in lower case with accents and punctuation removed, on whole words.",
    "",
    "- **Brand** reads only the card's `brand` field.",
    "  It is correct when it contains an accepted name, which is the maker or publisher of the "
    "item, and any other name in the label's `brand_accepted`.",
    "  It is a near miss when it contains a product line or series instead of the company, such "
    'as "PlayStation" for Sony, from `brand_near`.',
    "  Any other name is wrong, and an empty field is missing.",
    "- **Unknown-brand items** have a label of no brand.",
    "  An empty field is then correct, and naming any brand is wrong, because a guessed brand "
    "would send the search the wrong way.",
    "  This set has none of these items, so the rule is not exercised by the results here.",
    "- **Category** reads the card's `category` field and must equal the label, with no near miss.",
    "- **Product** reads the card's `product`, `exact_model` and `search_query` fields together, "
    "because the prompt keeps `product` plain and puts the name in the other two.",
    "  It leaves out `platform` and `visible_text`, so a platform or a logo alone doesn't name "
    "the item.",
    "  It is wrong when it contains a phrase from `product_wrong`, which names a different system "
    "or model from the same maker, even if a right phrase also appears.",
    "  It is otherwise correct when every phrase of one `product_right` alternative appears.",
    "  The product is the system, accessory or game title a buyer would name, so color, storage "
    "size, region and revisions such as Slim or Model 2 aren't required.",
    "  Models sold under their own name are required, such as the Game Boy Color, the DS Lite and "
    "the 3DS XL.",
    "  It is a near miss when it matches a `product_near` alternative, which is the right family "
    "or kind of thing without the specific product, such as a game cartridge with no title.",
    "  Anything else is wrong, and the model can't leave this empty because `search_query` is "
    "required.",
    "",
    "Labels come from the identity already recorded for each item in `api/eval/items.json` and "
    "`api/eval/fresh_items.json`, not from what the model read.",
    "`labelled_by` says who wrote each label, and `checked_by` stays empty until a person has "
    "looked at the photo and label together.",
]


def load_labels(path: Path = LABELS_FILE) -> list[VisionLabel]:
    return TypeAdapter(list[VisionLabel]).validate_json(path.read_bytes())


def normalize(text: str) -> str:
    """Lower case words with single spaces and no accents or punctuation, padded to match words."""
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return f" {re.sub(r'[^a-z0-9]+', ' ', plain.lower()).strip()} "


def contains(text: str, phrase: str) -> bool:
    return normalize(phrase) in normalize(text)


def _matches_all(text: str, alternatives: Terms) -> bool:
    return any(all(contains(text, phrase) for phrase in terms) for terms in alternatives)


def score_brand(label: VisionLabel, read: str | None) -> Outcome:
    if label.brand is None:
        return "correct" if read is None else "wrong"
    if read is None or not normalize(read).strip():
        return "missing"
    if any(contains(read, name) for name in label.brand_accepted):
        return "correct"
    return "near_miss" if any(contains(read, name) for name in label.brand_near) else "wrong"


def product_text(card: ItemCardDraft) -> str:
    parts = (card.product, card.exact_model, card.search_query)
    return " | ".join(part for part in parts if part)


def score_product(label: VisionLabel, read: str) -> Outcome:
    if not normalize(read).strip():
        return "missing"
    if any(contains(read, phrase) for phrase in label.product_wrong):
        return "wrong"
    if _matches_all(read, label.product_right):
        return "correct"
    return "near_miss" if _matches_all(read, label.product_near) else "wrong"


def score_item(label: VisionLabel, saved: SavedCard) -> ItemResult:
    card = saved.card
    read = product_text(card)
    return ItemResult(
        id=label.id,
        provider=saved.provider,
        brand_label=label.brand,
        brand_read=card.brand,
        brand=score_brand(label, card.brand),
        category_label=label.category,
        category_read=card.category,
        category="correct" if card.category is label.category else "wrong",
        product_label=label.product,
        product_read=read,
        product=score_product(label, read),
    )


def accuracy(outcomes: Sequence[Outcome]) -> Accuracy:
    counts = Counter(outcomes)
    return Accuracy(
        items=len(outcomes),
        correct=counts["correct"],
        near_miss=counts["near_miss"],
        wrong=counts["wrong"],
        missing=counts["missing"],
        accuracy=round(counts["correct"] / len(outcomes), 3) if outcomes else None,
    )


def summarize(labels: list[VisionLabel], rows: list[ItemResult]) -> VisionResults:
    return VisionResults(
        labels=len(labels),
        labels_checked_by_a_person=sum(label.checked_by is not None for label in labels),
        prompt_sha256=hashlib.sha256(PROMPT.encode()).hexdigest(),
        providers=dict(sorted(Counter(row.provider for row in rows).items())),
        brand=accuracy([row.brand for row in rows]),
        category=accuracy([row.category for row in rows]),
        product=accuracy([row.product for row in rows]),
        items=rows,
    )


def labelled_items() -> list[EvalItem]:
    """The games and hardware items, because no apparel label has been written yet."""
    items = [*load_items(), *load_fresh_items()]
    return [item for item in items if item.category is not Category.APPAREL]


def check_labels(labels: list[VisionLabel], items: list[EvalItem]) -> None:
    """Every evaluation item has one label, with the photo that item's card was read from."""
    by_id = {item.id: item for item in items}
    label_ids = [label.id for label in labels]
    if sorted(label_ids) != sorted(by_id):
        raise EvaluationStopped("The labels and the evaluation items don't list the same ids.")
    for label in labels:
        if label.photo != by_id[label.id].photo:
            raise EvaluationStopped(f"The label for {label.id} records a different photo.")


def _rate(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def _row(name: str, score: Accuracy) -> str:
    return (
        f"| {name} | {score.items} | {score.correct} | {_rate(score.accuracy)} "
        f"| {score.near_miss} | {score.wrong} | {score.missing} |"
    )


TABLE_HEAD = [
    "| Measure | Items | Correct | Accuracy | Near miss | Wrong | Missing |",
    "| --- | --- | --- | --- | --- | --- | --- |",
]


def _cell(text: str | None) -> str:
    return "none" if text is None else text.replace("|", "/")


def render_report(results: VisionResults) -> str:
    """The results as Markdown, generated so that a change shows up in review."""
    providers = ", ".join(f"`{name}` {count}" for name, count in results.providers.items())
    lines = [
        "# Vision accuracy",
        "",
        "This page is generated by `uv run python -m app.vision_accuracy` in `api/`, so edit the "
        "script or `api/eval/vision_labels.json` instead of this page.",
        "It measures reading the item, and [evaluation.md](evaluation.md) measures pricing.",
        "",
        f"**Labels checked by a person: {results.labels_checked_by_a_person} "
        f"of {results.labels}.** "
        + (
            "An AI coding agent wrote the labels from each item's recorded identity, and a person "
            "then checked every one."
            if results.labels_checked_by_a_person == results.labels
            else "An AI coding agent wrote the labels from each item's recorded identity, so treat "
            "these numbers as provisional until a person has checked the rest."
        ),
        "",
        "**Not measured: apparel.** Every item here is games or hardware, so these results say "
        "nothing about reading clothing.",
        "",
        "## Result",
        "",
        *TABLE_HEAD,
        _row("Brand", results.brand),
        _row("Category", results.category),
        _row("Product", results.product),
        "",
        "## How it is matched",
        "",
        *RULE_LINES,
        "",
        "## Limits",
        "",
        "- These are public Wikimedia Commons photos, many of them clean studio shots on white, "
        "and not photos from a thrift store, so a store's photos may read worse.",
        "- The category score is close to empty, because every label is games or hardware and "
        "the model only chooses between two categories.",
        "- The items were chosen for pricing and need a price guide page, so they lean toward "
        "well known consoles and games, and aren't a random sample of donations.",
        "- With this few items, one or two cards move each number by a few points.",
        "- The rule is strict about names in the brand field, so ColecoVision for Coleco counts as "
        "wrong, and no label or rule changed after the first score, which `git log` shows.",
        "- The labels were written with the pricing report's card searches already public in "
        "[evaluation.md](evaluation.md), so the writer had seen some of what the model read, and "
        "the person check is what guards against that.",
        "",
        "## Where the cards came from",
        "",
        f"These are the saved cards in `api/eval/cards/`: {providers}.",
        "The Gemini card is the fallback provider's answer for that item, which is what the item "
        "card step returned, and it uses the same prompt.",
        f"The prompt's SHA-256 is `{results.prompt_sha256}`, so changing the prompt changes this "
        "page, and the cards then need reading again.",
        "",
        "## Items",
        "",
        "| Item | Brand label | Brand read | Brand | Product read | Product |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in results.items:
        lines.append(
            f"| {row.product_label} "
            f"| {_cell(row.brand_label)} | {_cell(row.brand_read)} | {row.brand} "
            f"| {_cell(row.product_read)} | {row.product} |"
        )
    return "\n".join(lines) + "\n"


def results_json(results: VisionResults) -> str:
    return results.model_dump_json(indent=2) + "\n"


def run() -> VisionResults:
    labels = load_labels()
    items = {item.id: item for item in labelled_items()}
    check_labels(labels, list(items.values()))
    rows = [score_item(label, load_card(items[label.id])) for label in labels]
    return summarize(labels, rows)


def main() -> None:
    try:
        results = run()
    except EvaluationStopped as error:
        raise SystemExit(str(error)) from None
    RESULTS_FILE.write_text(results_json(results), encoding="utf-8", newline="\n")
    REPORT_FILE.write_text(render_report(results), encoding="utf-8", newline="\n")
    for name, score in (
        ("Brand", results.brand),
        ("Category", results.category),
        ("Product", results.product),
    ):
        print(f"{name}: {score.correct} of {score.items}, {_rate(score.accuracy)}")
    print(f"Wrote {RESULTS_FILE} and {REPORT_FILE}. No model calls were made.")


if __name__ == "__main__":
    main()
