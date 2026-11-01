"""Score the model's listing drafts on the evaluation items with the claim checker.

Run `uv run python -m app.draft_eval` in api/ to check the saved drafts in api/eval/drafts/ and
rewrite api/eval/draft_results.json and docs/listing-drafts.md. It makes no model call and needs
no keys.

`--write-drafts` asks the model for every draft that is missing, or that was written from a prompt
that has since changed, which needs the AI keys. Each draft is written from the saved item card and
the item's staff entries, for Channel A, which is the only channel that takes games and hardware.
"""

import argparse
import hashlib
import time
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from app.ai import (
    ChatModel,
    ModelReplyError,
    complete_json,
    get_chat_model,
    get_fallback_chat_model,
)
from app.claims import ClaimFlag, ClaimRule, ListingFacts, check_listing
from app.evaluate import (
    EVAL_DIR,
    EvalItem,
    EvaluationStopped,
    _item_card,
    _Strict,
    load_card,
    load_fresh_items,
    load_items,
)
from app.listing_drafts import (
    PROMPT_SHA256,
    DraftText,
    build_messages,
    category_options,
    parse_draft,
    template_draft,
)
from app.models import Category, Channel

DRAFTS_DIR = EVAL_DIR / "drafts"
RESULTS_FILE = EVAL_DIR / "draft_results.json"
REPORT_FILE = Path(__file__).resolve().parents[2] / "docs" / "listing-drafts.md"
CHANNEL = Channel.CHANNEL_A
# Keeps a run inside Groq's free tokens per minute, since a draft with its reasoning is near 2,000.
SECONDS_BETWEEN_DRAFTS = 15


class SavedDraft(_Strict):
    """The model's own draft for one item, before the checker or the template."""

    # The SHA-256 of the whole message the model read, so a changed prompt or card shows.
    prompt_sha256: str
    provider: str | None
    draft: DraftText | None
    failure: str | None = None


class DraftScore(_Strict):
    id: str
    provider: str | None
    title: str | None
    description: str | None
    category: str | None
    passed: bool
    flags: list[ClaimFlag]
    template_passed: bool


class DraftResults(_Strict):
    items: int
    passed: int
    flagged: int
    no_draft: int
    pass_rate: float | None
    flags_by_rule: dict[str, int]
    template_passed: int
    prompt_sha256: str
    providers: dict[str, int]
    drafts: list[DraftScore]


def item_facts(item: EvalItem) -> ListingFacts:
    return ListingFacts.from_card(_item_card(item, load_card(item).card))


def message_sha256(facts: ListingFacts) -> str:
    return hashlib.sha256(str(build_messages(facts, CHANNEL)[0]["content"]).encode()).hexdigest()


def draft_path(item: EvalItem, directory: Path = DRAFTS_DIR) -> Path:
    return directory / f"{item.id}.json"


def load_draft(item: EvalItem, facts: ListingFacts, directory: Path = DRAFTS_DIR) -> SavedDraft:
    path = draft_path(item, directory)
    if not path.exists():
        raise EvaluationStopped(f"No saved draft for {item.id}, so run again with --write-drafts.")
    saved = SavedDraft.model_validate_json(path.read_bytes())
    if saved.prompt_sha256 != message_sha256(facts):
        raise EvaluationStopped(
            f"The draft for {item.id} was written from a different prompt or card, "
            "so run again with --write-drafts."
        )
    return saved


def write_draft(facts: ListingFacts, providers: Sequence[ChatModel]) -> SavedDraft:
    options = category_options(CHANNEL, facts.category)
    sha = message_sha256(facts)
    try:
        reply = complete_json(
            build_messages(facts, CHANNEL), providers, lambda text: parse_draft(text, options)
        )
    except ModelReplyError as error:
        return SavedDraft(prompt_sha256=sha, provider=None, draft=None, failure=str(error))
    return SavedDraft(prompt_sha256=sha, provider=reply.provider, draft=reply.value)


def write_missing_drafts(
    items: list[EvalItem], providers: Sequence[ChatModel], directory: Path = DRAFTS_DIR
) -> int:
    """Ask the model for each draft that is missing or stale, and save its reply as it came."""
    directory.mkdir(parents=True, exist_ok=True)
    written = 0
    for item in items:
        facts = item_facts(item)
        try:
            load_draft(item, facts, directory)
            continue
        except EvaluationStopped:
            pass
        if written:
            time.sleep(SECONDS_BETWEEN_DRAFTS)
        saved = write_draft(facts, providers)
        draft_path(item, directory).write_text(
            saved.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        written += 1
        print(f"{item.id}: {saved.provider or saved.failure}", flush=True)
    return written


def score_draft(item: EvalItem, facts: ListingFacts, saved: SavedDraft) -> DraftScore:
    template = template_draft(facts, CHANNEL)
    template_passed = not check_listing(template.title, template.description, facts)
    draft = saved.draft
    flags = check_listing(draft.title, draft.description, facts) if draft else []
    return DraftScore(
        id=item.id,
        provider=saved.provider,
        title=draft.title if draft else None,
        description=draft.description if draft else None,
        category=draft.category if draft else None,
        passed=draft is not None and not flags,
        flags=flags,
        template_passed=template_passed,
    )


def summarize(rows: list[DraftScore]) -> DraftResults:
    passed = sum(row.passed for row in rows)
    no_draft = sum(row.title is None for row in rows)
    by_rule = Counter(flag.rule.value for row in rows for flag in row.flags)
    return DraftResults(
        items=len(rows),
        passed=passed,
        flagged=len(rows) - passed - no_draft,
        no_draft=no_draft,
        pass_rate=round(passed / len(rows), 3) if rows else None,
        flags_by_rule={rule.value: by_rule[rule.value] for rule in ClaimRule},
        template_passed=sum(row.template_passed for row in rows),
        prompt_sha256=PROMPT_SHA256,
        providers=dict(sorted(Counter(row.provider or "none" for row in rows).items())),
        drafts=rows,
    )


def eval_items() -> list[EvalItem]:
    """The games and hardware items, because Channel A is the only channel drafted here."""
    items = [*load_items(), *load_fresh_items()]
    return [item for item in items if item.category is not Category.APPAREL]


def run(directory: Path = DRAFTS_DIR) -> DraftResults:
    rows = []
    for item in eval_items():
        facts = item_facts(item)
        rows.append(score_draft(item, facts, load_draft(item, facts, directory)))
    return summarize(rows)


def _rate(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def _cell(text: str | None) -> str:
    return "none" if text is None else text.replace("|", "/").replace("\n", " ")


def render_report(results: DraftResults) -> str:
    """The results as Markdown, generated so that a change shows up in review."""
    providers = ", ".join(f"`{name}` {count}" for name, count in results.providers.items())
    rules = ", ".join(
        f"{rule.replace('_', ' ')} {count}" for rule, count in results.flags_by_rule.items()
    )
    lines = [
        "# Listing drafts",
        "",
        "This page is generated by `uv run python -m app.draft_eval` in `api/`, so edit the script "
        "or the prompt in `api/app/listing_drafts.py` instead of this page.",
        "It measures how often the model's own listing draft passes the claim checker, before any "
        "staff edit.",
        "The prompt, the model and the checker's rules are described in "
        "[architecture.md](architecture.md#listing-drafts).",
        "",
        "## Result",
        "",
        f"**{results.passed} of {results.items} drafts pass the checker, "
        f"{_rate(results.pass_rate)}.**",
        f"{results.flagged} were flagged and would have gone to the fixed template, and "
        f"{results.no_draft} got no usable reply from either model.",
        f"The template itself passes on {results.template_passed} of {results.items} items.",
        "",
        f"Flags by rule: {rules}.",
        "",
        "## Limits",
        "",
        "- **Not measured: apparel and Channel B.** Every item here is games or hardware, which "
        "only Channel A takes, so these results say nothing about clothing drafts.",
        "- Every item has the same staff entries, pre-owned and not complete in box, with nothing "
        "recorded about testing, so the rules about flaws, sizes and working claims are barely "
        "exercised here, and the unit tests in `api/tests/test_claims.py` cover them instead.",
        "- A pass means the checker found no unsupported claim, not that a person read the draft "
        "and found it good, and the checker can miss a claim it has no rule for.",
        "- With this few items, one draft moves the pass rate by about 2 points.",
        "",
        "## Where the drafts came from",
        "",
        "Each draft was written once from the saved item card in `api/eval/cards/` and the item's "
        "staff entries, and saved as it came in `api/eval/drafts/`.",
        f"Providers: {providers}.",
        f"The prompt's SHA-256 is `{results.prompt_sha256}`, so changing the prompt changes this "
        "page, and the drafts then need writing again with `--write-drafts`.",
        "",
        "## Drafts",
        "",
        "| Item | Title | Category | Flags |",
        "| --- | --- | --- | --- |",
    ]
    for row in results.drafts:
        flags = ", ".join(
            f"{flag.rule.value.replace('_', ' ')}: {flag.phrase}" for flag in row.flags
        )
        lines.append(
            f"| {row.id} | {_cell(row.title)} | {_cell(row.category)} | {_cell(flags or None)} |"
        )
    return "\n".join(lines) + "\n"


def results_json(results: DraftResults) -> str:
    return results.model_dump_json(indent=2) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write-drafts", action="store_true", help="ask the model for missing or stale drafts"
    )
    args = parser.parse_args()
    try:
        if args.write_drafts:
            fallback = get_fallback_chat_model()
            providers = [get_chat_model(), *([fallback] if fallback else [])]
            print(f"Wrote {write_missing_drafts(eval_items(), providers)} drafts.")
        results = run()
    except EvaluationStopped as error:
        raise SystemExit(str(error)) from None
    RESULTS_FILE.write_text(results_json(results), encoding="utf-8", newline="\n")
    REPORT_FILE.write_text(render_report(results), encoding="utf-8", newline="\n")
    print(f"Passed: {results.passed} of {results.items}, {_rate(results.pass_rate)}")
    print(f"Wrote {RESULTS_FILE} and {REPORT_FILE}.")


if __name__ == "__main__":
    main()
