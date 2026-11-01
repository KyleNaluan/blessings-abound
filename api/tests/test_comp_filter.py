import pytest

from app.comp_filter import DropReason, ItemFacts, filter_comps
from app.models import Category, Condition, Department
from app.pricing import Comp
from tests.serpapi_fixtures import ITEMS, load_comps

APPAREL = ItemFacts(category=Category.APPAREL, product="Detroit jacket", department=Department.MENS)
AIRPODS = ItemFacts(category=Category.ELECTRONICS_GAMES, product="Apple AirPods Pro")
SWITCH = ItemFacts(
    category=Category.ELECTRONICS_GAMES,
    product="Nintendo Switch console",
    platform="Nintendo Switch",
)
PS4 = ItemFacts(
    category=Category.ELECTRONICS_GAMES,
    product="PlayStation 4 Slim console",
    platform="PlayStation 4",
)
GAME = ItemFacts(
    category=Category.ELECTRONICS_GAMES,
    product="Mario Kart 8 Deluxe",
    platform="Nintendo Switch",
)


def comp(title: str, price_cents: int | None = 5000, condition: str | None = "Pre-Owned") -> Comp:
    return Comp(
        item_id=title,
        title=title,
        url="https://www.ebay.com/itm/1",
        condition=condition,
        price_cents=price_cents,
    )


def reason(title: str, item: ItemFacts, **fields: object) -> DropReason | None:
    result = filter_comps([comp(title, **fields)], item)  # type: ignore[arg-type]
    return result.dropped[0].reason if result.dropped else None


# Every title below is real and comes from tests/fixtures/serpapi unless it says otherwise.
@pytest.mark.parametrize(
    ("title", "item", "expected"),
    [
        # Accessories and single parts.
        ("Earbuds For Apple AirPods Pro 2nd Generation", AIRPODS, DropReason.ACCESSORY),
        (
            "Apple AirPods Pro 2nd Gen A2699 Left - A Grade - OEM Authentic",
            AIRPODS,
            DropReason.ACCESSORY,
        ),
        (
            "Apple AirPods Pro 1st Gen - A2190 - OEM MagSafe Charging Case",
            AIRPODS,
            DropReason.ACCESSORY,
        ),
        (
            "Original Apple AirPods Pro 1st Generation - Charging Case A2190",
            AIRPODS,
            DropReason.ACCESSORY,
        ),
        (
            "Patagonia Men's Better Sweater Fleece Vest - Navy Size Large",
            APPAREL,
            DropReason.WRONG_ITEM,
        ),
        # Lots and bundles, the first of the two prototype misses.
        ("LOT OF 6 Ring Video Doorbell Pro (1st Gen) Wi-Fi Wired", AIRPODS, DropReason.LOT),
        ("Nintendo Switch Console Bundle with 4 digital games", SWITCH, DropReason.BUNDLE),
        (
            "Sony PlayStation 4 Slim PS4 1TB Black Console, Headset & 3 Games",
            PS4,
            DropReason.BUNDLE,
        ),
        ("Sony PlayStation 4 Slim 500GB Black Console w/ 2 DualShock 4", PS4, DropReason.BUNDLE),
        ("Nintendo Switch 32GB Handheld Console - Neon Red with Games", SWITCH, DropReason.BUNDLE),
        (
            "Sony PlayStation 4 Slim PS4 500GB Console Controller Game FREE SHIP",
            PS4,
            DropReason.BUNDLE,
        ),
        # Modded and repaired items, the second prototype miss.
        ("Sony PS4 Slim 2TB Upgraded Console", PS4, DropReason.MODDED),
        ("Nintendo Switch - Custom Clear Shell with Clear Joy-Cons", SWITCH, DropReason.MODDED),
        ("Nintendo Switch UNPATCHED V1 HAC-001 Console Only", SWITCH, DropReason.MODDED),
        ("Ring Video Doorbell 2nd Gen Used w/ New Battery Pack", AIRPODS, DropReason.MODDED),
        ("Vintage 90s Carhartt J01 Detroit Jacket Custom Dyed Green", APPAREL, DropReason.MODDED),
        ("iPod classic 80GB flash storage conversion, synthetic", AIRPODS, DropReason.MODDED),
        # Parts and damage.
        (
            "Sony PlayStation 4 Slim Console 1TB -Frame Damage - Fair Condition",
            PS4,
            DropReason.PARTS,
        ),
        (
            "Nintendo Switch Console Tablet Only Black Tested Working - No Joy-Cons",
            SWITCH,
            DropReason.PARTS,
        ),
        # Other models, and hardware in a game's search.
        (
            "Nintendo Switch Lite 32GB Handheld Console Turquoise Green",
            SWITCH,
            DropReason.WRONG_ITEM,
        ),
        ("Nintendo Switch 2 Console Black Launch Edition", SWITCH, DropReason.WRONG_ITEM),
        (
            "Nintendo Switch Console W/ Mario Kart 8 Deluxe Very Good 6Z",
            GAME,
            DropReason.WRONG_ITEM,
        ),
        ("Nintendo Switch With Mario Kart 8 Deluxe", GAME, DropReason.WRONG_ITEM),
    ],
)
def test_title_rules_drop(title: str, item: ItemFacts, expected: DropReason) -> None:
    assert reason(title, item) is expected


@pytest.mark.parametrize(
    ("title", "item"),
    [
        ("Nintendo Switch Animal Crossing Locker Find With Super Mario Case NO GAMES", SWITCH),
        ("Nintendo Switch HAC-001 - 32GB Handheld Game System with Joy-Cons", SWITCH),
        ("Sony PlayStation 4 Slim 500GB Gaming Console with Controller - Black", PS4),
        ("Apple AirPods Pro 2 with MagSafe Charging Case USB-C | MTJV3LL/A - Fair", AIRPODS),
        ("Apple AirPods Pro (2nd Gen) Earbuds & Case A2968 A3048 A3047 - Tested", AIRPODS),
        ("Mario Kart 8 Deluxe (Nintendo Switch, 2017) Game Only, tested", GAME),
        ("Mario Kart 8 Deluxe Nintendo Switch Game Cartridge Only Tested WORKS", GAME),
        ("MARIO KART 8 DELUXE FOR NINTENDO SWITCH CARTRIDGE ONLY (CMP131243)", GAME),
        ("Patagonia Better Sweater Fleece Jacket Men's M Black Full Zip Stand Collar", APPAREL),
    ],
)
def test_title_rules_keep(title: str, item: ItemFacts) -> None:
    assert reason(title, item) is None


@pytest.mark.parametrize(
    ("title", "product"),
    [
        ("Nintendo Switch Bundle With Mario Kart 8 Deluxe 64GB", "Nintendo Switch bundle"),
        ("Patagonia Better Sweater Men's M Gray Full Zip Fleece Vest", "Better Sweater vest"),
        ("Nintendo Switch Lite 32GB Handheld Console", "Nintendo Switch Lite console"),
    ],
)
def test_item_that_is_one_of_those_keeps_them(title: str, product: str) -> None:
    category = Category.APPAREL if "Patagonia" in title else Category.ELECTRONICS_GAMES
    assert reason(title, ItemFacts(category=category, product=product)) is None


def test_accessory_item_keeps_accessory_comps() -> None:
    item = ItemFacts(category=Category.ELECTRONICS_GAMES, product="AirPods Pro charging case")
    assert reason("Apple AirPods Pro 1st Gen - A2190 - OEM MagSafe Charging Case", item) is None


KIDS_TITLES = [
    "Vintage Carhartt J97 Detroit Jacket Youth XL/Mens Small",  # names both departments
    "Nike Air Max 90 Pink Barbie 833376-603 Laser Fuscia 4.5Y - 6 W",
    "Carhartt Boys 6 Bib Overalls Brown Canvas",  # synthetic, the prototype's lost kids' comps
]


@pytest.mark.parametrize("title", KIDS_TITLES)
def test_kids_words_never_drop_a_kids_item(title: str) -> None:
    item = ItemFacts(category=Category.APPAREL, product="jacket", department=Department.KIDS)
    assert reason(title, item) is None


def test_kids_words_drop_only_when_staff_said_not_kids() -> None:
    mens = ItemFacts(category=Category.APPAREL, product="jacket", department=Department.MENS)
    assert reason(KIDS_TITLES[1], mens) is DropReason.DEPARTMENT
    assert reason(KIDS_TITLES[2], mens) is DropReason.DEPARTMENT
    # This one is sold as an adult small as well, so it stays.
    assert reason(KIDS_TITLES[0], mens) is None
    # With no department from staff, the words decide nothing.
    unknown = ItemFacts(category=Category.APPAREL, product="jacket")
    assert reason(KIDS_TITLES[2], unknown) is None


def test_other_department_is_dropped_but_unisex_stays() -> None:
    mens = ItemFacts(category=Category.APPAREL, product="fleece", department=Department.MENS)
    women = "Patagonia Better Sweater Women's Small Purple Full-Zip Fleece Jacket w/ Pockets"
    assert reason(women, mens) is DropReason.DEPARTMENT
    assert reason("Nike Air Max 90 Women's Unisex Sneakers", mens) is None
    # Curly apostrophes are what most of these titles use.
    assert reason("Lululemon Women\u2019s Align High Rise Leggings", mens) is DropReason.DEPARTMENT


def test_size_type_comes_from_staff_and_plain_sizes_never_drop() -> None:
    tall_title = "Vintage Hunter Green Carhartt Detroit Jacket Size Large Tall"
    large = APPAREL.model_copy(update={"size": "L"})
    tall = APPAREL.model_copy(update={"size": "Large Tall"})
    assert reason(tall_title, large) is DropReason.SIZE_TYPE
    assert reason(tall_title, tall) is None
    assert reason(tall_title, APPAREL) is None
    assert reason("Carhartt Men's Detroit Jacket Size Small Blanket Lining", large) is None


def test_complete_in_box_comes_from_staff() -> None:
    boxed = GAME.model_copy(update={"complete_in_box": True})
    loose = GAME.model_copy(update={"complete_in_box": False})
    cartridge = "Mario Kart 8 Deluxe Nintendo Switch Game Cartridge Only Tested WORKS"
    cib = "Mario Kart 8 Deluxe Nintendo Switch Complete in Box CIB Tested & Working"

    assert reason(cartridge, boxed) is DropReason.BOX
    assert reason(cib, boxed) is None
    assert reason(cib, loose) is DropReason.BOX
    assert reason(cartridge, loose) is None
    assert reason(cib, GAME) is None
    assert reason(cartridge, GAME) is None


@pytest.mark.parametrize(
    ("label", "item", "expected"),
    [
        ("Pre-Owned", APPAREL, None),
        ("New (Other)", APPAREL, DropReason.CONDITION),
        ("Brand New", APPAREL, DropReason.CONDITION),
        # eBay labels a like-new game "New (Other)", see docs/serpapi-ebay-check.md.
        ("New (Other)", GAME, None),
        ("Brand New", GAME, DropReason.CONDITION),
        ("For parts or not working", GAME, DropReason.CONDITION),
        # Two real rows carry the product name here, which is not a grade.
        ("Sony PlayStation 4", PS4, None),
        (None, PS4, None),
        (
            "Pre-Owned",
            APPAREL.model_copy(update={"condition": Condition.NEW_WITH_TAGS}),
            DropReason.CONDITION,
        ),
        ("Brand New", APPAREL.model_copy(update={"condition": Condition.NEW_WITH_TAGS}), None),
        ("New (Other)", APPAREL.model_copy(update={"condition": Condition.NEW_WITHOUT_TAGS}), None),
    ],
)
def test_condition_filter(label: str | None, item: ItemFacts, expected: DropReason | None) -> None:
    assert reason("Plain title", item, condition=label) is expected


def test_listing_with_no_single_price_is_dropped() -> None:
    title = "Nintendo Switch Console Only Rank select"
    assert reason(title, SWITCH, price_cents=None) is DropReason.NO_SINGLE_PRICE


def test_repeated_listing_is_dropped_once() -> None:
    title = "Levi's 501 Original Fit Jeans"
    result = filter_comps([comp(title), comp(title)], APPAREL)
    assert len(result.kept) == 1
    assert [dropped.reason for dropped in result.dropped] == [DropReason.DUPLICATE]


@pytest.mark.parametrize("slug", ITEMS)
def test_every_fixture_comp_is_kept_or_dropped_with_a_reason(slug: str) -> None:
    comps = load_comps(slug)
    result = filter_comps(comps, ITEMS[slug])
    assert len(result.kept) + len(result.dropped) == len(comps)
    assert all(dropped.detail for dropped in result.dropped)


def test_game_search_with_the_wrong_condition_ids_loses_its_consoles() -> None:
    # 57 of these 60 are consoles, and two of them name no hardware, so they still get through.
    kept = filter_comps(load_comps("mario-kart-8-switch"), ITEMS["mario-kart-8-switch"]).kept
    assert len(kept) == 5


def test_game_search_with_the_right_condition_ids_keeps_the_game() -> None:
    slug = "mario-kart-8-switch-game-conditions"
    result = filter_comps(load_comps(slug), ITEMS[slug])
    assert len(result.kept) == 59
    assert [dropped.reason for dropped in result.dropped] == [DropReason.LOT]
