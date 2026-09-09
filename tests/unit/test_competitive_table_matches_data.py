"""The competitive table must agree with the data it claims to be built from.

`docs/competitive-analysis.md` states its own method: "repository metadata
fetched via the GitHub API on the refresh date". The table used to be typed by
hand, so it could drift from `data/competitor-meta.json` -- and it did, in the
worst possible cell.

The row read `| Optic | - | - | - | - | repo gone (404) |`, and the prose said
"Dredd/Optic -- archived/gone". Optic's repository is not gone: `opticdev/optic`
is archived and public with 1,534 stars. The 404 came from this repository's
own fetcher asking for `useoptic/optic`, which does not exist; `gh_json`
swallowed the error into `None`, the caller wrote it into the artifact, and the
document transcribed a tool failure as a fact about a competitor.

That is not a cosmetic error. An archived incumbent with 1,534 stars in exactly
this project's domain is the most interesting fact in the file, and the table
said it had vanished.

The table is now rendered by `scripts/generate_competitive_table.py`, so the
strongest available assertion is the whole-document one: the committed prose
must equal what the generator produces from the committed data. That subsumes
every per-cell check and, unlike the per-cell version these tests used to
perform, it cannot skip a row.

It could, before. The old comparison mapped a row to a data entry with
`label.split()[0].lower().strip("()")` against the repository basename, then
`continue`d when the lookup missed, deferring to "the count test" -- which did
not exist in this module. "Pact (pact-js)" keyed to `pact` against a basename of
`pact-js`, and "GraphQL Inspector" keyed to `graphql` against
`graphql-inspector`, so two of the fourteen rows were never checked at all. A
third hole sat in the licence assertion, which was guarded by `if want_lic`, so
a null licence let the table print anything.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent.parent
_DOC = _ROOT / "docs" / "competitive-analysis.md"
_DATA = _ROOT / "data" / "competitor-meta.json"
_CURATED = _ROOT / "data" / "competitive-capabilities.json"


def _generator() -> Any:
    """Import scripts/generate_competitive_table.py, which is not a package."""
    path = _ROOT / "scripts" / "generate_competitive_table.py"
    spec = importlib.util.spec_from_file_location("generate_competitive_table", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _meta() -> dict:
    return json.loads(_DATA.read_text(encoding="utf-8"))


def test_the_document_is_what_the_generator_produces() -> None:
    """The whole-file assertion the three "it is generated" claims promised."""
    gen = _generator()
    current = _DOC.read_text(encoding="utf-8")
    expected = gen.splice(current, _meta())
    assert current == expected, (
        "docs/competitive-analysis.md disagrees with data/competitor-meta.json. "
        "Run: python scripts/generate_competitive_table.py"
    )


def test_every_fetched_competitor_appears_in_the_table() -> None:
    """No row may be silently absent, which the old per-cell mapping allowed."""
    gen = _generator()
    table = gen.render_landscape(_meta())
    missing = [
        label
        for repo, label in gen.LABELS.items()
        if repo in _meta()["repos"] and f"| {label} |" not in table
    ]
    assert not missing, f"fetched competitors missing from the rendered table: {missing}"


def test_every_fetched_competitor_has_a_table_label() -> None:
    gen = _generator()
    unlabelled = sorted(set(_meta()["repos"]) - set(gen.LABELS))
    assert not unlabelled, (
        f"fetched repos with no LABELS entry: {unlabelled}. The generator raises on these, "
        "but failing here names them without a traceback."
    )


def test_no_competitor_is_recorded_as_a_failed_lookup() -> None:
    """A fetch that failed must never reach the artifact as a finding.

    The old `gh_json` returned None on any error and the caller stored
    `{"error": "repo-not-found-or-error"}`. That string is what became
    "repo gone (404)" in the published table.
    """
    blob = json.dumps(_meta())
    assert "repo-not-found-or-error" not in blob, (
        "competitor-meta.json contains a failed lookup recorded as data; "
        "fetch_competitor_meta.py should have raised instead"
    )
    for key, entry in _meta()["repos"].items():
        assert entry.get("stars") is not None, f"{key} has no star count -- did the fetch fail?"


def test_curated_entries_name_a_repository_that_was_actually_fetched() -> None:
    """The join between the two data files must resolve.

    `competitive-capabilities.json` recorded Optic's repository as
    `useoptic/optic` -- the name that never existed and produced the 404. A
    curated entry pointing at a repository no fetch covers is how a hand-written
    claim ends up with no evidence behind it while looking like it has some.
    """
    fetched = set(_meta()["repos"])
    curated = json.loads(_CURATED.read_text(encoding="utf-8"))["competitors"]
    dangling = {
        c["name"]: c.get("github_repo")
        for c in curated
        if c.get("github_repo") and c["github_repo"] not in fetched
    }
    assert not dangling, (
        f"curated competitors naming a repository absent from competitor-meta.json: {dangling}. "
        "Either the name is wrong or the repo is missing from the fetch list."
    )


def test_optic_is_recorded_as_archived_not_missing() -> None:
    """The specific regression, pinned.

    Optic is the most consequential entry in this file: an archived project in
    exactly this domain. Recording it as absent both misstates the fact and
    discards the signal.
    """
    entry = _meta()["repos"].get("opticdev/optic")
    assert entry is not None, "opticdev/optic dropped from the competitor set"
    assert entry["archived"] is True, "Optic is archived; the data says otherwise"
    assert entry["stars"] > 1000, f"Optic star count looks wrong: {entry['stars']}"
    # Scoped to the table, not the whole file: the prose below it explains the
    # former error and legitimately quotes the old wording. Asserting over the
    # entire document flagged that explanation as the defect it documents.
    text = _DOC.read_text(encoding="utf-8")
    table = text[text.index("| Tool | License |") :].split("\n\n", 1)[0]
    assert "repo gone" not in table, 'the table still claims a competitor\'s "repo gone"'
    assert "| Optic | MIT |" in table, "the Optic row no longer carries its real metadata"


def test_no_curated_note_claims_optic_vanished() -> None:
    """The inverse of the above, in the file that defines the evidence vocabulary.

    `competitive-capabilities.json` carried "the Optic OSS project is no longer
    published under that org (verified live)" -- a false inference wearing a
    VERIFIED label, in the file whose job is to say how claims are evidenced.
    """
    curated = json.loads(_CURATED.read_text(encoding="utf-8"))
    optic = next(c for c in curated["competitors"] if c["name"] == "Optic")
    assert optic["github_repo"] == "opticdev/optic"
    for weakness in optic["weaknesses_or_tradeoffs"]:
        assert "404" not in weakness, (
            f"Optic weakness still cites the fetcher's own 404 as a fact: {weakness!r}"
        )
    for item in optic["evidence"]:
        assert "useoptic" not in item["claim"], (
            f"Optic evidence still asserts something about useoptic/optic: {item['claim']!r}"
        )


def test_the_snapshot_date_matches_the_data() -> None:
    """A table headed with one date and built from another is a false citation."""
    date = _meta()["fetched_utc"][:10]
    text = _DOC.read_text(encoding="utf-8")
    assert f"verified {date}" in text, (
        f"the landscape heading does not name the data's fetch date ({date})"
    )


def test_the_document_does_not_cite_a_second_conflicting_date() -> None:
    """The provenance line and the table heading drifted 17 days apart.

    Line 3 read "Generated: 2026-08-23" while the heading below it read
    "verified 2026-09-09", both describing the same fetched artifact. Both are
    now rendered from `fetched_utc`, so the only date in the generated blocks is
    the one the data carries.
    """
    gen = _generator()
    meta = _meta()
    date = gen.fetch_date(meta)
    text = _DOC.read_text(encoding="utf-8")
    # Only the two provenance blocks. The landscape table legitimately carries a
    # push date and a release date per project; those are data, not citations of
    # when the fetch ran.
    for name in ("provenance", "method"):
        open_mark = gen.MARK_OPEN.format(name=name)
        close_mark = gen.MARK_CLOSE.format(name=name)
        block = text[text.index(open_mark) : text.index(close_mark)]
        stale = [found for found in re.findall(r"\d{4}-\d{2}-\d{2}", block) if found != date]
        assert not stale, f"generated block {name!r} cites date(s) other than {date}: {stale}"
