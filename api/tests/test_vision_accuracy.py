from typing import Any

import pytest

from app.evaluate import EvaluationStopped, PhotoSource, SavedCard, load_fresh_items, load_items
from app.models import Category, Confidence
from app.vision import ItemCardDraft
from app.vision_accuracy import (
    REPORT_FILE,
    RESULTS_FILE,
    VisionLabel,
    accuracy,
    check_labels,
    load_labels,
    normalize,
    product_text,
    render_report,
    results_json,
    run,
    score_brand,
    score_item,
    score_product,
)

PHOTO = PhotoSource(
    file="a.jpg",
    url="https://e.com/a.jpg",
    page="https://e.com/a",
    sha1="x",
    license="CC0",
    author="A",
)


def label(**changes: Any) -> VisionLabel:
    values: dict[str, Any] = {
        "id": "game-boy",
        "category": Category.ELECTRONICS_GAMES,
        "brand": "Nintendo",
        "brand_accepted": ["Nintendo"],
        "brand_near": ["Game Boy"],
        "product": "Game Boy",
        "product_right": [["game boy"]],
        "product_near": [["nintendo", "handheld"]],
        "product_wrong": ["game boy color"],
        "labelled_by": "someone",
        "checked_by": None,
        "photo": PHOTO,
    }
    return VisionLabel(**{**values, **changes})


def card(**changes: Any) -> ItemCardDraft:
    values: dict[str, Any] = {
        "category": Category.ELECTRONICS_GAMES,
        "brand": "Nintendo",
        "product": "handheld game console",
        "search_query": "Nintendo Game Boy",
        "model_confidence": Confidence.HIGH,
    }
    return ItemCardDraft(**{**values, **changes})


def test_normalize_ignores_case_accents_and_punctuation() -> None:
    assert normalize("Pokémon: BLACK!") == " pokemon black "


@pytest.mark.parametrize(
    ("read", "outcome"),
    [
        ("NINTENDO", "correct"),
        ("Nintendo of America", "correct"),
        ("Game Boy", "near_miss"),
        ("Sega", "wrong"),
        (None, "missing"),
        ("  ", "missing"),
    ],
)
def test_brand_outcomes(read: str | None, outcome: str) -> None:
    assert score_brand(label(), read) == outcome


def test_a_partial_word_is_not_a_brand_match() -> None:
    assert score_brand(label(brand_accepted=["Sega"], brand_near=[]), "Segal") == "wrong"


@pytest.mark.parametrize(("read", "outcome"), [(None, "correct"), ("Nintendo", "wrong")])
def test_an_unknown_brand_item_is_right_only_with_no_brand(read: str | None, outcome: str) -> None:
    unknown = label(brand=None, brand_accepted=[], brand_near=[])
    assert score_brand(unknown, read) == outcome


@pytest.mark.parametrize(
    ("read", "outcome"),
    [
        ("Nintendo Game Boy", "correct"),
        ("Nintendo Game Boy Color", "wrong"),
        ("Nintendo handheld console", "near_miss"),
        ("handheld console", "wrong"),
        ("Sega Game Gear", "wrong"),
    ],
)
def test_product_outcomes(read: str, outcome: str) -> None:
    assert score_product(label(), read) == outcome


def test_every_phrase_of_an_alternative_must_appear() -> None:
    both = label(product_right=[["switch", "pro controller"]], product_near=[], product_wrong=[])
    assert score_product(both, "Switch Pro Controller") == "correct"
    assert score_product(both, "Switch controller") == "wrong"


def test_product_reads_the_named_fields_but_not_the_platform_or_visible_text() -> None:
    draft = card(
        product="console",
        exact_model="Model X",
        search_query="query words",
        platform="Game Boy",
        visible_text="GAME BOY",
    )
    assert product_text(draft) == "console | Model X | query words"
    assert score_product(label(), product_text(draft)) == "wrong"


def test_a_near_miss_counts_against_accuracy() -> None:
    score = accuracy(["correct", "near_miss", "wrong", "missing"])
    assert (score.correct, score.near_miss, score.wrong, score.missing) == (1, 1, 1, 1)
    assert score.accuracy == 0.25
    assert accuracy([]).accuracy is None


def test_a_wrong_category_is_wrong_with_no_near_miss() -> None:
    saved = SavedCard(provider="p", card=card(category=Category.APPAREL))
    assert score_item(label(), saved).category == "wrong"


def test_every_evaluation_item_has_a_label_with_its_photo() -> None:
    labels = load_labels()
    items = [*load_items(), *load_fresh_items()]
    check_labels(labels, items)
    with pytest.raises(EvaluationStopped):
        check_labels(labels[1:], items)
    changed = labels[0].model_copy(update={"photo": PHOTO})
    with pytest.raises(EvaluationStopped):
        check_labels([changed, *labels[1:]], items)


def test_every_label_says_who_wrote_it() -> None:
    assert all(row.labelled_by for row in load_labels())


def test_the_saved_results_match_the_cards_and_labels() -> None:
    results = run()
    hint = "Run `uv run python -m app.vision_accuracy` in api/ to rewrite the saved results."
    assert results_json(results) == RESULTS_FILE.read_text(encoding="utf-8"), hint
    assert render_report(results) == REPORT_FILE.read_text(encoding="utf-8"), hint
