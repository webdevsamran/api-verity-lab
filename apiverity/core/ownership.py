"""Who owns a contract, read from the file the repository already keeps.

A finding needs an owner before it can become somebody's Monday. Most
repositories already answer that question in `CODEOWNERS`, and asking teams to
maintain a second ownership file next to the one they have is how the second
one goes stale.

GitHub's matching rule is unusual and worth stating, because getting it
backwards silently assigns the wrong team: **the last matching pattern wins**,
not the most specific one. `*` on line one and `/api/ @payments` on line two
means the payments team owns `/api`, and a reader scanning top-down for the
first match would conclude the opposite.

Patterns are gitignore-shaped rather than glob-shaped, and the differences that
matter here are: a leading `/` anchors to the repository root, a trailing `/`
matches a directory and everything under it, and a pattern with no slash at all
matches at any depth. `**` spans directories; a bare `*` does not.

An unowned contract is reported as unowned. Guessing an owner from a directory
name would produce a plausible team that never agreed to anything.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

#: Where GitHub looks, in the order it looks. The first file that exists wins.
CODEOWNERS_LOCATIONS = (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS")


@dataclass(frozen=True)
class Rule:
    """One CODEOWNERS line."""

    pattern: str
    owners: tuple[str, ...]
    line: int


def _to_regex(pattern: str) -> re.Pattern[str]:
    """A gitignore-shaped CODEOWNERS pattern as a regex over a posix path."""
    anchored = pattern.startswith("/")
    directory = pattern.endswith("/")
    body = pattern.strip("/")

    parts: list[str] = []
    for segment in body.split("/"):
        if segment == "**":
            parts.append(".*")
            continue
        escaped = ""
        for char in segment:
            if char == "*":
                escaped += "[^/]*"
            elif char == "?":
                escaped += "[^/]"
            else:
                escaped += re.escape(char)
        parts.append(escaped)

    joined = "/".join(parts)
    # A pattern naming a directory, or one with a trailing slash, owns
    # everything beneath it.
    tail = "(/.*)?$" if not directory else "/.*$"
    prefix = "^" if anchored or "/" in body else "^(.*/)?"
    return re.compile(prefix + joined + tail)


def parse_codeowners(text: str) -> list[Rule]:
    """Rules in file order. Order is the whole semantics, so it is preserved."""
    rules: list[Rule] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        pattern, *owners = line.split()
        if not owners:
            continue
        rules.append(Rule(pattern=pattern, owners=tuple(owners), line=number))
    return rules


def find_codeowners(root: str | Path) -> Path | None:
    base = Path(root)
    for candidate in CODEOWNERS_LOCATIONS:
        path = base / candidate
        if path.is_file():
            return path
    return None


@dataclass
class Ownership:
    """The rules of one repository, and the file they came from."""

    rules: list[Rule]
    source: str | None = None

    def owners_of(self, relative_path: str) -> tuple[str, ...]:
        """Owners of a repo-relative path, or an empty tuple.

        Last match wins. Iterating in reverse and returning the first hit is
        the same rule stated the way GitHub states it.
        """
        target = PurePosixPath(relative_path.replace("\\", "/")).as_posix().lstrip("/")
        for rule in reversed(self.rules):
            if _to_regex(rule.pattern).match(target):
                return rule.owners
        return ()

    def rule_for(self, relative_path: str) -> Rule | None:
        target = relative_path.replace("\\", "/").lstrip("/")
        for rule in reversed(self.rules):
            if _to_regex(rule.pattern).match(target):
                return rule
        return None


def load_ownership(root: str | Path) -> Ownership:
    """Read a repository's CODEOWNERS, or an empty ruleset if it has none."""
    path = find_codeowners(root)
    if path is None:
        return Ownership(rules=[], source=None)
    return Ownership(
        rules=parse_codeowners(path.read_text(encoding="utf-8-sig")),
        source=str(path),
    )


__all__ = [
    "CODEOWNERS_LOCATIONS",
    "Ownership",
    "Rule",
    "find_codeowners",
    "load_ownership",
    "parse_codeowners",
]
