"""Keep only the comps that are the same kind of item, and record why each other one was dropped.

Department, size and complete in box are judged against what staff entered, so a word like "boys"
only drops a comp when staff said the item is not a kids' item. The word lists come from the titles
in tests/fixtures/serpapi and they will miss some listings, so the outlier trim stays as a backstop.
"""

import re
from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from app.comps import Comp
from app.models import Category, Condition, Department


class DropReason(StrEnum):
    DUPLICATE = "duplicate"
    CONDITION = "condition"
    PARTS = "parts"
    MODDED = "modded"
    LOT = "lot"
    BUNDLE = "bundle"
    ACCESSORY = "accessory"
    WRONG_ITEM = "wrong_item"
    DEPARTMENT = "department"
    SIZE_TYPE = "size_type"
    BOX = "box"


class ItemFacts(BaseModel):
    """The item card and staff entries the filter compares each comp with."""

    model_config = ConfigDict(frozen=True)

    category: Category
    product: str | None = None
    platform: str | None = None
    condition: Condition = Condition.PRE_OWNED
    department: Department | None = None
    size: str | None = None
    complete_in_box: bool | None = None


class DroppedComp(BaseModel):
    comp: Comp
    reason: DropReason
    detail: str


class FilteredComps(BaseModel):
    kept: list[Comp]
    dropped: list[DroppedComp]


@dataclass(frozen=True)
class _TitleRule:
    reason: DropReason
    pattern: re.Pattern[str]
    # None means the rule applies to every category.
    category: Category | None = None


def _words(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


_GAMES = Category.ELECTRONICS_GAMES
_APPAREL = Category.APPAREL

_ACCESSORY_NOUNS = (
    r"case|cover|charger|cable|cord|skin|dock|adapter|stand|strap|grip|shell|earbuds?|ear ?tips?"
    r"|controller|faceplate|mount|bracket|sticker|decal"
)

_TITLE_RULES = (
    _TitleRule(
        DropReason.PARTS,
        _words(
            r"\bfor parts\b|\bparts (?:only|or|and|&)\b|\brepair only\b|\bnot working\b"
            r"|\bbroken\b|\bdefective\b|\bfaulty\b|\bas[- ]is\b|\bdamaged?\b|\bnot tested\b"
            r"|\buntested\b"
        ),
    ),
    _TitleRule(
        DropReason.PARTS,
        _words(r"\btablet only\b|\bno joy[- ]?cons?\b"),
        _GAMES,
    ),
    _TitleRule(
        DropReason.MODDED,
        _words(
            r"\bmod(?:ded)?\b|\bmodified\b|\brefurb(?:ished)?\b|\bjailbroken\b|\bhacked\b"
            r"|\bchipped\b|\bunpatched\b|\bupgraded\b|\bflash storage\b|\bnew batter(?:y|ies)\b"
        ),
        _GAMES,
    ),
    _TitleRule(DropReason.MODDED, _words(r"\bcustom\b")),
    _TitleRule(
        DropReason.MODDED,
        _words(r"\bhand ?painted\b|\bone of one\b|\breworked\b|\baltered\b"),
        _APPAREL,
    ),
    _TitleRule(
        DropReason.LOT,
        _words(r"\blots?\b|\bset of\b|\b\d+ pairs\b|\bwholesale\b|\bvolume discounts?\b"),
    ),
    _TitleRule(DropReason.BUNDLE, _words(r"\bbundles?\b|\bcombo\b")),
    _TitleRule(
        DropReason.BUNDLE,
        _words(
            r"\b(?:2|3|4|two|three|four|extra|additional)\s+(?:\S+\s+){0,2}?"
            r"(?:controllers?|contrs?|joy[- ]?cons?|dualshock)\b|\bheadset\b"
        ),
        _GAMES,
    ),
    _TitleRule(
        DropReason.ACCESSORY,
        _words(rf"\b(?:{_ACCESSORY_NOUNS})s?\s+(?:for|compatible with|fits)\b"),
        _GAMES,
    ),
    _TitleRule(
        DropReason.ACCESSORY,
        _words(
            rf"\b(?:{_ACCESSORY_NOUNS}|box|manual|remote)s?\s+only\b|\bempty box\b|\breplacement\b"
            r"|\b(?:left|right)\s+(?:side|only|earbud|airpod|joy[- ]?con)\b"
            r"|\b(?:left|right)\s*-\s*[a-c] grade\b"
            r"|\boem\b.*\bcharging case\b|\bcharging case a\d{4}\b"
        ),
        _GAMES,
    ),
    _TitleRule(
        DropReason.ACCESSORY,
        _words(r"\bbox only\b|\bempty box\b|\blaces only\b|\binsoles\b"),
        _APPAREL,
    ),
    _TitleRule(
        DropReason.WRONG_ITEM,
        _words(
            r"\bvests?\b|\bshorts\b|\bskirts?\b|\bhats?\b|\bbeanies?\b|\bgloves\b|\bsocks\b"
            r"|\bscar(?:f|ves)\b|\bwallets?\b|\bbackpacks?\b|\bpurses?\b|\btote\b"
        ),
        _APPAREL,
    ),
    _TitleRule(DropReason.WRONG_ITEM, _words(r"\blite\b|\boled\b|\bmini\b|\bswitch 2\b"), _GAMES),
)

# Nouns that mean the item itself is one of the things a rule would drop.
_ITEM_IS = {
    DropReason.PARTS: _words(r"\bparts?\b|\bbroken\b"),
    DropReason.MODDED: _words(r"\bmod(?:ded)?\b|\brefurb(?:ished)?\b"),
    DropReason.LOT: _words(r"\blots?\b|\bbundles?\b"),
    DropReason.BUNDLE: _words(r"\bbundles?\b|\blots?\b"),
    DropReason.ACCESSORY: _words(
        rf"\b(?:{_ACCESSORY_NOUNS}|joy[- ]?cons?|manual|remote|replacement)s?\b"
    ),
}

# Hardware words in a card's product, which tell a console apart from a game for that platform.
_HARDWARE_PRODUCT = _words(
    r"\bconsole\b|\bsystem\b|\bhandheld\b|\blite\b|\boled\b|\bslim\b|\bcontroller\b|\bjoy[- ]?con\b"
    r"|\bheadset\b|\bdock\b"
)
# Hardware in the title of a listing for a game, which is how consoles get in with the game.
_HARDWARE_TITLE = _words(
    r"\bconsole\b|\bsystem\b|\bhandheld\b|\blite\b|\boled\b|\bjoy[- ]?cons?\b|\bdock\b"
    r"|\b(?:hac|hdh|heg)-\d+"
)
# Games in the title of a listing for hardware. "No games" stays, and so does "game system".
_GAMES_INCLUDED = _words(r"(?<!\bno )\bgames?\b(?!\s*(?:system|console|boy|cube|gear)\b)")

# Labels eBay shows in the condition field. Anything else, such as a product name, is not a grade.
_LABEL_NEW = {"brand new", "new"}
_LABEL_NEW_TAGS = {"new with tags", "new with box"}
_LABEL_NEW_OTHER = {"new (other)", "new other", "new without tags", "new without box", "open box"}
_LABEL_USED = {"pre-owned", "used", "very good", "good", "acceptable", "like new"}
_LABEL_NEVER = {"for parts or not working", "certified refurbished", "seller refurbished"}
_KNOWN_LABELS = _LABEL_NEW | _LABEL_NEW_TAGS | _LABEL_NEW_OTHER | _LABEL_USED | _LABEL_NEVER

_DEPARTMENT_WORDS = {
    Department.KIDS: _words(
        r"\bkids?\b|\bkid's\b|\bboys?\b|\bboy's\b|\bgirls?\b|\bgirl's\b|\byouth\b|\btoddlers?\b"
        r"|\binfants?\b|\bbaby\b(?! (?:blue|pink))|\bjuniors?\b|\b\d+(?:\.5)?[yt]\b"
    ),
    Department.MENS: _words(r"\bmen(?:'?s)?\b"),
    Department.WOMENS: _words(r"\bwomen(?:'?s)?\b|\bladies\b|\bwmns\b"),
}
_UNISEX = _words(r"\bunisex\b")

_SIZE_TYPES = (
    _words(r"\btall\b|\b\d?x*lt\b"),
    _words(r"\bplus size\b"),
    _words(r"\bpetite\b"),
)

_LOOSE = _words(
    r"\b(?:cartridge|cart|game|disc|disk|console|system|tablet|device)\s+only\b|\bloose\b"
    r"|\b(?:no|without)\s+(?:case|box)\b"
)
_BOXED = _words(
    r"\bcib\b|\bcomplete in (?:the )?box\b|\bin box\b|\bsealed\b|\b(?:with|w/)\s*(?:the )?box\b"
    r"|\boriginal (?:case|box)\b|\bcase[ ,&]+(?:manual|cartridge)\b"
)


def filter_comps(comps: list[Comp], item: ItemFacts) -> FilteredComps:
    """Split comps into the ones to price and the ones dropped, each with a reason."""
    kept: list[Comp] = []
    dropped: list[DroppedComp] = []
    seen: set[str] = set()
    for comp in comps:
        drop = (
            (DropReason.DUPLICATE, f"same item id {comp.item_id}")
            if comp.item_id in seen
            else _drop_reason(comp, item)
        )
        seen.add(comp.item_id)
        if drop is None:
            kept.append(comp)
        else:
            dropped.append(DroppedComp(comp=comp, reason=drop[0], detail=drop[1]))
    return FilteredComps(kept=kept, dropped=dropped)


def _drop_reason(comp: Comp, item: ItemFacts) -> tuple[DropReason, str] | None:
    title = _normalize(comp.title)
    return (
        _check_title_rules(title, item)
        or _check_item_kind(title, item)
        or _check_department(title, item)
        or _check_size_type(title, item)
        or _check_box(title, item)
        or _check_condition(comp, item)
    )


def _normalize(text: str) -> str:
    """Curly apostrophes and non-breaking hyphens are common in titles and miss the rules."""
    return text.replace("\u2019", "'").replace("\u2011", "-")


def _check_title_rules(title: str, item: ItemFacts) -> tuple[DropReason, str] | None:
    product = _normalize(item.product or "")
    item_is = {reason for reason, pattern in _ITEM_IS.items() if pattern.search(product)}
    for rule in _TITLE_RULES:
        if rule.category not in (None, item.category) or rule.reason in item_is:
            continue
        match = rule.pattern.search(title)
        if match and match.group(0).lower() not in product.lower():
            return rule.reason, f'title says "{match.group(0)}"'
    return None


def _is_hardware(item: ItemFacts) -> bool:
    """A product that names hardware, or is only its platform's name, is the hardware."""
    product = (item.product or "").lower()
    if _HARDWARE_PRODUCT.search(product):
        return True
    return bool(item.platform) and product.replace((item.platform or "").lower(), "").strip() == ""


def _check_item_kind(title: str, item: ItemFacts) -> tuple[DropReason, str] | None:
    """Keep games out of a console's comps, and consoles out of a game's comps."""
    if item.category is not _GAMES:
        return None
    if _is_hardware(item):
        match = _GAMES_INCLUDED.search(title)
        return (DropReason.BUNDLE, f'title says "{match.group(0)}"') if match else None
    if not item.platform:
        return None

    # A title that opens with the platform and goes on to the game is the console with the game.
    console_with_game = rf"^\W*{re.escape(item.platform)}\s*(?:with\b|w/|,)"
    match = _HARDWARE_TITLE.search(title) or _words(console_with_game).search(title)
    if match:
        return DropReason.WRONG_ITEM, f'title says "{match.group(0)}" for a game'
    return None


def _check_department(title: str, item: ItemFacts) -> tuple[DropReason, str] | None:
    if item.category is not _APPAREL or item.department is None:
        return None
    if _DEPARTMENT_WORDS[item.department].search(title) or _UNISEX.search(title):
        return None
    for department, pattern in _DEPARTMENT_WORDS.items():
        match = pattern.search(title)
        if match:
            return (
                DropReason.DEPARTMENT,
                f'title says "{match.group(0)}", staff said {item.department.value}, '
                f"not {department.value}",
            )
    return None


def _check_size_type(title: str, item: ItemFacts) -> tuple[DropReason, str] | None:
    """Tall, plus and petite cut price differently, while a plain size never drops a comp."""
    if item.category is not _APPAREL or item.size is None:
        return None
    for pattern in _SIZE_TYPES:
        match = pattern.search(title)
        if match and not pattern.search(item.size):
            return DropReason.SIZE_TYPE, f'title says "{match.group(0)}", staff said {item.size}'
    return None


def _check_box(title: str, item: ItemFacts) -> tuple[DropReason, str] | None:
    if item.category is not _GAMES or item.complete_in_box is None:
        return None
    pattern = _LOOSE if item.complete_in_box else _BOXED
    match = pattern.search(title)
    if match is None:
        return None
    entered = "complete in box" if item.complete_in_box else "not complete in box"
    return DropReason.BOX, f'title says "{match.group(0)}", staff said {entered}'


def _accepted_labels(item: ItemFacts) -> set[str]:
    if item.condition is Condition.NEW_WITH_TAGS:
        return _LABEL_NEW | _LABEL_NEW_TAGS
    if item.condition is Condition.NEW_WITHOUT_TAGS:
        return _LABEL_NEW_OTHER
    # eBay labels a game the search asked for as like new "New (Other)", so it is still used here.
    return _LABEL_USED | _LABEL_NEW_OTHER if item.category is _GAMES else _LABEL_USED


def _check_condition(comp: Comp, item: ItemFacts) -> tuple[DropReason, str] | None:
    label = (comp.condition or "").strip().lower()
    if label in _KNOWN_LABELS and label not in _accepted_labels(item):
        return DropReason.CONDITION, f'listed as "{comp.condition}"'
    return None
