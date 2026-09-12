"""Every docs page publishes its own meta description, or this fails.

A MkDocs page with no `description:` front matter inherits `site_description`
from `mkdocs.yml`. That is invisible in the rendered site -- the page looks
finished -- and visible only in a search result, months later, as ninety-seven
results carrying one identical sentence. A search engine reads that as
duplication and substitutes an excerpt of its own choosing, which is how a
documentation site ends up represented by whatever three lines happened to sit
near the top of each page.

So descriptions live in `scripts/page_meta.py`, one per page, and this holds
the committed pages to that table:

* every page under `docs/` has front matter, and its description is the one
  `page_meta` records for it;
* `page_meta` has no entry for a page that no longer exists;
* no two pages share a description, and none is the site description;
* each is long enough to say something and short enough not to be truncated.

    python scripts/check_page_descriptions.py           # write the missing ones
    python scripts/check_page_descriptions.py --check   # verify, exit 1 on drift

Without `--check` it writes, which is normally only needed for a page a person
just added: twenty-seven pages under `docs/` are generated, and their
generators import `front_matter` from the same table, so those already carry
the right block the moment they are rendered.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from page_meta import DESCRIPTIONS, front_matter, strip_front_matter

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
MKDOCS = ROOT / "mkdocs.yml"

#: Shorter than this says nothing a reader can act on; longer is cut off in
#: the result it was written for. Both ends are held, because a description
#: nobody reads to the end is the same defect as no description.
MIN_LENGTH = 70
MAX_LENGTH = 165

NL = chr(10)


def pages() -> list[str]:
    """Every page under `docs/`, as a docs-relative POSIX path."""
    return sorted(p.relative_to(DOCS).as_posix() for p in DOCS.rglob("*.md"))


def declared(text: str) -> str | None:
    """The `description:` a page declares, or `None` if it declares none.

    Deliberately a small hand-rolled reader rather than a YAML parse: this runs
    in the lint job, the front matter it reads is written by `front_matter`,
    and a dependency added for four lines is a dependency added for four lines.
    """
    if not text.startswith("---" + NL):
        return None
    end = text.find(NL + "---" + NL, 3)
    if end == -1:
        return None
    block = text[4 : end + 1].splitlines()
    for index, line in enumerate(block):
        if not line.startswith("description:"):
            continue
        inline = line[len("description:") :].strip()
        if inline and inline not in (">", ">-", "|", "|-"):
            return inline.strip("'\"")
        folded = [
            following.strip()
            for following in block[index + 1 :]
            if following.startswith(("  ", "\t")) and following.strip()
        ]
        return " ".join(folded) if folded else None
    return None


def site_description() -> str:
    """The site-wide description, so no page can silently repeat it."""
    text = MKDOCS.read_text(encoding="utf-8")
    marker = "site_description: >" + NL
    if marker not in text:
        return ""
    rest = text.split(marker, 1)[1].splitlines()
    folded = []
    for line in rest:
        if not line.startswith("  "):
            break
        folded.append(line.strip())
    return " ".join(folded)


def problems() -> list[str]:
    """Everything wrong, rather than the first thing wrong.

    A checker that stops at the first failure turns one run into six, and this
    one is most often run after adding several pages at once.
    """
    found: list[str] = []
    committed = pages()

    for orphan in sorted(set(DESCRIPTIONS) - set(committed)):
        found.append(
            f"scripts/page_meta.py describes docs/{orphan}, which does not exist -- "
            f"remove the entry, or restore the page"
        )

    site = site_description()
    seen: dict[str, str] = {}

    for page in committed:
        expected = DESCRIPTIONS.get(page)
        if expected is None:
            found.append(
                f"docs/{page} has no entry in scripts/page_meta.py, so it would publish "
                f"the site description instead of its own"
            )
            continue

        length = len(expected)
        if length < MIN_LENGTH:
            found.append(f"docs/{page}: description is {length} chars, under {MIN_LENGTH}")
        elif length > MAX_LENGTH:
            found.append(
                f"docs/{page}: description is {length} chars, over {MAX_LENGTH} and will "
                f"be truncated in a search result"
            )

        if site and expected.strip() == site.strip():
            found.append(f"docs/{page} repeats the site description rather than describing itself")

        if expected in seen:
            found.append(f"docs/{page} and docs/{seen[expected]} share one description")
        else:
            seen[expected] = page

        actual = declared((DOCS / page).read_text(encoding="utf-8"))
        if actual is None:
            found.append(
                f"docs/{page} has no description front matter; run "
                f"scripts/check_page_descriptions.py"
            )
        elif actual != expected:
            found.append(
                f"docs/{page} declares a description that is not the one in "
                f"scripts/page_meta.py; run scripts/check_page_descriptions.py"
            )

    return found


def write() -> None:
    """Put the recorded front matter on every page that is missing it."""
    written = 0
    for page in pages():
        if page not in DESCRIPTIONS:
            continue
        path = DOCS / page
        text = path.read_text(encoding="utf-8")
        if declared(text) == DESCRIPTIONS[page]:
            continue
        path.write_text(front_matter(page) + strip_front_matter(text), encoding="utf-8", newline=NL)
        written += 1
    print(f"wrote  front matter into {written} page(s)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Hold every docs page to its meta description.")
    parser.add_argument("--check", action="store_true", help="verify only; exit 1 on any problem")
    args = parser.parse_args(argv)

    found = problems()
    if not args.check:
        if found:
            write()
            found = problems()
        if found:
            print(*(f"error: {problem}" for problem in found), sep=NL, file=sys.stderr)
            return 1
        print(f"ok     {len(pages())} pages, each with its own meta description")
        return 0

    if found:
        print(*(f"error: {problem}" for problem in found), sep=NL, file=sys.stderr)
        return 1
    print(f"ok     {len(pages())} pages, each with its own meta description")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
