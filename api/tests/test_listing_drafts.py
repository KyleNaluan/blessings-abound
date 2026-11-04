import json
from dataclasses import replace
from itertools import product

import pytest

from app.claims import ListingFacts, check_listing
from app.listing_drafts import (
    TITLE_MAX,
    build_prompt,
    default_category,
    parse_draft,
    template_draft,
)
from app.models import Category, Channel, Condition, Department, Flaw
from app.pipeline import listing_channels

HOODIE = ListingFacts(
    category=Category.APPAREL,
    condition=Condition.PRE_OWNED,
    brand="Nike",
    product="pullover hoodie",
    color="grey",
    material="cotton",
    department=Department.MENS,
    size="M",
)

SWITCH = ListingFacts(
    category=Category.ELECTRONICS_GAMES,
    condition=Condition.PRE_OWNED,
    brand="Nintendo",
    product="Mario Kart 8 Deluxe game",
    platform="Nintendo Switch",
    complete_in_box=False,
)


def test_games_go_to_channel_a_and_apparel_to_both() -> None:
    assert listing_channels(Category.ELECTRONICS_GAMES) == [Channel.CHANNEL_A]
    assert listing_channels(Category.APPAREL) == [Channel.CHANNEL_A, Channel.CHANNEL_B]


def test_the_template_restates_the_card() -> None:
    draft = template_draft(HOODIE, Channel.CHANNEL_A)
    assert draft.title == "Men's Nike pullover hoodie, Size M, Grey - Pre-owned"
    assert draft.description == (
        "Nike pullover hoodie, pre-owned. Color: grey. Material: cotton. Department: Men's. "
        "Size: M. See the photos for the exact item."
    )
    assert draft.category == "Men's Clothing"
    assert template_draft(HOODIE, Channel.CHANNEL_B).category == "Menswear"


def test_the_template_says_what_staff_recorded_about_a_game() -> None:
    facts = ListingFacts(
        category=Category.ELECTRONICS_GAMES,
        condition=Condition.PRE_OWNED,
        brand="Sony",
        product="DualShock 4 controller",
        platform="PlayStation 4",
        flaws=(Flaw.SCUFFS,),
        tested_working=True,
        complete_in_box=True,
        accessories_included="charging cable",
    )
    draft = template_draft(facts, Channel.CHANNEL_A)
    assert draft.title == "Sony DualShock 4 controller for PlayStation 4 - Pre-owned"
    assert "Flaws: scuffs. Tested and working. Complete in box." in draft.description
    assert "Includes: charging cable." in draft.description
    assert draft.category == "Controllers & Attachments"


def test_a_long_title_drops_details_from_the_end_to_fit() -> None:
    facts = ListingFacts(
        category=Category.APPAREL,
        condition=Condition.NEW_WITH_TAGS,
        brand="Patagonia",
        product="Better Sweater quarter zip fleece pullover jacket",
        color="heather grey with navy trim",
        department=Department.WOMENS,
        size="XL",
    )
    title = template_draft(facts, Channel.CHANNEL_A).title
    # The color and size go first, then the name is cut at a word.
    assert title == "Women's Patagonia Better Sweater quarter zip fleece pullover - New with tags"
    assert len(title) <= TITLE_MAX


@pytest.mark.parametrize(
    ("product_name", "category"),
    [
        ("Switch Lite console", "Video Game Consoles"),
        ("Joy-Con pair", "Controllers & Attachments"),
        ("Halo 3 game", "Video Games"),
        ("charging dock", "Video Game Accessories"),
    ],
)
def test_the_template_picks_a_category_from_the_card(product_name: str, category: str) -> None:
    facts = ListingFacts(
        category=Category.ELECTRONICS_GAMES, condition=Condition.PRE_OWNED, product=product_name
    )
    assert default_category(facts, Channel.CHANNEL_A) == category


def test_shoes_get_a_shoe_category() -> None:
    shoes = ListingFacts(
        category=Category.APPAREL, condition=Condition.PRE_OWNED, product="running shoes"
    )
    assert default_category(shoes, Channel.CHANNEL_A) == "Unisex Shoes"
    assert default_category(shoes, Channel.CHANNEL_B) == "Shoes"


CONDITIONS = list(Condition)
FLAW_SETS = [(), (Flaw.STAINS,), (Flaw.TEARS, Flaw.MISSING_PARTS)]


@pytest.mark.parametrize(
    ("condition", "flaws", "department"),
    list(product(CONDITIONS, FLAW_SETS, [None, *Department])),
)
def test_the_template_never_trips_the_checker_on_apparel(
    condition: Condition, flaws: tuple[Flaw, ...], department: Department | None
) -> None:
    facts = ListingFacts(
        category=Category.APPAREL,
        condition=condition,
        brand="Levi's",
        product="501 jeans",
        color="dark blue",
        material="denim",
        department=department,
        size="32",
        size_type="waist",
        flaws=flaws,
    )
    for channel in listing_channels(Category.APPAREL):
        draft = template_draft(facts, channel)
        assert check_listing(draft.title, draft.description, facts) == []


@pytest.mark.parametrize(
    ("tested", "boxed", "accessories"),
    list(product([None, True, False], [None, True, False], [None, "two controllers"])),
)
def test_the_template_never_trips_the_checker_on_games(
    tested: bool | None, boxed: bool | None, accessories: str | None
) -> None:
    facts = ListingFacts(
        category=Category.ELECTRONICS_GAMES,
        condition=Condition.PRE_OWNED,
        brand="Microsoft",
        product="Xbox 360 console",
        exact_model="Xbox 360 S 250GB",
        tested_working=tested,
        complete_in_box=boxed,
        accessories_included=accessories,
        flaws=(Flaw.SCUFFS,),
    )
    draft = template_draft(facts, Channel.CHANNEL_A)
    assert check_listing(draft.title, draft.description, facts) == []


def test_the_prompt_gives_the_facts_and_the_rules_for_this_item() -> None:
    prompt = build_prompt(SWITCH, Channel.CHANNEL_A)
    assert "- Brand: Nintendo\n" in prompt
    assert "- Platform: Nintendo Switch\n" in prompt
    assert "- Tested and working: not recorded\n" in prompt
    assert "- Complete in box: no\n" in prompt
    assert "Don't say it works, was tested, powers on or plays." in prompt
    assert "Don't mention a box, a manual, packaging or anything it comes with" in prompt
    assert '"includes", "including" or "comes with"' in prompt
    assert '"Video Games", "Video Game Consoles"' in prompt
    assert "{" not in prompt.replace("JSON object", "")


def test_the_prompt_asks_for_the_text_on_the_item_in_quotes() -> None:
    labeled = replace(SWITCH, visible_text="MARIO KART 8 DELUXE")
    assert "It reads and then the text in double quotes" in build_prompt(labeled, Channel.CHANNEL_A)
    assert "It reads" not in build_prompt(SWITCH, Channel.CHANNEL_A)


def test_the_prompt_leaves_out_what_nobody_recorded() -> None:
    prompt = build_prompt(HOODIE, Channel.CHANNEL_B)
    assert "Depop-style" in prompt
    assert "Exact model" not in prompt
    assert "Tested and working" not in prompt
    assert "- Size: M\n" in prompt


def reply(**values: str) -> str:
    return json.dumps({"title": "Nike hoodie", "description": "Nike hoodie."} | values)


def test_a_reply_parses_with_the_channel_category() -> None:
    draft = parse_draft(reply(category="men's clothing", extra="ignored"), ["Men's Clothing"])
    assert draft.category == "Men's Clothing"


def test_a_reply_in_a_fence_after_thinking_parses() -> None:
    text = f"<think>hmm</think>```json\n{reply(category='Menswear')}\n```"
    assert parse_draft(text, ["Menswear"]).title == "Nike hoodie"


@pytest.mark.parametrize(
    "text",
    [
        reply(category="Jackets"),
        reply(category="Menswear", title=""),
        reply(category="Menswear", title="x" * (TITLE_MAX + 1)),
        json.dumps({"title": "Nike hoodie", "category": "Menswear"}),
        "not json",
    ],
)
def test_a_reply_that_is_not_a_usable_draft_is_refused(text: str) -> None:
    with pytest.raises(ValueError):
        parse_draft(text, ["Menswear"])
