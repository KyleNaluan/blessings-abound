"""The rule-based claim checker for listing drafts.

It flags banned words, and any brand, size, number or condition claim that the item card does not
support. A phrase is supported when it appears in the card's own text, and a condition claim is
also supported by the matching staff entry, such as "tested" by tested and working. The checker is
deliberately strict, because a flagged draft falls back to the fixed template, which never makes a
claim, and staff can still edit either one. The rules are described in docs/architecture.md.
"""

import re
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from enum import StrEnum

from pydantic import BaseModel

from app.models import Category, Condition, Department, Flaw, ItemCard


class ClaimRule(StrEnum):
    BANNED_WORD = "banned_word"
    BRAND = "brand"
    SIZE = "size"
    NUMBER = "number"
    CONDITION = "condition"


class ClaimFlag(BaseModel):
    rule: ClaimRule
    phrase: str
    message: str


@dataclass(frozen=True)
class ListingFacts:
    """Everything known about the item, which is all a draft may say."""

    category: Category
    condition: Condition
    brand: str | None = None
    product: str | None = None
    exact_model: str | None = None
    platform: str | None = None
    color: str | None = None
    material: str | None = None
    visible_text: str | None = None
    department: Department | None = None
    size: str | None = None
    size_type: str | None = None
    flaws: tuple[Flaw, ...] = field(default_factory=tuple)
    tested_working: bool | None = None
    complete_in_box: bool | None = None
    accessories_included: str | None = None

    @classmethod
    def from_card(cls, card: ItemCard) -> "ListingFacts":
        return cls(
            category=card.category,
            condition=card.condition,
            brand=card.brand,
            product=card.product,
            exact_model=card.exact_model,
            platform=card.platform,
            color=card.color,
            material=card.material,
            visible_text=card.visible_text,
            department=card.department,
            size=card.size,
            size_type=card.size_type,
            flaws=tuple(Flaw(flaw) for flaw in card.flaws),
            tested_working=card.tested_working,
            complete_in_box=card.complete_in_box,
            accessories_included=card.accessories_included,
        )

    def card_text(self) -> str:
        """The card's own words, where any phrase that appears is supported."""
        parts = (
            self.brand,
            self.product,
            self.exact_model,
            self.platform,
            self.color,
            self.material,
            self.visible_text,
            self.size,
            self.size_type,
            self.accessories_included,
            *(flaw.value.replace("_", " ") for flaw in self.flaws),
        )
        return "\n".join(part for part in parts if part)


def normalize(text: str) -> str:
    """Lower case words with single spaces, no accents or punctuation, padded to match words.

    Apostrophes are dropped rather than spaced, so "Levi's" and "Levis" read the same and a lone
    "s" never appears.
    """
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    # A curly apostrophe is already gone with the other characters outside ASCII.
    plain = re.sub(r"['`]", "", plain)
    return f" {re.sub(r'[^a-z0-9]+', ' ', plain).strip()} "


def _norm(phrase: str) -> str:
    return normalize(phrase).strip()


# Words a listing never uses unless the card itself says them: rarity, authenticity, age, value,
# the item's history and shipping, none of which anyone at intake can vouch for.
BANNED_WORDS = (
    "rare",
    "rarest",
    "authentic",
    "authenticity",
    "authenticated",
    "genuine",
    "antique",
    "vintage",
    "collectible",
    "collectable",
    "collector",
    "collectors",
    "limited edition",
    "exclusive",
    "one of a kind",
    "hard to find",
    "htf",
    "sought after",
    "highly sought",
    "grail",
    "investment",
    "valuable",
    "value",
    "worth",
    "priceless",
    "msrp",
    "retail",
    "retails",
    "official",
    "officially",
    "licensed",
    "oem",
    "guaranteed",
    "guarantee",
    "warranty",
    "certified",
    "smoke free",
    "pet free",
    "shipping",
    "ships",
)

# Each group names one brand or product line, and any of its names on the card supports the rest.
# A name that starts with "=" is matched with its case as written, because in lower case it is an
# everyday word, such as Coach or Switch.
BRAND_GROUPS: tuple[tuple[str, ...], ...] = (
    # Games and hardware makers.
    ("nintendo",),
    ("sony",),
    ("microsoft",),
    ("sega",),
    ("atari",),
    ("snk", "neo geo", "neogeo"),
    ("turbografx", "pc engine"),
    ("coleco", "colecovision"),
    ("mattel", "intellivision"),
    ("activision",),
    ("electronic arts", "=EA"),
    ("ubisoft",),
    ("capcom",),
    ("konami",),
    ("square enix", "squaresoft"),
    ("bandai",),
    ("namco",),
    ("rockstar",),
    ("bethesda",),
    ("mad catz", "madcatz"),
    ("powera",),
    ("turtle beach",),
    ("logitech",),
    ("razer",),
    ("=Hori",),
    ("8bitdo",),
    ("nyko",),
    ("hyperkin",),
    ("redoctane", "red octane"),
    ("pokemon",),
    # Product lines, which also say which system an item is for.
    ("playstation", "=PS1", "=PSX", "=PSone"),
    ("playstation 2", "=PS2"),
    ("playstation 3", "=PS3"),
    ("playstation 4", "=PS4"),
    ("playstation 5", "=PS5"),
    ("psp", "playstation portable"),
    ("vita", "ps vita", "playstation vita"),
    ("xbox",),
    ("xbox 360",),
    ("xbox one",),
    ("xbox series",),
    ("kinect",),
    ("wii",),
    ("wii u",),
    ("gamecube", "game cube"),
    ("game boy", "gameboy"),
    ("game boy color", "gameboy color", "=GBC"),
    ("game boy advance", "gameboy advance", "=GBA"),
    ("nintendo ds", "=DS"),
    ("3ds",),
    ("2ds",),
    ("nintendo switch", "=Switch"),
    ("joy con", "joycon"),
    ("nintendo 64", "=N64"),
    ("=NES", "nintendo entertainment system"),
    ("=SNES", "super nintendo", "super nes", "super famicom"),
    ("famicom",),
    ("=Genesis", "mega drive", "megadrive"),
    ("dreamcast",),
    ("=Saturn", "sega saturn"),
    ("game gear",),
    ("master system",),
    ("virtual boy",),
    ("=Jaguar", "atari jaguar"),
    # Apparel and shoe brands.
    ("nike",),
    ("=Jordan", "air jordan", "jumpman"),
    ("adidas",),
    ("levis", "levi strauss", "=Levi"),
    ("carhartt",),
    ("patagonia",),
    ("north face",),
    ("=Columbia", "columbia sportswear"),
    ("under armour",),
    ("=Puma",),
    ("reebok",),
    ("new balance",),
    ("=Converse",),
    ("=Vans",),
    ("ralph lauren", "=Polo"),
    ("tommy hilfiger",),
    ("calvin klein",),
    ("=Gap",),
    ("old navy",),
    ("american eagle",),
    ("abercrombie",),
    ("hollister",),
    ("j crew", "jcrew"),
    ("lululemon",),
    ("=Champion",),
    ("wrangler",),
    ("=Lee",),
    ("dickies",),
    ("gucci",),
    ("prada",),
    ("louis vuitton",),
    ("chanel",),
    ("=Coach",),
    ("michael kors",),
    ("kate spade",),
    ("=Supreme",),
    ("timberland",),
    ("dr martens", "doc martens"),
    ("ugg", "uggs"),
    ("zara",),
    ("=H&M",),
    ("uniqlo",),
    ("=Guess",),
    ("banana republic",),
    ("=Express",),
    ("forever 21",),
    ("burberry",),
    ("versace",),
    ("armani",),
    ("hugo boss",),
    ("pendleton",),
    ("filson",),
    ("ll bean", "llbean"),
    ("eddie bauer",),
    ("fila",),
    ("asics",),
    ("saucony",),
    ("hanes",),
    ("stussy",),
    ("bape", "a bathing ape"),
    ("off white",),
    ("yeezy",),
    ("birkenstock",),
    ("crocs",),
    ("skechers",),
    ("oakley",),
    ("ray ban",),
    ("true religion",),
    ("madewell",),
    ("free people",),
    ("athleta",),
)

# Letter sizes, matched in capitals only, so "s" and "m" as words never count.
LETTER_SIZES = (
    "XXS",
    "XS",
    "S",
    "M",
    "L",
    "XL",
    "XXL",
    "XXXL",
    "2XL",
    "3XL",
    "4XL",
    "5XL",
    "1X",
    "2X",
    "3X",
)
# Cuts, fits and builds, which are size claims too.
FIT_WORDS = (
    "petite",
    "tall",
    "plus size",
    "big and tall",
    "maternity",
    "husky",
    "slim",
    "slim fit",
    "skinny",
    "regular fit",
    "relaxed fit",
    "oversized",
    "one size",
)
SIZE_WORDS = ("small", "medium", "large", "x large", "extra large", "xx large", "x small")
DEPARTMENT_WORDS: dict[Department | None, tuple[str, ...]] = {
    Department.MENS: ("mens", "men", "male", "guys"),
    Department.WOMENS: ("womens", "women", "ladies", "female"),
    Department.KIDS: (
        "kids",
        "kid",
        "children",
        "childrens",
        "boys",
        "girls",
        "youth",
        "toddler",
        "baby",
        "juniors",
    ),
    None: ("unisex",),
}

NUMBER_WORDS = {
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10",
    "eleven": "11",
    "twelve": "12",
    "twenty": "20",
    "dozen": "12",
    "hundred": "100",
    "thousand": "1000",
}

NEGATIONS = frozenset(
    {"no", "not", "without", "never", "isnt", "doesnt", "dont", "wasnt", "hasnt", "havent", "nor"}
)
# How many words before a claim a negation still turns it around, as in "has not been tested". It
# never reaches back past punctuation, so "No box, but tested" is still a claim that it was tested.
NEGATION_WINDOW = 3


@dataclass(frozen=True)
class _ConditionClaims:
    phrases: tuple[str, ...]
    supported: Callable[[ListingFacts], bool]
    # Whether "not" or "no" just before the phrase turns it into a statement the card allows.
    negatable: bool = True


def _is_new(facts: ListingFacts) -> bool:
    return facts.condition in (Condition.NEW_WITH_TAGS, Condition.NEW_WITHOUT_TAGS)


def _has_flaw(flaw: Flaw) -> Callable[[ListingFacts], bool]:
    return lambda facts: flaw in facts.flaws


def _never(facts: ListingFacts) -> bool:
    return False


CONDITION_CLAIMS = (
    _ConditionClaims(
        ("new", "brand new", "unused", "unworn", "never used", "never worn", "nib", "bnib"),
        _is_new,
    ),
    _ConditionClaims(
        ("with tags", "nwt", "bnwt", "tags attached", "new with tags", "original tags"),
        lambda facts: facts.condition is Condition.NEW_WITH_TAGS,
    ),
    _ConditionClaims(
        ("without tags", "nwot", "new without tags", "no tags"),
        lambda facts: facts.condition is Condition.NEW_WITHOUT_TAGS,
        negatable=False,
    ),
    _ConditionClaims(
        ("used", "pre owned", "preowned", "secondhand", "second hand", "previously owned", "worn"),
        lambda facts: facts.condition is Condition.PRE_OWNED,
    ),
    _ConditionClaims(
        ("sealed", "factory sealed", "never opened", "unopened", "shrink wrapped"), _never
    ),
    # Grades and promises the card has no field for, so only the card's own text supports them.
    _ConditionClaims(
        (
            "mint",
            "near mint",
            "like new",
            "as new",
            "excellent",
            "great condition",
            "good condition",
            "fair condition",
            "very good",
            "pristine",
            "flawless",
            "perfect",
            "perfectly",
            "immaculate",
            "spotless",
            "gently used",
            "lightly used",
            "barely used",
            "hardly used",
            "gently worn",
            "lightly worn",
            "barely worn",
            "minimal wear",
            "light wear",
            "no wear",
            "no flaws",
            "no stains",
            "no tears",
            "no holes",
            "no rips",
            "no scratches",
            "no scuffs",
            "no damage",
            "no issues",
            "no defects",
            "no cracks",
            "well kept",
            "well maintained",
            "well cared for",
            "clean",
            "cleaned",
            "sanitized",
            "washed",
            "refurbished",
            "restored",
            "for parts",
            "as is",
            "not working",
            "broken",
            "damaged",
            "crack",
            "cracked",
            "cracks",
        ),
        _never,
        negatable=False,
    ),
    _ConditionClaims(
        (
            "tested",
            "working",
            "works",
            "fully functional",
            "functional",
            "functions",
            "functioning",
            "powers on",
            "turns on",
            "plays",
            "operational",
        ),
        lambda facts: facts.tested_working is True,
    ),
    _ConditionClaims(
        (
            "complete in box",
            "cib",
            "in box",
            "in the box",
            "in its box",
            "with box",
            "with the box",
            "original box",
            "boxed",
            "box included",
            "original packaging",
            "with packaging",
            "with manual",
            "with the manual",
            "manual included",
            "complete",
        ),
        lambda facts: facts.complete_in_box is True,
    ),
    _ConditionClaims(
        (
            "includes",
            "included",
            "including",
            "comes with",
            "come with",
            "bundle",
            "bundled",
            "with cables",
            "with cable",
            "with charger",
            "with power supply",
            "with controller",
            "with controllers",
            "with games",
            "with game",
            "with accessories",
            "lot of",
            "set of",
        ),
        lambda facts: facts.complete_in_box is True or bool(facts.accessories_included),
    ),
    _ConditionClaims(
        ("stain", "stains", "stained", "discolored", "discoloration", "yellowing", "yellowed"),
        _has_flaw(Flaw.STAINS),
    ),
    _ConditionClaims(
        ("tear", "tears", "torn", "rip", "rips", "ripped", "hole", "holes"),
        _has_flaw(Flaw.TEARS),
    ),
    _ConditionClaims(
        ("scuff", "scuffs", "scuffed", "scratch", "scratches", "scratched", "wear", "marks"),
        _has_flaw(Flaw.SCUFFS),
    ),
    _ConditionClaims(("missing", "missing parts", "incomplete"), _has_flaw(Flaw.MISSING_PARTS)),
)


def _occurrences(text: str, phrase: str) -> Iterable[int]:
    """The word index of each place the phrase starts in normalized text."""
    target = _norm(phrase)
    if not target:
        return
    words = text.split()
    size = len(target.split())
    for index in range(len(words) - size + 1):
        if " ".join(words[index : index + size]) == target:
            yield index


def _exact(text: str, name: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9])", text) is not None


def _in_text(raw: str, normalized: str, name: str) -> bool:
    if name.startswith("="):
        return _exact(raw, name[1:])
    return any(True for _ in _occurrences(normalized, name))


def _on_card(card: str, name: str) -> bool:
    """A name or phrase on the card, in any case, as whole words."""
    target = _norm(name.removeprefix("="))
    return bool(target) and f" {target} " in card


def _negated(words: list[str], index: int) -> bool:
    return any(word in NEGATIONS for word in words[max(0, index - NEGATION_WINDOW) : index])


def _numbers(text: str) -> set[str]:
    return {match.replace(",", "") for match in re.findall(r"\d+(?:[.,]\d+)*", text)}


@dataclass
class _Findings:
    flags: list[ClaimFlag] = field(default_factory=list)
    seen: set[tuple[ClaimRule, str]] = field(default_factory=set)

    def add(self, rule: ClaimRule, phrase: str, message: str) -> None:
        key = (rule, phrase.lower())
        if key not in self.seen:
            self.seen.add(key)
            self.flags.append(ClaimFlag(rule=rule, phrase=phrase, message=message))


def _check_banned(normalized: str, card: str, found: _Findings) -> None:
    for word in BANNED_WORDS:
        if any(True for _ in _occurrences(normalized, word)) and not _on_card(card, word):
            found.add(ClaimRule.BANNED_WORD, word, f'"{word}" is a word listings never use.')


def _check_brands(raw: str, normalized: str, card: str, found: _Findings) -> None:
    for group in BRAND_GROUPS:
        named = next((name for name in group if _in_text(raw, normalized, name)), None)
        if named is not None and not any(_on_card(card, name) for name in group):
            phrase = named.removeprefix("=")
            found.add(ClaimRule.BRAND, phrase, f'"{phrase}" is a brand or system the card lacks.')


def _check_sizes(raw: str, normalized: str, facts: ListingFacts, found: _Findings) -> None:
    card = normalize(facts.card_text())

    def flag(phrase: str) -> None:
        found.add(ClaimRule.SIZE, phrase, f'"{phrase}" is a size or fit the card lacks.')

    for size in LETTER_SIZES:
        if _exact(raw, size) and not _on_card(card, size):
            flag(size)
    for word in FIT_WORDS:
        if any(True for _ in _occurrences(normalized, word)) and not _on_card(card, word):
            flag(word)
    # A size given after the word "size", such as "size 10" or "Size: Large".
    for match in re.finditer(r"\bsize\s*:?\s*([a-z0-9][a-z0-9./-]*)", raw, flags=re.IGNORECASE):
        token = match.group(1)
        sized = any(char.isdigit() for char in token) or _norm(token) in SIZE_WORDS
        if (sized or token.upper() in LETTER_SIZES) and not _on_card(card, token):
            flag(f"size {token}")
    for department, words in DEPARTMENT_WORDS.items():
        if department is not None and department is facts.department:
            continue
        for word in words:
            if any(True for _ in _occurrences(normalized, word)) and not _on_card(card, word):
                flag(word)


def _check_numbers(raw: str, normalized: str, card_raw: str, found: _Findings) -> None:
    card_numbers = _numbers(card_raw)
    card = normalize(card_raw)
    for number in sorted(_numbers(raw)):
        if number not in card_numbers:
            found.add(ClaimRule.NUMBER, number, f'"{number}" is a number the card lacks.')
    for word, digits in NUMBER_WORDS.items():
        if f" {word} " in normalized and digits not in card_numbers and not _on_card(card, word):
            found.add(ClaimRule.NUMBER, word, f'"{word}" is a number the card lacks.')


def _check_condition(raw: str, facts: ListingFacts, card: str, found: _Findings) -> None:
    clauses = [normalize(clause) for clause in re.split(r"[.,;:!?()\n]+", raw)]
    for claims in CONDITION_CLAIMS:
        if claims.supported(facts):
            continue
        for phrase in claims.phrases:
            if _on_card(card, phrase):
                continue
            if any(_claimed(clause, phrase, claims.negatable) for clause in clauses):
                found.add(
                    ClaimRule.CONDITION,
                    phrase,
                    f'"{phrase}" says something about the condition the card doesn\'t.',
                )


def _claimed(clause: str, phrase: str, negatable: bool) -> bool:
    words = clause.split()
    return any(not (negatable and _negated(words, index)) for index in _occurrences(clause, phrase))


def _drop_card_quotes(text: str, card: str) -> str:
    """The text without any quoted words copied from the card, which repeat it and claim nothing.

    Each quote becomes a clause break, so a word before it can't join a word inside it.
    """
    return re.sub(
        r"[\"\u201c\u201d]([^\"\u201c\u201d\n]+)[\"\u201c\u201d]",
        lambda match: ". " if _on_card(card, match.group(1)) else match.group(0),
        text,
    )


def check_text(text: str, facts: ListingFacts) -> list[ClaimFlag]:
    """Every claim in one piece of text that the card doesn't support."""
    found = _Findings()
    card_raw = facts.card_text()
    card = normalize(card_raw)
    text = _drop_card_quotes(text, card)
    normalized = normalize(text)
    _check_banned(normalized, card, found)
    _check_brands(text, normalized, card, found)
    _check_sizes(text, normalized, facts, found)
    _check_numbers(text, normalized, card_raw, found)
    _check_condition(text, facts, card, found)
    return found.flags


def check_listing(title: str, description: str, facts: ListingFacts) -> list[ClaimFlag]:
    """The flags for a title and description, checked apart so a negation can't reach across."""
    flags = check_text(title, facts)
    seen = {(flag.rule, flag.phrase.lower()) for flag in flags}
    for flag in check_text(description, facts):
        if (flag.rule, flag.phrase.lower()) not in seen:
            flags.append(flag)
    return flags
