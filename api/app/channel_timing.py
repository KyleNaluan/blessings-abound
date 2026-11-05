"""Which channels can take an item, and whether to list it now or hold it for its season.

Code decides both. The channel rules are each channel's categories in `CHANNEL_CATEGORIES` and
the fields it needs in `CHANNEL_REQUIRED`, both in app/listing_drafts.py, and the timing comes from
the seasonal calendar on the Settings page, read on every call. The model only words the one-line
reason from the facts in `PROMPT`. A reply that names a number or a month the facts lack, a failed
call, or one slower than `REASON_SECONDS`, falls back to the fixed sentence in `template_reason`,
so the recommendation always shows. The rules are described in docs/architecture.md.
"""

import hashlib
import logging
import re
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

from app.ai import ChatModel, Message, ModelReplyError, complete_json, strip_reply
from app.claims import ListingFacts, _numbers  # pyright: ignore[reportPrivateUsage]
from app.listing_drafts import CATEGORY_LABELS, CHANNEL_NAMES, CHANNEL_REQUIRED, channel_takes
from app.models import Channel, DraftSource, FallbackReason
from app.store_settings import MONTHS, Season, SeasonalCalendar

logger = logging.getLogger(__name__)

REASON_MAX = 200
# How long the screen waits for the model's reason before it shows the fixed one instead.
REASON_SECONDS = 8.0

CHANNEL_KINDS = {
    Channel.CHANNEL_A: "an eBay-style marketplace",
    Channel.CHANNEL_B: "a Depop or Poshmark-style resale app for clothing",
}

PROMPT = """\
You write the reason for a recommendation of where and when a nonprofit thrift store lists one \
secondhand item, for the store staff who choose.
Code has already decided the channels and the timing, in "Recommendation" below. Say the same \
thing in your own plain words, and change neither.

Facts:
{facts}

Rules:
- Write one sentence of at most {reason_max} characters.
- Use only the facts, and name no month, year, number or channel that isn't in them.
- Don't mention price, value, fees, shipping or the store.
- Use no hashtags, emoji or exclamation marks.

Reply with one JSON object and nothing else, with exactly this key:
- "reason": the sentence
"""

PROMPT_SHA256 = hashlib.sha256(PROMPT.encode()).hexdigest()

_MONTH_WORDS = re.compile(r"\b(?:" + "|".join(MONTHS) + r")\b", re.IGNORECASE)

# The model call runs here, so the screen can stop waiting for it without stopping the request.
_reasons = ThreadPoolExecutor(max_workers=4, thread_name_prefix="channel-reason")


def get_today() -> date:
    """Today in UTC, the same day the approval step holds a release month against."""
    return datetime.now(UTC).date()


class ChannelOption(BaseModel):
    channel: Channel
    takes: bool
    # Why the channel can't take the item, when it can't.
    why_not: str | None


class TimingHint(BaseModel):
    # The first season in the calendar the item matches, or none when it matches none.
    season: str | None
    # The months as words, such as "August to January".
    season_span: str | None
    # The first day of the month the item is held until, or none to list it now.
    release_month: date | None


class ChannelAdvice(BaseModel):
    """What code decides, before the reason is worded."""

    channels: list[ChannelOption]
    timing: TimingHint

    def takes(self) -> list[Channel]:
        return [option.channel for option in self.channels if option.takes]


class ChannelRecommendation(ChannelAdvice):
    # One sentence on why, from the model or the fixed sentence.
    reason: str
    reason_source: DraftSource
    reason_fallback: FallbackReason | None


def _missing_field(channel: Channel, facts: ListingFacts) -> str | None:
    """The first field the channel needs that the card leaves empty."""
    return next(
        (name for name in CHANNEL_REQUIRED.get(channel, ()) if not getattr(facts, name)), None
    )


def channel_options(facts: ListingFacts) -> list[ChannelOption]:
    """Each channel, and whether its categories and required fields let it take the item."""
    options = []
    for channel in Channel:
        name = CHANNEL_NAMES[channel]
        missing = _missing_field(channel, facts)
        why_not = None
        if not channel_takes(channel, facts.category):
            why_not = f"{name} doesn't take {CATEGORY_LABELS[facts.category].lower()}."
        elif missing:
            why_not = f"{name} needs a {missing}, and the item card has none."
        options.append(ChannelOption(channel=channel, takes=why_not is None, why_not=why_not))
    return options


def _card_text(facts: ListingFacts) -> str:
    parts = (facts.brand, facts.product, facts.exact_model, facts.material, facts.visible_text)
    return " ".join(part for part in parts if part)


def _word_pattern(word: str) -> re.Pattern[str]:
    """A whole word or phrase, plural too, so boot matches Boots and flip flop flip-flops."""
    parts = [re.escape(part) for part in word.split()]
    return re.compile(r"(?<![a-z0-9])" + r"[\s-]+".join(parts) + r"(?:e?s)?(?![a-z0-9])", re.I)


def matching_season(facts: ListingFacts, calendar: SeasonalCalendar) -> Season | None:
    """The first season of the item's category with a word on its card, or none."""
    text = _card_text(facts)
    for season in calendar.seasons:
        if season.category is not facts.category:
            continue
        if any(_word_pattern(word).search(text) for word in season.match_words):
            return season
    return None


def release_month(months: Sequence[int], today: date) -> date | None:
    """None when today's month is in the season, and the first day of its next month if not.

    A season can run across the year end, such as August to January, so the next month may be in
    the next year.
    """
    if today.month in months:
        return None
    for step in range(1, 12):
        month = (today.month - 1 + step) % 12 + 1
        if month in months:
            return date(today.year + (1 if month < today.month else 0), month, 1)
    return None


def month_span(months: Sequence[int]) -> str:
    """The months as runs, such as "August to January" or "March, May and July"."""
    chosen = sorted(set(months))
    runs: list[list[int]] = []
    for month in chosen:
        if runs and runs[-1][-1] == month - 1:
            runs[-1].append(month)
        else:
            runs.append([month])
    # A run that ends in December goes on into one that starts in January.
    if len(runs) > 1 and runs[0][0] == 1 and runs[-1][-1] == 12:
        runs[-1].extend(runs.pop(0))
    words = [
        MONTHS[run[0] - 1] if len(run) == 1 else f"{MONTHS[run[0] - 1]} to {MONTHS[run[-1] - 1]}"
        for run in runs
    ]
    return words[0] if len(words) == 1 else f"{', '.join(words[:-1])} and {words[-1]}"


def month_name(month: date) -> str:
    return f"{MONTHS[month.month - 1]} {month.year}"


def advise(facts: ListingFacts, calendar: SeasonalCalendar, today: date) -> ChannelAdvice:
    season = matching_season(facts, calendar)
    timing = TimingHint(
        season=season.name if season else None,
        season_span=month_span(season.months) if season else None,
        release_month=release_month(season.months, today) if season else None,
    )
    return ChannelAdvice(channels=channel_options(facts), timing=timing)


def _names(channels: Sequence[Channel]) -> str:
    return " and ".join(CHANNEL_NAMES[channel] for channel in channels)


def template_reason(advice: ChannelAdvice, facts: ListingFacts) -> str:
    """The fixed sentence, which only restates what code decided."""
    takes = advice.takes()
    category = CATEGORY_LABELS[facts.category].lower()
    refused = [option for option in advice.channels if not option.takes]
    if not takes:
        channels = "No channel takes it"
    elif not refused:
        channels = f"{_names(takes)} both take {category}"
    elif all(not channel_takes(option.channel, facts.category) for option in refused):
        channels = f"Only {_names(takes)} takes {category}"
    else:
        refused_by = refused[0].channel
        channels = (
            f"Only {_names(takes)} takes it, because {CHANNEL_NAMES[refused_by]} needs a "
            f"{_missing_field(refused_by, facts)} and the card has none"
        )
    timing = advice.timing
    if timing.season is None:
        when = "it matches no season, so list it now"
    elif timing.release_month is None:
        when = f"its season, {timing.season}, runs from {timing.season_span}, so list it now"
    else:
        when = (
            f"its season, {timing.season}, runs from {timing.season_span}, so hold it until "
            f"{month_name(timing.release_month)}"
        )
    return f"{channels}, and {when}."


def facts_lines(advice: ChannelAdvice, facts: ListingFacts, template: str) -> list[str]:
    lines: list[tuple[str, str]] = []
    name = " ".join(part for part in (facts.brand, facts.product) if part)
    if name:
        lines.append(("Item", name))
    lines.append(("Category", CATEGORY_LABELS[facts.category]))
    for option in advice.channels:
        label = f"{CHANNEL_NAMES[option.channel]}, {CHANNEL_KINDS[option.channel]}"
        lines.append((label, "takes it" if option.takes else f"can't take it. {option.why_not}"))
    timing = advice.timing
    if timing.season is None:
        lines.append(("Season", "none, so it can be listed in any month"))
    else:
        lines.append(("Season", f"{timing.season}, listed from {timing.season_span}"))
    if timing.release_month is None:
        lines.append(("Timing", "list now"))
    else:
        lines.append(("Timing", f"hold until {month_name(timing.release_month)}"))
    lines.append(("Recommendation", template))
    return [f"- {label}: {value}" for label, value in lines]


def build_messages(advice: ChannelAdvice, facts: ListingFacts, template: str) -> list[Message]:
    facts_text = "\n".join(facts_lines(advice, facts, template))
    content = PROMPT.format(facts=facts_text, reason_max=REASON_MAX)
    return [{"role": "user", "content": content}]


class ReasonText(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    reason: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=REASON_MAX)
    ]


def parse_reason(reply: str) -> ReasonText:
    text = ReasonText.model_validate_json(strip_reply(reply))
    if "\n" in text.reason:
        raise ValueError("the reason is more than one line")
    return text


def unsupported_words(reason: str, facts: str) -> list[str]:
    """The numbers and months in the reason that the facts don't have, which code refuses."""
    extra = {number for number in _numbers(reason) if number not in _numbers(facts)}
    known = {month.lower() for month in _MONTH_WORDS.findall(facts)}
    extra |= {month for month in _MONTH_WORDS.findall(reason) if month.lower() not in known}
    return sorted(extra)


@dataclass(frozen=True)
class ReasonResult:
    text: str
    source: DraftSource
    fallback_reason: FallbackReason | None


def write_reason(
    advice: ChannelAdvice, facts: ListingFacts, providers: Sequence[ChatModel]
) -> ReasonResult:
    """The model's sentence when it passes the check in time, and the fixed one otherwise."""
    template = template_reason(advice, facts)
    if not providers:
        return ReasonResult(template, DraftSource.TEMPLATE, FallbackReason.NOT_CONFIGURED)
    messages = build_messages(advice, facts, template)
    failed = ReasonResult(template, DraftSource.TEMPLATE, FallbackReason.MODEL_FAILED)
    call = _reasons.submit(complete_json, messages, list(providers), parse_reason)
    try:
        reply = call.result(timeout=REASON_SECONDS)
    except FutureTimeoutError:
        logger.warning("channel reason: no reply within %s seconds", REASON_SECONDS)
        return failed
    except ModelReplyError as error:
        logger.warning("channel reason: %s", error)
        return failed
    except Exception:
        # A bug, not the model, but the recommendation still shows with the fixed sentence.
        logger.exception("channel reason failed")
        return failed
    extra = unsupported_words(reply.value.reason, messages[0]["content"])
    if extra:
        logger.warning("channel reason: words not in the facts: %s", extra)
        return ReasonResult(template, DraftSource.TEMPLATE, FallbackReason.FLAGGED)
    return ReasonResult(reply.value.reason, DraftSource.MODEL, None)


def recommend(
    facts: ListingFacts,
    calendar: SeasonalCalendar,
    today: date,
    providers: Sequence[ChatModel],
) -> ChannelRecommendation:
    advice = advise(facts, calendar, today)
    reason = write_reason(advice, facts, providers)
    return ChannelRecommendation(
        **advice.model_dump(),
        reason=reason.text,
        reason_source=reason.source,
        reason_fallback=reason.fallback_reason,
    )
