"""Tests for pr_rules.py, run with the command in the README's "Tests and lint" section."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pr_rules
from pr_rules import Commit, check_commit, check_description, template_sections

SECTIONS = template_sections(pr_rules.TEMPLATE.read_text(encoding="utf-8"))

GOOD_BODY = """## What changed and why

This adds the check.

## How to test it

Run the tests.

## Anything you're unsure about

Nothing much.

Closes #76
"""


def commit(message: str) -> Commit:
    return Commit("0123456789abcdef", message)


class TemplateTest(unittest.TestCase):
    def test_sections_come_from_the_template(self):
        self.assertEqual(
            SECTIONS,
            ["What changed and why", "How to test it", "Anything you're unsure about"],
        )


class CommitTest(unittest.TestCase):
    def test_plain_commit_passes(self):
        self.assertEqual(check_commit(commit("Add delist call when an item sells")), [])

    def test_commit_with_a_body_passes(self):
        message = "Add delist call when an item sells\n\nThe sale webhook calls it: once.\n"
        self.assertEqual(check_commit(commit(message)), [])

    def test_merge_commits_from_main_pass(self):
        for subject in [
            "Merge branch 'main' into kyle/ebay-listing-sync",
            "Merge remote-tracking branch 'origin/main' into kyle/ebay-listing-sync",
            "Merge pull request #74 from KyleNaluan/kyle/ba-intake-triage",
        ]:
            with self.subTest(subject=subject):
                self.assertEqual(check_commit(commit(subject)), [])

    def test_a_colon_later_in_the_subject_passes(self):
        for subject in [
            "Update the README: add the test commands",
            "Fix the view: name",
            "Re-run the v2 import: it timed out",
        ]:
            with self.subTest(subject=subject):
                self.assertEqual(check_commit(commit(subject)), [])

    def test_prefixed_subjects_fail(self):
        for subject in [
            "feat(api): add comps lookup",
            "fix: stop a crash",
            "chore!: drop py3.11",
            "no-mistakes(document): Fix stale dashboard view name in database.md",
            "v2: rework the import",
        ]:
            with self.subTest(subject=subject):
                problems = check_commit(commit(subject))
                self.assertEqual(len(problems), 1)
                self.assertIn(f'Commit 0123456 "{subject}" starts with a prefix', problems[0])

    def test_co_author_line_fails_in_any_case(self):
        for line in [
            "Co-Authored-By: Bot <bot@example.com>",
            "co-authored-by: Bot <bot@example.com>",
        ]:
            with self.subTest(line=line):
                problems = check_commit(commit(f"Add the check\n\n{line}"))
                self.assertEqual(
                    problems, ['Commit 0123456 "Add the check" has a Co-Authored-By line.']
                )

    def test_generated_with_footer_fails_in_any_case(self):
        for line in [
            "\U0001f916 Generated with [Some Tool](https://example.com/tool)",
            "GENERATED WITH some tool",
        ]:
            with self.subTest(line=line):
                problems = check_commit(commit(f"Add the check\n\n{line}"))
                self.assertEqual(
                    problems, ['Commit 0123456 "Add the check" has a "Generated with" footer.']
                )

    def test_generated_with_in_the_middle_of_a_sentence_passes(self):
        message = "Add the history\n\nThe rows are generated with a fixed seed."
        self.assertEqual(check_commit(commit(message)), [])

    def test_session_link_fails(self):
        for link in [
            "https://claude.ai/code/session_01ABC",
            "https://chatgpt.com/codex/tasks/task_e_123",
            "https://app.devin.ai/sessions/abc",
        ]:
            with self.subTest(link=link):
                problems = check_commit(commit(f"Add the check\n\n{link}"))
                self.assertEqual(len(problems), 1)
                self.assertIn(f"has a tool session link, {link}", problems[0])

    def test_every_broken_rule_is_reported(self):
        message = "feat: add the check\n\nCo-Authored-By: Bot <bot@example.com>"
        self.assertEqual(len(check_commit(commit(message))), 2)


class DescriptionTest(unittest.TestCase):
    def test_good_description_passes(self):
        self.assertEqual(check_description(GOOD_BODY, SECTIONS), [])

    def test_refs_passes_in_place_of_closes(self):
        self.assertEqual(check_description(GOOD_BODY.replace("Closes", "Refs"), SECTIONS), [])

    def test_windows_line_endings_and_a_curly_apostrophe_pass(self):
        body = GOOD_BODY.replace("'", "\u2019").replace("\n", "\r\n")
        self.assertEqual(check_description(body, SECTIONS), [])

    def test_missing_section_fails_by_name(self):
        body = GOOD_BODY.replace("## How to test it\n\nRun the tests.\n\n", "")
        self.assertEqual(
            check_description(body, SECTIONS),
            ['The description is missing the "How to test it" section.'],
        )

    def test_empty_section_fails_by_name(self):
        body = GOOD_BODY.replace("Nothing much.", "")
        self.assertEqual(
            check_description(body, SECTIONS),
            ["The description's \"Anything you're unsure about\" section is empty."],
        )

    def test_unfilled_template_fails(self):
        problems = check_description(pr_rules.TEMPLATE.read_text(encoding="utf-8"), SECTIONS)
        self.assertEqual(len(problems), 4)
        self.assertIn("neither Closes #N nor Refs #N", problems[-1])

    def test_bare_closes_placeholder_fails(self):
        body = GOOD_BODY.replace("Closes #76", "Closes #")
        self.assertEqual(
            check_description(body, SECTIONS),
            ["The description has neither Closes #N nor Refs #N, so add the issue it works on."],
        )

    def test_empty_description_fails(self):
        self.assertEqual(len(check_description("", SECTIONS)), 4)

    def test_co_author_line_fails(self):
        body = GOOD_BODY + "\nco-authored-by: Bot <bot@example.com>\n"
        self.assertEqual(
            check_description(body, SECTIONS), ["The description has a Co-Authored-By line."]
        )

    def test_generated_with_footer_fails(self):
        body = GOOD_BODY + "\n\U0001f916 Generated with Some Tool\n"
        self.assertEqual(
            check_description(body, SECTIONS), ['The description has a "Generated with" footer.']
        )


class GitTest(unittest.TestCase):
    """Run the script on a real repository, the way CI does."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.git("init", "-q", "-b", "main")
        self.commit_file("a", "feat: an old commit on main with a prefix")
        self.git("checkout", "-q", "-b", "kyle/check")

    def git(self, *args: str) -> str:
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
        }
        return subprocess.run(
            ["git", "-c", "commit.gpgsign=false", *args],
            cwd=self.dir.name,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        ).stdout

    def commit_file(self, name: str, message: str) -> None:
        Path(self.dir.name, name).write_text(message, encoding="utf-8")
        self.git("add", name)
        self.git("commit", "-q", "-m", message)

    def run_script(self, body: str = GOOD_BODY) -> subprocess.CompletedProcess[str]:
        env = {**os.environ, "PR_BODY": body, "GITHUB_ACTIONS": "false"}
        return subprocess.run(
            [sys.executable, pr_rules.__file__, "main", "HEAD"],
            cwd=self.dir.name,
            env=env,
            capture_output=True,
            text=True,
        )

    def test_only_the_branch_commits_are_checked(self):
        self.commit_file("b", "Add the check")
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("1 commit(s)", result.stdout)

    def test_merging_main_into_the_branch_passes(self):
        self.commit_file("b", "Add the check")
        self.git("checkout", "-q", "main")
        self.commit_file("c", "Add a change on main")
        self.git("checkout", "-q", "kyle/check")
        self.git("merge", "-q", "--no-edit", "main")
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_a_broken_commit_fails_and_is_named(self):
        self.commit_file("b", "Add the check\n\nCo-authored-by: Bot <bot@example.com>")
        sha = self.git("rev-parse", "--short=7", "HEAD").strip()
        result = self.run_script()
        self.assertEqual(result.returncode, 1)
        self.assertIn(f'Commit {sha} "Add the check" has a Co-Authored-By line.', result.stdout)

    def test_a_broken_description_fails(self):
        self.commit_file("b", "Add the check")
        result = self.run_script(body="")
        self.assertEqual(result.returncode, 1)
        self.assertIn("4 rule(s)", result.stdout)

    def test_errors_are_annotated_in_github_actions(self):
        self.commit_file("b", "fix: the check")
        env = {**os.environ, "PR_BODY": GOOD_BODY, "GITHUB_ACTIONS": "true"}
        result = subprocess.run(
            [sys.executable, pr_rules.__file__, "main", "HEAD"],
            cwd=self.dir.name,
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertTrue(result.stdout.startswith("::error::Commit "), result.stdout)


if __name__ == "__main__":
    unittest.main()
