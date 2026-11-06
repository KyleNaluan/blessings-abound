"""Check a pull request's own commits and its description against CONTRIBUTING.md.

CI runs it on every pull request with the base and head commits and the description:

    export PR_BODY="$(gh pr view 12 --json body -q .body)"
    python3 .github/scripts/pr_rules.py origin/main HEAD

It prints one line for each broken rule, naming the commit or section, and exits 1 if any broke.
It uses only the standard library, so it needs nothing installed.
"""

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent.parent / "pull_request_template.md"

# Attribution lines some tools add by default, which CONTRIBUTING.md keeps out of the repo.
CO_AUTHOR = re.compile(r"^\s*co-authored-by\s*:", re.IGNORECASE | re.MULTILINE)
GENERATED_WITH = re.compile(r"^[^\w\s-]*\s*generated with\b", re.IGNORECASE | re.MULTILINE)
# Links to a coding agent's session or task, which some tools put in a commit or a description.
SESSION_LINK = re.compile(
    r"https?://(?:[\w-]+\.)*"
    r"(?:claude\.ai|claude\.com|chatgpt\.com|chat\.openai\.com|devin\.ai|cursor\.com|jules\.google\.com)"
    r"/\S*",
    re.IGNORECASE,
)
# A conventional-commit style prefix such as `feat:`, `fix(api):`, `chore!:`,
# `no-mistakes(document):` or `v2:`: one word of letters, digits and hyphens.
SUBJECT_PREFIX = re.compile(r"^[A-Za-z0-9-]+(?:\([^)]*\))?!?:")
ISSUE_LINK = re.compile(r"\b(?:closes|refs) #\d+\b", re.IGNORECASE)
# A line that only links an issue, which isn't part of the section above it.
ISSUE_LINE = re.compile(r"^\s*(?:closes|refs)\s*#\d*\s*$", re.IGNORECASE)
HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$")


@dataclass(frozen=True)
class Commit:
    sha: str
    message: str

    @property
    def subject(self) -> str:
        return self.message.split("\n", 1)[0].strip()

    @property
    def label(self) -> str:
        return f'Commit {self.sha[:7]} "{self.subject}"'


def attribution_problems(text: str) -> list[str]:
    problems = []
    if CO_AUTHOR.search(text):
        problems.append("has a Co-Authored-By line")
    if GENERATED_WITH.search(text):
        problems.append('has a "Generated with" footer')
    link = SESSION_LINK.search(text)
    if link:
        problems.append(f"has a tool session link, {link.group(0)}")
    return problems


def check_commit(commit: Commit) -> list[str]:
    problems = [f"{commit.label} {p}." for p in attribution_problems(commit.message)]
    if SUBJECT_PREFIX.match(commit.subject):
        problems.append(
            f"{commit.label} starts with a prefix, so write the first line as a plain "
            'present-tense summary instead, such as "Add delist call when an item sells".'
        )
    return problems


def normalize(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\u2019", "'")


def template_sections(template: str) -> list[str]:
    sections = []
    for line in normalize(template).splitlines():
        match = HEADING.match(line)
        if match:
            sections.append(match.group(1))
    return sections


def check_description(body: str, sections: list[str]) -> list[str]:
    body = normalize(body)
    problems = [f"The description {p}." for p in attribution_problems(body)]

    # Map each heading in the description to the text under it, up to the next heading.
    found: dict[str, str] = {}
    current = None
    for line in body.splitlines():
        match = HEADING.match(line)
        if match:
            current = match.group(1).casefold()
            found.setdefault(current, "")
        elif current is not None and not ISSUE_LINE.match(line):
            found[current] += line.strip()

    for section in sections:
        key = section.casefold()
        if key not in found:
            problems.append(f'The description is missing the "{section}" section.')
        elif not found[key]:
            problems.append(f'The description\'s "{section}" section is empty.')

    if not ISSUE_LINK.search(body):
        problems.append(
            "The description has neither Closes #N nor Refs #N, so add the issue it works on."
        )
    return problems


def pr_commits(base: str, head: str) -> list[Commit]:
    """Read the commits on head that aren't on base, which are the pull request's own."""
    out = subprocess.run(
        ["git", "log", "--format=%H%x00%B%x00", f"{base}..{head}"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    fields = out.split("\x00")
    return [
        Commit(sha.strip(), normalize(message).strip())
        for sha, message in zip(fields[0::2], fields[1::2], strict=False)
        if sha.strip()
    ]


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: pr_rules.py <base> <head>, with the description in PR_BODY", file=sys.stderr)
        return 2
    base, head = argv[1], argv[2]
    commits = pr_commits(base, head)
    problems = [p for commit in commits for p in check_commit(commit)]
    sections = template_sections(TEMPLATE.read_text(encoding="utf-8"))
    problems += check_description(os.environ.get("PR_BODY", ""), sections)

    prefix = "::error::" if os.environ.get("GITHUB_ACTIONS") == "true" else ""
    for problem in problems:
        print(f"{prefix}{problem}")
    if problems:
        print(f"{len(problems)} rule(s) from CONTRIBUTING.md broken.")
        return 1
    print(f"{len(commits)} commit(s) and the description follow CONTRIBUTING.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
