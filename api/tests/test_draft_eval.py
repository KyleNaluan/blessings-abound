import json
from pathlib import Path

import pytest

from app.draft_eval import (
    REPORT_FILE,
    RESULTS_FILE,
    SavedDraft,
    draft_path,
    eval_items,
    item_facts,
    load_draft,
    message_sha256,
    render_report,
    results_json,
    run,
    score_draft,
    summarize,
    write_draft,
    write_missing_drafts,
)
from app.evaluate import EvaluationStopped
from app.listing_drafts import DraftText


class StubChat:
    def __init__(self, reply: str) -> None:
        self.name = "stub"
        self.reply = reply
        self.calls = 0

    def complete(self, messages: object, *, json_mode: bool = False) -> str:
        self.calls += 1
        return self.reply


GAME_BOY = next(item for item in eval_items() if item.id == "game-boy")


def clean_reply() -> str:
    return json.dumps(
        {
            "title": "Nintendo Game Boy handheld console - Pre-owned",
            "description": "Nintendo Game Boy, pre-owned.",
            "category": "Video Game Consoles",
        }
    )


def test_a_draft_passes_only_with_no_flags() -> None:
    facts = item_facts(GAME_BOY)
    sha = message_sha256(facts)
    clean = DraftText.model_validate_json(clean_reply())
    flagged = clean.model_copy(update={"title": "Rare Game Boy from 1989"})

    passed = score_draft(GAME_BOY, facts, SavedDraft(prompt_sha256=sha, provider="x", draft=clean))
    assert passed.passed
    assert passed.template_passed
    failed = score_draft(
        GAME_BOY, facts, SavedDraft(prompt_sha256=sha, provider="x", draft=flagged)
    )
    assert not failed.passed
    assert {flag.phrase for flag in failed.flags} == {"rare", "1989"}
    missing = score_draft(
        GAME_BOY, facts, SavedDraft(prompt_sha256=sha, provider=None, draft=None, failure="no")
    )
    assert not missing.passed

    results = summarize([passed, failed, missing])
    assert (results.passed, results.flagged, results.no_draft) == (1, 1, 1)
    assert results.pass_rate == 0.333
    assert results.flags_by_rule["banned_word"] == 1
    assert results.flags_by_rule["number"] == 1


def test_drafts_are_written_once_and_again_when_the_prompt_changes(tmp_path: Path) -> None:
    chat = StubChat(clean_reply())
    assert write_missing_drafts([GAME_BOY], [chat], tmp_path) == 1
    assert write_missing_drafts([GAME_BOY], [chat], tmp_path) == 0
    assert chat.calls == 1

    path = draft_path(GAME_BOY, tmp_path)
    stale = SavedDraft.model_validate_json(path.read_bytes()).model_copy(
        update={"prompt_sha256": "old"}
    )
    path.write_text(stale.model_dump_json(), encoding="utf-8")
    with pytest.raises(EvaluationStopped, match="different prompt or card"):
        load_draft(GAME_BOY, item_facts(GAME_BOY), tmp_path)
    assert write_missing_drafts([GAME_BOY], [chat], tmp_path) == 1


def test_a_model_with_no_usable_reply_is_saved_as_no_draft() -> None:
    saved = write_draft(item_facts(GAME_BOY), [StubChat("not json")])
    assert saved.draft is None
    assert saved.failure is not None


def test_a_missing_draft_stops_the_score(tmp_path: Path) -> None:
    with pytest.raises(EvaluationStopped, match="No saved draft for"):
        run(tmp_path)


def test_the_saved_results_match_the_drafts_and_the_checker() -> None:
    results = run()
    hint = "Run `uv run python -m app.draft_eval` in api/ to rewrite the saved results."
    assert results_json(results) == RESULTS_FILE.read_text(encoding="utf-8"), hint
    assert render_report(results) == REPORT_FILE.read_text(encoding="utf-8"), hint
