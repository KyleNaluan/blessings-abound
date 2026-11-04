import pytest

from app.claims import ClaimRule, ListingFacts, check_listing, check_text
from app.models import Category, Condition, Department, Flaw

GAME = ListingFacts(
    category=Category.ELECTRONICS_GAMES,
    condition=Condition.PRE_OWNED,
    brand="Nintendo",
    product="Mario Kart 8 Deluxe",
    platform="Nintendo Switch",
    visible_text="MARIO KART 8 DELUXE",
    tested_working=None,
    complete_in_box=False,
)

HOODIE = ListingFacts(
    category=Category.APPAREL,
    condition=Condition.PRE_OWNED,
    brand="Nike",
    product="pullover hoodie",
    color="grey",
    department=Department.MENS,
    size="M",
    size_type="letter",
)


def phrases(text: str, facts: ListingFacts, rule: ClaimRule | None = None) -> set[str]:
    return {flag.phrase for flag in check_text(text, facts) if rule is None or flag.rule is rule}


def test_a_draft_that_only_restates_the_card_passes() -> None:
    text = "Nintendo Switch Mario Kart 8 Deluxe, pre-owned. See the photos for the exact item."
    assert check_text(text, GAME) == []


@pytest.mark.parametrize("word", ["rare", "authentic", "antique", "vintage", "genuine", "mint"])
def test_banned_words_are_flagged(word: str) -> None:
    assert word in phrases(f"A {word} copy of Mario Kart 8 Deluxe.", GAME)


def test_a_banned_word_is_matched_whole_and_in_any_case() -> None:
    assert "rare" in phrases("RARE find", GAME, ClaimRule.BANNED_WORD)
    assert phrases("Prepared and shipped quickly.", GAME, ClaimRule.BANNED_WORD) == set()


def test_a_banned_word_on_the_card_itself_is_allowed() -> None:
    facts = ListingFacts(
        category=Category.APPAREL,
        condition=Condition.PRE_OWNED,
        brand="Levi's",
        product="vintage wash jeans",
    )
    assert "vintage" not in phrases("Levi's vintage wash jeans.", facts)


def test_a_brand_the_card_lacks_is_flagged() -> None:
    assert phrases("Works with Sony PlayStation 5.", GAME, ClaimRule.BRAND) >= {"sony"}


def test_a_brand_alias_of_the_card_brand_is_allowed() -> None:
    assert phrases("Mario Kart 8 Deluxe for Switch.", GAME, ClaimRule.BRAND) == set()


def test_a_number_the_card_lacks_is_flagged() -> None:
    assert phrases("Released in 2017.", GAME, ClaimRule.NUMBER) == {"2017"}
    assert phrases("Mario Kart 8 Deluxe.", GAME, ClaimRule.NUMBER) == set()


def test_a_number_word_the_card_lacks_is_flagged() -> None:
    assert "two" in phrases("Includes two controllers.", GAME, ClaimRule.NUMBER)


def test_a_size_the_card_lacks_is_flagged() -> None:
    found = phrases("Nike pullover hoodie, size L, slim fit.", HOODIE, ClaimRule.SIZE)
    assert {"L", "size L", "slim fit"} <= found


def test_the_card_size_is_allowed() -> None:
    assert phrases("Nike pullover hoodie, size M, men's.", HOODIE) == set()


def test_a_department_the_card_lacks_is_flagged() -> None:
    assert "womens" in phrases("Women's Nike hoodie.", HOODIE, ClaimRule.SIZE)


def test_a_lowercase_letter_is_not_read_as_a_size() -> None:
    assert phrases("A grey hoodie in m condition.", HOODIE, ClaimRule.SIZE) == set()


def test_a_condition_the_card_lacks_is_flagged() -> None:
    found = phrases("Brand new, factory sealed, tested and working.", GAME, ClaimRule.CONDITION)
    assert {"brand new", "factory sealed", "tested"} <= found


def test_the_card_condition_is_allowed() -> None:
    assert phrases("Pre-owned and used.", GAME, ClaimRule.CONDITION) == set()


def test_a_negated_claim_is_allowed() -> None:
    assert phrases("Not tested. No box.", GAME, ClaimRule.CONDITION) == set()


def test_a_negation_does_not_reach_into_the_next_clause() -> None:
    assert "tested" in phrases("No box, but tested.", GAME, ClaimRule.CONDITION)


def test_a_grade_is_flagged_even_when_negated() -> None:
    assert "no flaws" in phrases("Pre-owned with no flaws.", GAME, ClaimRule.CONDITION)


def test_working_is_allowed_when_staff_tested_it() -> None:
    tested = ListingFacts(
        category=Category.ELECTRONICS_GAMES, condition=Condition.PRE_OWNED, tested_working=True
    )
    assert phrases("Tested and working.", tested, ClaimRule.CONDITION) == set()


def test_a_box_claim_is_allowed_when_staff_recorded_it() -> None:
    boxed = ListingFacts(
        category=Category.ELECTRONICS_GAMES, condition=Condition.PRE_OWNED, complete_in_box=True
    )
    assert phrases("Complete in box with manual.", GAME, ClaimRule.CONDITION) != set()
    assert phrases("Complete in box.", boxed, ClaimRule.CONDITION) == set()


def test_a_flaw_is_allowed_only_when_the_card_records_it() -> None:
    stained = ListingFacts(
        category=Category.APPAREL, condition=Condition.PRE_OWNED, flaws=(Flaw.STAINS,)
    )
    assert "stain" in phrases("A small stain on the cuff.", HOODIE, ClaimRule.CONDITION)
    assert phrases("A small stain on the cuff.", stained, ClaimRule.CONDITION) == set()


def test_a_new_item_may_say_new_but_not_used() -> None:
    new = ListingFacts(category=Category.APPAREL, condition=Condition.NEW_WITH_TAGS)
    assert phrases("New with tags.", new, ClaimRule.CONDITION) == set()
    assert "used" in phrases("Barely used.", new, ClaimRule.CONDITION)


def test_curly_apostrophes_and_accents_match_like_plain_ones() -> None:
    assert "womens" in phrases("Women\u2019s hoodie.", HOODIE, ClaimRule.SIZE)
    assert "rare" in phrases("R\u00e1re hoodie.", HOODIE, ClaimRule.BANNED_WORD)


def test_quoted_text_from_the_card_claims_nothing() -> None:
    facts = ListingFacts(
        category=Category.ELECTRONICS_GAMES,
        condition=Condition.PRE_OWNED,
        brand="Nintendo",
        product="Game Boy Advance",
        visible_text="GAME BOY ADVANCE, TESTED",
    )
    assert check_text('A clear casing with "GAME BOY ADVANCE" on it.', facts) == []
    assert check_text("It reads \u201cTESTED\u201d.", facts) == []
    assert "with game" in phrases("A clear casing with GAME BOY ADVANCE on it.", facts)


def test_quoted_text_not_on_the_card_is_still_checked() -> None:
    assert "rare" in phrases('It reads "RARE EDITION".', GAME, ClaimRule.BANNED_WORD)


def test_the_title_and_description_are_checked_apart_and_flagged_once() -> None:
    flags = check_listing("Rare Mario Kart 8 Deluxe", "Not rare, but tested.", GAME)
    assert [(flag.rule, flag.phrase) for flag in flags] == [
        (ClaimRule.BANNED_WORD, "rare"),
        (ClaimRule.CONDITION, "tested"),
    ]


def test_each_flag_says_what_is_wrong() -> None:
    (flag,) = check_text("Rare.", GAME)
    assert flag.message == '"rare" is a word listings never use.'
