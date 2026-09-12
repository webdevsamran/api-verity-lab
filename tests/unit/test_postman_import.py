"""A Postman collection as a source for a draft contract, and what it is not.

The most common answer to "run the contract gate on this API" is "we have no
contract". The second most common is "we have a Postman collection" -- which
for many teams is the only written description of their API that exists.

Two things are guarded here beyond the parsing.

**A collection is not traffic.** A HAR is a recording: those requests happened,
in that order, at those times. A collection is a set of requests somebody
saved, and a saved response is an example somebody pasted -- possibly years
ago, possibly by hand. Every threshold `infer` applies ("present in every
sample") means something weaker about examples than about observations, so the
draft says which it came from, and the word in its first sentence is *saved*
rather than *recorded*.

**Nothing is dropped quietly.** A draft missing a third of an API because those
requests used form bodies looks like an API with a third fewer endpoints. Every
construct this does not read is named, with the request it was on.

Shapes asserted here come from the Postman Collection Format v2.1.0 schema,
read 2026-09-10 at schema.postman.com.
"""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest

from apiverity.cli.main import main
from apiverity.traffic import postman

_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE = _ROOT / "fixtures" / "traffic" / "orders.postman_collection.json"


@pytest.fixture(scope="module")
def imported() -> postman.Import:
    return postman.read(str(_FIXTURE))


def _urls(imported: postman.Import) -> list[str]:
    return [entry["url"] for entry in imported.entries]


def _run(argv: list[str]) -> tuple[int, dict[str, Any]]:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(io.StringIO()):
        code = main(argv)
    text = buffer.getvalue()
    return code, (json.loads(text) if text.strip().startswith("{") else {})


# ------------------------------------------------------------------ detection


def test_a_collection_is_recognised_by_its_schema_url() -> None:
    document = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    assert postman.is_collection(document)


def test_a_hand_edited_collection_with_no_schema_url_is_still_one() -> None:
    """`info` and `item` are the two required members. A file with both and no
    schema URL is almost certainly a collection somebody edited by hand."""
    assert postman.is_collection({"info": {"name": "x"}, "item": []})


def test_a_har_is_not_a_collection() -> None:
    """Both are `.json`, and a HAR named `collection.json` is a file somebody
    will hand this."""
    assert not postman.is_collection({"log": {"entries": []}})
    assert not postman.is_collection({"info": "not an object"})
    assert not postman.is_collection([])


# -------------------------------------------------------------------- reading


def test_nested_folders_are_walked_to_any_depth(imported: postman.Import) -> None:
    """Forty requests in six folders is the normal shape. Flattening only the
    top level would draft a contract from whichever requests happened to be at
    the root -- often none of them."""
    assert any("/orders" in url for url in _urls(imported))
    assert any("/admin/exports" in url for url in _urls(imported))


def test_the_collection_variable_is_substituted(imported: postman.Import) -> None:
    # The host, parsed. `startswith` on a URL is the shape that reads
    # `https://orders.example.com.evil.invalid/` as a match, and a test that
    # models a URL check loosely is where the loose version gets copied from.
    assert all(urlsplit(url).netloc == "orders.example.com" for url in _urls(imported))


def test_an_unresolved_variable_is_left_alone_and_reported(imported: postman.Import) -> None:
    """Guessing a value would draft an operation at a path nobody serves;
    dropping the request would quietly shrink the API."""
    assert any("{{userId}}" in url for url in _urls(imported))
    assert imported.unresolved
    assert "{{userId}}" in imported.unresolved[0]


def test_both_url_forms_are_read(imported: postman.Import) -> None:
    """The schema allows a bare string and an object. `Get one order` uses the
    first; `Export orders` uses the second with a host array and no `raw`."""
    assert "https://orders.example.com/orders/ORD-1" in _urls(imported)
    assert "https://orders.example.com/admin/exports" in _urls(imported)


def test_a_disabled_query_parameter_is_not_carried(imported: postman.Import) -> None:
    """It is one somebody deliberately turned off. Declaring it would put a
    parameter in the draft that the collection says not to send."""
    listing = next(e for e in imported.entries if e["url"].endswith("?status=open&page=1"))
    assert set(listing["query"]) == {"status", "page"}


def test_a_disabled_header_is_not_carried(imported: postman.Import) -> None:
    listing = next(e for e in imported.entries if "status=open" in e["url"])
    assert "X-Debug" not in listing["request_headers"]
    assert listing["request_headers"]["Accept"] == "application/json"


def test_a_raw_json_body_is_parsed(imported: postman.Import) -> None:
    placed = next(
        e for e in imported.entries if e["method"] == "POST" and e["url"].endswith("/orders")
    )
    assert placed["request_body"] == {"sku": "ABC-1", "quantity": 2}


def test_a_saved_response_becomes_the_response_body(imported: postman.Import) -> None:
    listing = next(e for e in imported.entries if "status=open" in e["url"])
    assert listing["status"] == 200
    assert listing["response_body"]["items"][0]["id"] == "ORD-1"
    assert listing["response_mime"] == "application/json"


def test_a_request_with_no_saved_response_says_so(imported: postman.Import) -> None:
    """ "Nothing was returned" and "nobody saved one" are different facts, and
    `import_har` already draws that distinction the same way."""
    export = next(e for e in imported.entries if e["url"].endswith("/admin/exports"))
    assert export["response_body"] is None
    assert "saved no response" in export["response_body_dropped"]
    assert imported.without_response == 3


def test_no_timestamps_are_invented(imported: postman.Import) -> None:
    """A collection records none, and a fabricated one would put a window in
    the draft's own description that nobody observed."""
    assert all(entry["started_at"] is None for entry in imported.entries)
    assert all(entry["elapsed_ms"] is None for entry in imported.entries)


def test_the_entries_are_the_shape_import_har_produces() -> None:
    """The point of the whole module: one inference engine, one set of
    thresholds. Two would be two sets of decisions about when a field is
    required, and they would disagree."""
    from apiverity.traffic.redact import RedactionConfig, import_har

    har = import_har(str(_ROOT / "fixtures/traffic/crud.har"), RedactionConfig())
    collection = postman.read(str(_FIXTURE))
    assert set(collection.entries[0]) == set(har[0])


# ------------------------------------------------------- what is not read


def test_a_form_body_is_named_rather_than_dropped(imported: postman.Import) -> None:
    """A draft missing a third of an API because those requests used form
    bodies looks like an API with a third fewer endpoints."""
    assert any("formdata" in note for note in imported.skipped)
    assert any("Upload a manifest" in note for note in imported.skipped)


def test_the_request_itself_survives_a_body_mode_that_is_not_read(
    imported: postman.Import,
) -> None:
    """The endpoint is real even when its payload cannot be modelled. Dropping
    the request would remove an operation that exists."""
    assert any(url.endswith("/admin/manifests") for url in _urls(imported))


@pytest.mark.parametrize("mode", ["formdata", "file", "graphql"])
def test_the_modes_this_does_not_read_are_the_documented_ones(mode: str) -> None:
    assert mode not in postman.READABLE_BODY_MODES


def test_a_collection_with_no_requests_reads_as_empty_rather_than_raising() -> None:
    assert postman.convert({"info": {"name": "x"}, "item": []}).entries == []


def test_a_file_that_is_not_a_collection_is_refused_by_name(tmp_path: Path) -> None:
    path = tmp_path / "nope.json"
    path.write_text('{"log": {"entries": []}}', encoding="utf-8")
    with pytest.raises(ValueError, match="not a Postman collection"):
        postman.read(str(path))


# ---------------------------------------------------------------- the draft


def test_infer_accepts_a_collection_and_says_where_it_came_from(tmp_path: Path) -> None:
    out = tmp_path / "draft.yaml"
    code, payload = _run(["--no-config", "infer", str(_FIXTURE), "-o", str(out), "--json"])
    assert code == 0
    assert payload["provenance"]["source"] == "postman-collection"
    assert payload["provenance"]["collection"] == "Orders API"
    assert out.is_file()


def test_the_draft_says_saved_rather_than_recorded(tmp_path: Path) -> None:
    """The sentence a reader is most likely to quote. "Recorded" is a claim
    about a HAR -- those requests happened. These were saved by somebody,
    possibly years ago and possibly by hand."""
    out = tmp_path / "draft.yaml"
    _run(["--no-config", "infer", str(_FIXTURE), "-o", str(out), "--json"])
    text = out.read_text(encoding="utf-8")
    assert "saved request(s)" in text
    assert "recorded request(s)" not in text


def test_the_draft_carries_the_collection_note(tmp_path: Path) -> None:
    out = tmp_path / "draft.yaml"
    _run(["--no-config", "infer", str(_FIXTURE), "-o", str(out), "--json"])
    text = out.read_text(encoding="utf-8")
    assert "not traffic anybody observed" in text
    assert "x-apiverity-source: postman-collection" in text


def test_a_har_still_says_recorded(tmp_path: Path) -> None:
    """The other half of the same assertion: the noun follows the source."""
    out = tmp_path / "draft.yaml"
    _run(
        [
            "--no-config",
            "infer",
            str(_ROOT / "fixtures/traffic/crud.har"),
            "-o",
            str(out),
            "--json",
        ]
    )
    assert "recorded request(s)" in out.read_text(encoding="utf-8")


def test_what_was_skipped_reaches_the_artifact(tmp_path: Path) -> None:
    _code, payload = _run(["--no-config", "infer", str(_FIXTURE), "--json"])
    assert payload["provenance"]["skipped"]
    assert payload["provenance"]["unresolved_variables"]
    assert payload["provenance"]["requests_without_a_saved_response"] == 3
