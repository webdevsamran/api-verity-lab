"""Assert the built docs site actually contains its documents.

`mkdocs build --strict` passing does not mean the site has content in it. This
project's site was green while publishing empty pages: every one of its nine
`--8<--` snippet includes used a `../` path, which pymdownx refuses because it
escapes `base_path`, and `check_paths: false` made that refusal silent. The
Architecture page shipped with 68 words of navigation chrome and none of
ARCHITECTURE.md.

A build that succeeds while producing nothing is the same defect this
repository has fixed twice elsewhere -- a CI step named for a check it never
performed. So the site is checked for content, not just for exit status.

    python scripts/check_docs_site.py            # build, then verify
    python scripts/check_docs_site.py --site DIR # verify an existing build
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: A page carrying only navigation chrome lands around 60-70 words.
#:
#: Two thresholds rather than one, because a flat number is the wrong
#: instrument: api-verity-lab has legitimately terse pages (docs/sdk.md is 18
#: lines, mostly a code block) that a single 120-word bar reported as broken.
#: The defect being guarded is an *include* resolving to nothing, so
#: include-backed pages get the strict bar and everything else only has to be
#: non-blank.
MIN_WORDS_INCLUDED = 120
MIN_WORDS_ANY = 40

TAG = re.compile(r"<[^>]+>")


def words_in(html: str) -> int:
    body = html.split("<article", 1)[-1].split("</article>", 1)[0]
    return len(TAG.sub(" ", body).split())


def build(into: Path) -> None:
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell, no user input
        [sys.executable, "-m", "mkdocs", "build", "--strict", "--site-dir", str(into)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(result.stderr or result.stdout, file=sys.stderr)
        raise SystemExit("mkdocs build failed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", type=Path, default=None)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        site = args.site or Path(tmp) / "site"
        if args.site is None:
            build(site)

        pages = sorted(site.rglob("index.html"))
        if not pages:
            print("no pages were built", file=sys.stderr)
            return 1

        # Which source pages are built from a snippet include.
        included = {
            path.stem
            for path in (ROOT / "docs").rglob("*.md")
            if "--8<--" in path.read_text(encoding="utf-8", errors="replace")
        }

        thin: list[tuple[str, int, str]] = []
        for page in pages:
            name = page.parent.relative_to(site).as_posix() or "index"
            if name.startswith(("assets", "search")):
                continue
            count = words_in(page.read_text(encoding="utf-8", errors="replace"))
            stem = name.rsplit("/", 1)[-1] or "index"
            is_included = stem in included
            floor = MIN_WORDS_INCLUDED if is_included else MIN_WORDS_ANY
            if count < floor:
                why = "include resolved to nothing" if is_included else "page is blank"
                thin.append((name, count, why))

        if thin:
            print(
                f"{len(thin)} page(s) built with almost no content -- a snippet "
                "include is probably resolving to nothing:",
                file=sys.stderr,
            )
            for name, count, why in thin:
                print(f"  {name}: {count} words -- {why}", file=sys.stderr)
            return 1

        print(f"ok     {len(pages)} pages built, all carrying real content")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
