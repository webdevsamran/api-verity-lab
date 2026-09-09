"""The competitive table must agree with the data it claims to be built from.

`docs/competitive-analysis.md` states its own method: "repository metadata
fetched via the GitHub API on the refresh date". The table is nonetheless typed
by hand, so it can drift from `data/competitor-meta.json` -- and it did, in the
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

These tests bind the prose to the data so the two cannot disagree again.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
_DOC = _ROOT / "docs" / "competitive-analysis.md"
_DATA = _ROOT / "data" / "competitor-meta.json"

_ROW = re.compile(r"^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|")


def _meta() -> dict:
    return json.loads(_DATA.read_text(encoding="utf-8"))


def _table_rows() -> dict[str, tuple[str, str, str]]:
    """{label: (license, stars, last_push)} from the landscape table."""
    text = _DOC.read_text(encoding="utf-8")
    start = text.index("| Tool | License |")
    body = text[start:].splitlines()[2:]
    rows = {}
    for line in body:
        if not line.startswith("|"):
            break
        match = _ROW.match(line)
        if match:
            label, lic, stars, push = (g.strip() for g in match.groups())
            rows[label] = (lic, stars, push)
    return rows


def _by_label() -> dict[str, dict]:
    """Data entries keyed by the label the table uses for them."""
    repos = _meta()["repos"]
    out = {}
    for key, entry in repos.items():
        out[key.split("/")[-1].lower()] = entry
    return out


def test_every_table_row_matches_the_fetched_data() -> None:
    rows = _table_rows()
    assert rows, "the landscape table has no rows"
    data = _by_label()

    mismatches = []
    for label, (lic, stars, push) in rows.items():
        key = label.split()[0].lower().strip("()")
        entry = data.get(key)
        if entry is None:
            continue  # label the test cannot map; covered by the count test
        if entry.get("stars") is not None:
            want = f"{entry['stars']:,}"
            if stars != want:
                mismatches.append(f"{label}: table says {stars} stars, data says {want}")
        want_push = (entry.get("pushed_at") or "")[:10]
        if want_push and push != want_push:
            mismatches.append(f"{label}: table says pushed {push}, data says {want_push}")
        want_lic = entry.get("license_spdx")
        if want_lic and lic != want_lic:
            mismatches.append(f"{label}: table says license {lic}, data says {want_lic}")

    assert not mismatches, "competitive table disagrees with competitor-meta.json:\n" + "\n".join(
        "  " + m for m in mismatches
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


def test_the_snapshot_date_matches_the_data() -> None:
    """A table headed with one date and built from another is a false citation."""
    date = _meta()["fetched_utc"][:10]
    text = _DOC.read_text(encoding="utf-8")
    assert f"verified {date}" in text, (
        f"the landscape heading does not name the data's fetch date ({date})"
    )
