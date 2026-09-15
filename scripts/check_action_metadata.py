"""Hold `action.yml` to what the GitHub Marketplace and consumers require.

GitHub offers to publish any repository with a root `action.yml` to the
Marketplace. It accepts the listing at release time, and it rejects one for
reasons that are invisible until the moment you try: branding that is missing
or uses a colour outside the eight it allows, an icon on its excluded list, a
missing description.

Worse than a rejected listing is an accepted one whose quickstart does not
work. This repository shipped that: `docs/ci.md` told readers

    uses: webdevsamran/api-verity-lab@v1

three times, `docs/faq.md` said `@v0` once, and **neither tag existed**. The
only tag that resolves is `v0.2.0`, which predates `action.yml` entirely, so
every documented way to use this action failed with "Unable to resolve action".
Nothing anywhere noticed, because nothing in this repository has ever used it
the way a consumer does.

So this checks the three things that are wrong only somewhere nobody looks:

* **Marketplace readiness** -- the metadata GitHub requires of a listing.
* **A resolvable reference** -- every `owner/repo@ref` in the documentation
  names the moving major tag that matches this project's own version, so the
  docs cannot drift from the release that `release.yml` publishes.
* **Documented surface** -- every input and output carries a description,
  because those are what the Marketplace listing renders.

    python scripts/check_action_metadata.py           # report
    python scripts/check_action_metadata.py --check    # exit 1 on any problem
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys
import tomllib
from typing import Any

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from page_meta import front_matter

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: The Marketplace reads the action from the repository root and nowhere else.
#: A nested `action.yml` is a perfectly good action and is not publishable.
ACTION = ROOT / "action.yml"
PYPROJECT = ROOT / "pyproject.toml"
PAGE = ROOT / "docs" / "github-action.md"

#: Files whose `uses:` lines a reader will copy.
DOCUMENTED_IN = ("README.md", "docs/ci.md", "docs/faq.md", "docs/github-action.md")

#: The eight GitHub accepts. Anything else is rejected when the listing is
#: published, which is after the tag exists and is the worst time to find out.
BRANDING_COLORS = frozenset(
    {"white", "yellow", "blue", "green", "orange", "red", "purple", "gray-dark"}
)

#: Feather icons GitHub explicitly refuses, from its own published list.
#:
#: Only the exclusions are encoded, not the ~280 accepted names. Writing those
#: out from memory and calling them "the Feather v4.28 set" would be exactly
#: the fabricated provenance this repository refuses elsewhere, and a list that
#: is subtly short rejects a valid icon -- a false positive, which is the
#: failure mode that gets a check deleted. So a name outside the exclusions is
#: accepted here and verified by GitHub at publish time.
BRANDING_ICONS_REFUSED = frozenset(
    {
        "coffee",
        "columns",
        "divide-circle",
        "divide-square",
        "divide",
        "frown",
        "hexagon",
        "key",
        "meh",
        "mouse-pointer",
        "smile",
        "tool",
        "x-octagon",
        "x-square",
        "x",
    }
)

ICON_SHAPE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

#: `uses: owner/repo@ref`, with or without a subpath.
USES = re.compile(r"uses:\s*(webdevsamran/api-verity-lab)(/[^@\s]+)?@([^\s`'\"]+)")

NL = chr(10)


def action() -> dict[str, Any]:
    return yaml.safe_load(ACTION.read_text(encoding="utf-8"))


def project_version() -> str:
    return str(tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["version"])


def major_tag(version: str | None = None) -> str:
    """The moving tag consumers pin, derived rather than written down.

    `release.yml` moves `v<major>` to each release, so this is the one
    reference that keeps working. Deriving it from the version means a 1.0
    release changes the documentation by changing `pyproject.toml`, instead of
    leaving `@v0` in four files for somebody to find.
    """
    return "v" + (version or project_version()).split(".", 1)[0]


MARK_OPEN = "<!-- generated:action -->"
MARK_CLOSE = "<!-- /generated:action -->"


def _cell(value: object) -> str:
    """One table cell: folded onto a line, with pipes escaped."""
    return " ".join(str(value).split()).replace("|", chr(92) + "|")


def _default(spec: dict[str, Any]) -> str:
    raw = spec.get("default", "")
    if raw == "" or raw is None:
        return "_(empty)_"
    return "`" + _cell(raw) + "`"


def render() -> str:
    """The reference half of the page, from `action.yml` itself.

    Eleven inputs and five outputs are the whole contract a consumer has with
    this action, and they are what a Marketplace listing renders. Typed by hand
    they would be right on the day they were typed.
    """
    meta = action()
    tag = major_tag()
    lines = [
        MARK_OPEN,
        "",
        f"`{meta['name']}` — {_cell(meta['description'])}",
        "",
        "```yaml",
        "- uses: actions/checkout@v5",
        "  with: { fetch-depth: 0 }   # the diff needs the base revision",
        f"- uses: webdevsamran/api-verity-lab@{tag}",
        "```",
        "",
        "## Inputs",
        "",
        "| Input | Default | What it does |",
        "|---|---|---|",
    ]
    for name, spec in (meta.get("inputs") or {}).items():
        lines.append(f"| `{name}` | {_default(spec)} | {_cell(spec['description'])} |")

    lines += [
        "",
        "## Outputs",
        "",
        "| Output | What it carries |",
        "|---|---|",
    ]
    for name, spec in (meta.get("outputs") or {}).items():
        lines.append(f"| `{name}` | {_cell(spec['description'])} |")

    lines += [
        "",
        f"Branding for the Marketplace listing: `{meta['branding']['icon']}` on "
        f"`{meta['branding']['color']}`.",
        "",
        MARK_CLOSE,
        "",
    ]
    return NL.join(lines)


def page() -> str:
    """The whole page: hand-written prose, generated reference."""
    tag = major_tag()
    header = [
        "# The GitHub Action",
        "",
        "`action.yml` at the root of this repository is a composite action, and it is",
        "the thing GitHub offers to publish to the Marketplace.",
        "",
        "## Pin the major tag",
        "",
        f"`{tag}` moves to each release, so this is the reference to use:",
        "",
        "```yaml",
        f"- uses: webdevsamran/api-verity-lab@{tag}",
        "```",
        "",
        f"`release.yml` moves `{tag}` after it creates the release, and",
        "`scripts/check_action_metadata.py --check` holds every documented `uses:` line",
        "to the major in `pyproject.toml` — so the tag the docs name and the tag the",
        "release creates cannot disagree.",
        "",
        "Pin the exact release instead — `@v0.3.0` — if you would rather take upgrades",
        "deliberately. Pin a commit SHA if your policy requires it; `.github/workflows`",
        "in this repository pins every third-party action that way.",
        "",
        "## An action, not the reusable workflow",
        "",
        "Both exist and they are not interchangeable:",
        "",
        "| | What you get |",
        "|---|---|",
        f"| `uses: webdevsamran/api-verity-lab@{tag}` | A **step** inside a job you own: your runner, your matrix, your checkout, your steps before and after. |",
        f"| `uses: webdevsamran/api-verity-lab/.github/workflows/api-verity.yml@{tag}` | A whole **job**. Less to write, and you cannot put your own steps around it. |",
        "",
        "The README advertised the first for a long time while only the second existed,",
        "so anyone who copied the line got `Can't find 'action.yml'`. Both are real now,",
        "and `ci.yml` runs the action on every push to prove it.",
        "",
    ]

    footer = [
        "",
        "## Publishing it to the Marketplace",
        "",
        "Deliberately not automated. Listing software under an account's name is that",
        "account owner's to do, and a workflow with a token that could do it is a",
        "workflow with more access than it needs.",
        "",
        "Everything the listing requires is in the repository and checked on every",
        "build — root `action.yml`, branding GitHub accepts, a description, a",
        "description on every input and output. What is left is three steps in the",
        "web interface:",
        "",
        "1. **Accept the GitHub Marketplace Developer Agreement.** Once, per account.",
        "2. **Cut a release.** Push a `v*` tag; `release.yml` builds it, creates the",
        f"   release, and moves `{tag}`.",
        "3. **On that release, tick _Publish this Action to the GitHub Marketplace_**,",
        "   then choose a primary and secondary category. *Continuous integration* and",
        "   *Code quality* are the ones that fit.",
        "",
        "GitHub validates the metadata at that point and refuses the listing if any of",
        "it is wrong. That check runs after the tag exists, which is the worst moment",
        "to discover a typo in a colour name — which is why",
        "`scripts/check_action_metadata.py` runs first.",
        "",
        "Two things it cannot check from here, stated rather than implied:",
        "",
        "- **The name must be unique across the Marketplace**, and must not collide",
        "  with an existing GitHub account name. Only GitHub knows that, at publish",
        "  time.",
        "- **The icon must be a Feather icon GitHub accepts.** The colours are eight",
        "  values and the refused icons are a published list, so both are checked. The",
        "  ~280 accepted icon names are not vendored here: writing them from memory and",
        "  calling them the Feather set would be provenance this repository does not",
        "  have, and a list that is subtly short rejects a valid icon.",
        "",
    ]
    return NL.join(header) + render() + NL.join(footer)


def write() -> None:
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(front_matter("github-action.md") + page(), encoding="utf-8", newline=NL)


def marketplace_problems(meta: dict[str, Any]) -> list[str]:
    """What would stop GitHub accepting a listing, or make it useless."""
    found: list[str] = []

    for field in ("name", "description"):
        value = str(meta.get(field) or "").strip()
        if not value:
            found.append(f"action.yml has no `{field}`; the Marketplace requires it")

    description = " ".join(str(meta.get("description") or "").split())
    if description and len(description) < 30:
        found.append(
            f"the description is {len(description)} characters -- it is the one line a "
            f"reader sees in a Marketplace search result"
        )

    branding = meta.get("branding")
    if not isinstance(branding, dict):
        found.append(
            "action.yml has no `branding` block; GitHub refuses a Marketplace "
            "listing without an icon and a colour"
        )
        return found

    color = str(branding.get("color") or "")
    if color not in BRANDING_COLORS:
        found.append(
            f"branding.color is {color!r}; GitHub accepts only {', '.join(sorted(BRANDING_COLORS))}"
        )

    icon = str(branding.get("icon") or "")
    if not icon:
        found.append("branding.icon is empty")
    elif not ICON_SHAPE.match(icon):
        found.append(f"branding.icon {icon!r} is not a lower-case Feather icon name")
    elif icon in BRANDING_ICONS_REFUSED:
        found.append(f"branding.icon {icon!r} is on GitHub's list of icons it refuses")

    return found


def surface_problems(meta: dict[str, Any]) -> list[str]:
    """Inputs and outputs are what the listing renders. Undescribed ones read
    as an unfinished action to the only person who has not read the source."""
    found: list[str] = []
    for section in ("inputs", "outputs"):
        for name, spec in (meta.get(section) or {}).items():
            if not isinstance(spec, dict) or not str(spec.get("description") or "").strip():
                found.append(f"{section}.{name} has no description")
    return found


def reference_problems(expected: str) -> list[str]:
    """Every documented `uses:` names a ref that `release.yml` maintains."""
    found: list[str] = []
    for name in DOCUMENTED_IN:
        path = ROOT / name
        if not path.is_file():
            continue
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            match = USES.search(line)
            if not match:
                continue
            ref = match.group(3)
            if ref != expected:
                found.append(
                    f"{name}:{line_number} tells a reader to use `@{ref}`, but the moving "
                    f"major tag for version {project_version()} is `@{expected}`"
                )
    return found


def problems() -> list[str]:
    if not ACTION.is_file():
        return [
            "there is no action.yml in the repository root; GitHub reads a "
            "Marketplace action from there and nowhere else"
        ]
    meta = action()
    expected = major_tag()
    found = marketplace_problems(meta) + surface_problems(meta) + reference_problems(expected)

    rendered = front_matter("github-action.md") + page()
    if not PAGE.is_file():
        found.append("docs/github-action.md does not exist; run scripts/check_action_metadata.py")
    elif PAGE.read_text(encoding="utf-8") != rendered:
        found.append(
            "docs/github-action.md no longer matches action.yml; run "
            "scripts/check_action_metadata.py"
        )
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Hold action.yml to what publishing requires.")
    parser.add_argument("--check", action="store_true", help="exit 1 on any problem")
    args = parser.parse_args(argv)

    if not args.check:
        write()

    found = problems()
    if found:
        print(*(f"error: {problem}" for problem in found), sep=NL, file=sys.stderr)
        return 1

    meta = action()
    inputs = len(meta.get("inputs") or {})
    outputs = len(meta.get("outputs") or {})
    print(
        f"ok     action.yml is publishable: {inputs} inputs, {outputs} outputs, "
        f"branding {meta['branding']['icon']}/{meta['branding']['color']}, "
        f"documented as @{major_tag()}"
    )
    if not args.check:
        print()
        print("Publishing is an owner action and deliberately not automated here:")
        print("  1. Accept the GitHub Marketplace Developer Agreement (once, on the account).")
        print(f"  2. Cut a release. `release.yml` moves the `{major_tag()}` tag to it.")
        print("  3. On the release, tick 'Publish this Action to the GitHub Marketplace'.")
        print("See docs/github-action.md.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
