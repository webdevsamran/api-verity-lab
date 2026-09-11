"""The repository's description and topics, held against the code.

GitHub keeps these in a settings page. Nothing reviews them, nothing notices
when they go stale, and this repository's had: the description named **three**
protocols while the loader read **seven**, and had said so since AsyncAPI
shipped. Somebody arriving from a search for "asyncapi breaking changes" was
told, by the repository's own card, that it does not do that.

It was not the only place. The README's headline, `mkdocs.yml`'s
`site_description` and `pyproject.toml`'s `description` each carried a
different version of the same sentence, and all three were wrong in different
ways.

    python scripts/check_repo_metadata.py           # print the apply command
    python scripts/check_repo_metadata.py --check   # verify, exit 1 on drift
    python scripts/check_repo_metadata.py --live    # also compare with GitHub

## `--check` never touches the network

It compares `.github/repo-metadata.yml` with the code and with the three other
places that state the protocol list. `--live` additionally asks GitHub what the
repository currently says, which is a question with an answer the maintainer
has to act on rather than a gate that should fail a pull request.

Nothing here writes to GitHub. Repository settings are the maintainer's, and a
script that edited them from CI would be a script with more access than it
needs.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
METADATA = ROOT / ".github" / "repo-metadata.yml"

sys.path.insert(0, str(ROOT))

REPO = "webdevsamran/api-verity-lab"

#: GitHub's own limits, which it enforces by rejecting the edit.
MAX_DESCRIPTION = 350
MAX_TOPICS = 20
TOPIC = re.compile(r"^[a-z0-9][a-z0-9-]{0,48}[a-z0-9]$")

#: How each supported format is named in prose. A list generated from the
#: format *keys* would read "swagger2, wsdl", which is not what anybody calls
#: them -- so the mapping is written down and the completeness is checked.
PROSE = {
    "openapi": "OpenAPI",
    "swagger2": "Swagger 2.0",
    "asyncapi": "AsyncAPI",
    "graphql": "GraphQL",
    "grpc": "gRPC",
    "mcp": "MCP",
    "wsdl": "WSDL",
}

#: Every file that states the protocol list, and how to find the sentence.
#: Four places said four different things, which is three too many.
STATED_IN = (
    ("README.md", "the bold headline"),
    ("mkdocs.yml", "site_description"),
    ("pyproject.toml", "project.description"),
)


def metadata() -> dict:
    import yaml

    return yaml.safe_load(METADATA.read_text(encoding="utf-8"))


def supported() -> list[str]:
    from apiverity.specs.loader import SPEC_FORMATS

    return list(SPEC_FORMATS)


def problems() -> list[str]:
    """Everything wrong, rather than the first thing wrong."""
    found: list[str] = []
    data = metadata()
    formats = supported()

    missing_prose = sorted(set(formats) - set(PROSE))
    if missing_prose:
        found.append(
            f"the loader supports {missing_prose} and this script has no prose name for them"
        )

    description = " ".join(str(data.get("description", "")).split())
    if not description:
        found.append("no description")
    if len(description) > MAX_DESCRIPTION:
        found.append(
            f"description is {len(description)} characters; GitHub allows {MAX_DESCRIPTION}"
        )

    # The point of the file. A description naming three of seven formats is the
    # repository telling a searcher it cannot do the thing they searched for.
    for key in formats:
        name = PROSE.get(key)
        if name and name.lower() not in description.lower():
            found.append(f"the description does not mention {name}, which the loader supports")

    topics = data.get("topics") or []
    if len(topics) > MAX_TOPICS:
        found.append(f"{len(topics)} topics; GitHub allows {MAX_TOPICS}")
    for topic in topics:
        if not TOPIC.match(str(topic)):
            found.append(f"topic {topic!r} is not a valid GitHub topic")
    if len(set(topics)) != len(topics):
        found.append("a topic is listed twice")

    homepage = str(data.get("homepage") or "")
    if not homepage.startswith("https://"):
        found.append("homepage should be the docs site")

    # The other three places that state the same list.
    for name, where in STATED_IN:
        text = (ROOT / name).read_text(encoding="utf-8")
        # Only the leading portion: the protocol list appears in prose further
        # down in README.md, and this is about the one-line claim at the top.
        head = text[:4000]
        for key in formats:
            prose = PROSE.get(key)
            if prose and prose.lower() not in head.lower():
                found.append(f"{name} ({where}) does not mention {prose}")
    return found


def apply_command() -> str:
    data = metadata()
    description = " ".join(str(data["description"]).split())
    topics = " ".join(f"--add-topic {topic}" for topic in data["topics"])
    return (
        f"gh repo edit {REPO} \\\n"
        f"  --description {json.dumps(description)} \\\n"
        f"  --homepage {json.dumps(str(data['homepage']))} \\\n"
        f"  {topics}"
    )


def live() -> list[str]:
    """What GitHub currently says, compared with what this file says."""
    import urllib.request

    data = metadata()
    request = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "apiverity"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            current = json.load(response)
    except OSError as exc:
        return [f"could not ask GitHub: {exc}"]

    differences = []
    wanted = " ".join(str(data["description"]).split())
    if (current.get("description") or "") != wanted:
        differences.append("the description on GitHub differs from this file")
    if (current.get("homepage") or "") != str(data["homepage"]):
        differences.append("the homepage on GitHub differs from this file")
    missing = sorted(set(data["topics"]) - set(current.get("topics") or []))
    if missing:
        differences.append(f"topics not set on GitHub: {missing}")
    return differences


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify against the code, offline")
    parser.add_argument("--live", action="store_true", help="also compare with GitHub")
    args = parser.parse_args(argv)

    found = problems()
    if found:
        for problem in found:
            print(f"error: {problem}", file=sys.stderr)
        return 1

    if args.live:
        differences = live()
        if differences:
            print("the repository on GitHub does not match this file:", file=sys.stderr)
            for difference in differences:
                print(f"  {difference}", file=sys.stderr)
            print("\napply it with:\n", file=sys.stderr)
            print(apply_command(), file=sys.stderr)
            return 1
        print("ok     GitHub matches .github/repo-metadata.yml")
        return 0

    if args.check:
        print(f"ok     repo-metadata.yml names all {len(supported())} supported formats")
        return 0

    print(apply_command())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
