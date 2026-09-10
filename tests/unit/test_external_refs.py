"""Multi-file contracts, which are the normal shape of a real one.

An entry file, a `schemas/` directory beside it, and often a `../../shared/`
tree in a monorepo. Every ref into those produced `SPEC-REF-EXTERNAL` and
resolved to nothing, and the nothing is the part that matters: the schema
behind the ref was *absent from the model*, so the differ compared two absences
and reported no change, and `validate_value` accepted anything at that
position. A warning that a schema could not be read is a much smaller problem
than a diff that says a rewritten contract is unchanged.

So these tests run the whole path rather than asserting that the bundler
populated a dict: parse a real tree of files, then check the model, the diff
and the reported source locations.

Two refusals are tested as carefully as the successes, because a bundler is a
thing that reads files a *document* named rather than files the caller named.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from apiverity.diff.engine import diff_services
from apiverity.rules.breaking import evaluate_breaking
from apiverity.specs.bundle import bundle
from apiverity.specs.loader import detect_and_load

_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE = _ROOT / "fixtures" / "apis" / "multifile" / "openapi.yaml"


def _load(path: Path):
    service, findings, _ = detect_and_load(str(path))
    return service, findings


def _request_schema(service: Any):
    body = service.operations[0].request_body
    assert body is not None
    return next(iter(body.content.values()))


def _tree(root: Path, files: dict[str, Any]) -> Path:
    """Write a small multi-file contract and return its entry document."""
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, str):
            path.write_text(content, encoding="utf-8")
        else:
            path.write_text(yaml.safe_dump(content, sort_keys=False), encoding="utf-8")
    return root / next(iter(files))


def _entry(**paths: Any) -> dict[str, Any]:
    return {
        "openapi": "3.1.0",
        "info": {"title": "T", "version": "1.0.0"},
        "paths": paths,
    }


def _post(schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "post": {
            "operationId": "op",
            "requestBody": {
                "required": True,
                "content": {"application/json": {"schema": schema}},
            },
            "responses": {"200": {"description": "ok"}},
        }
    }


# ------------------------------------------------------- the shipped tree


def test_the_multi_file_fixture_loads_with_no_unresolved_references() -> None:
    _, findings = _load(_FIXTURE)
    rules = {f.rule_id for f in findings}
    assert "SPEC-REF-EXTERNAL" not in rules
    assert "SPEC-REF-UNRESOLVED" not in rules


def test_the_referenced_schema_is_in_the_model_not_merely_unreported() -> None:
    """This is the assertion the old behaviour would fail.

    It did not raise, it did not warn beyond one WARN -- it produced a model
    with an empty schema where the contract declared a shape.
    """
    service, _ = _load(_FIXTURE)
    schema = _request_schema(service)
    assert sorted(schema.properties) == ["customer", "quantity", "sku"]
    assert schema.required == ["sku", "quantity"]
    assert schema.properties["quantity"].minimum == 1


def test_a_reference_inside_an_included_file_resolves_against_that_file() -> None:
    """`../shared/customer.yaml` from `schemas/order.yaml` is two hops.

    Resolving it against the *entry* document instead would read a different
    file, or none -- and either way the result is a schema that does not match
    the contract, arrived at silently.
    """
    service, _ = _load(_FIXTURE)
    customer = _request_schema(service).properties["customer"]
    assert sorted(customer.properties) == ["id", "tier"]
    assert customer.properties["tier"].enum == ["free", "pro", "enterprise"]


def test_a_finding_names_the_file_the_schema_actually_lives_in() -> None:
    """Otherwise every location points at the entry document.

    A reviewer told a problem is at `openapi.yaml:0` goes looking for a line
    that is not there, which is worse than no location at all.
    """
    service, _ = _load(_FIXTURE)
    customer = _request_schema(service).properties["customer"]
    assert customer.source_location is not None
    assert customer.source_location.file == "shared/customer.yaml"
    assert customer.source_location.line > 0


def test_a_whole_file_reference_with_no_pointer_works() -> None:
    service, _ = _load(_FIXTURE)
    rejected = next(r for r in service.operations[0].responses if r.status == "422")
    schema = next(iter(rejected.content.values()))
    assert sorted(schema.properties) == ["code", "message"]


def test_a_change_in_an_included_file_is_a_breaking_change(tmp_path: Path) -> None:
    """The point of the whole exercise.

    Editing `schemas/order.yaml` changes the contract. Before bundling, the
    differ saw two empty schemas and called a removed required field no change
    at all.
    """
    before = _tree(
        tmp_path / "before",
        {
            "openapi.yaml": _entry(**{"/x": _post({"$ref": "./s.yaml#/X"})}),
            "s.yaml": {
                "X": {
                    "type": "object",
                    "required": ["a", "b"],
                    "properties": {
                        "a": {"type": "string"},
                        "b": {"type": "string"},
                    },
                }
            },
        },
    )
    after = _tree(
        tmp_path / "after",
        {
            "openapi.yaml": _entry(**{"/x": _post({"$ref": "./s.yaml#/X"})}),
            "s.yaml": {
                "X": {
                    "type": "object",
                    "required": ["a"],
                    "properties": {
                        "a": {"type": "string"},
                    },
                }
            },
        },
    )
    old_service, _ = _load(before)
    new_service, _ = _load(after)
    rules = {f.rule_id for f in evaluate_breaking(diff_services(old_service, new_service))}
    assert "BRK-REQ-FIELD-REMOVED" in rules


# --------------------------------------------------------------- hygiene


def test_a_fragment_referenced_twice_is_hoisted_once(tmp_path: Path) -> None:
    entry = _tree(
        tmp_path,
        {
            "openapi.yaml": _entry(
                **{
                    "/a": _post({"$ref": "./s.yaml#/X"}),
                    "/b": _post({"$ref": "./s.yaml#/X"}),
                }
            ),
            "s.yaml": {"X": {"type": "object", "properties": {"a": {"type": "string"}}}},
        },
    )
    document = yaml.safe_load(entry.read_text(encoding="utf-8"))
    result = bundle(document, base=entry)
    assert len(result.document["components"]["schemas"]) == 1
    assert len(result.rewritten) == 1


def test_generated_names_do_not_depend_on_the_checkout_directory(tmp_path: Path) -> None:
    """A bundler whose names moved with the directory would make the next diff
    on a different machine report every schema as renamed."""
    names: list[list[str]] = []
    for directory in ("one", "two"):
        entry = _tree(
            tmp_path / directory,
            {
                "openapi.yaml": _entry(**{"/x": _post({"$ref": "./s.yaml#/X"})}),
                "s.yaml": {"X": {"type": "object"}},
            },
        )
        document = yaml.safe_load(entry.read_text(encoding="utf-8"))
        names.append(sorted(bundle(document, base=entry).document["components"]["schemas"]))
    assert names[0] == names[1]


def test_two_files_with_the_same_name_do_not_collide(tmp_path: Path) -> None:
    entry = _tree(
        tmp_path,
        {
            "openapi.yaml": _entry(
                **{
                    "/a": _post({"$ref": "./one/s.yaml#/X"}),
                    "/b": _post({"$ref": "./two/s.yaml#/X"}),
                }
            ),
            "one/s.yaml": {"X": {"type": "object", "properties": {"a": {"type": "string"}}}},
            "two/s.yaml": {"X": {"type": "object", "properties": {"b": {"type": "string"}}}},
        },
    )
    document = yaml.safe_load(entry.read_text(encoding="utf-8"))
    schemas = bundle(document, base=entry).document["components"]["schemas"]
    assert len(schemas) == 2
    assert {tuple(sorted(s["properties"])) for s in schemas.values()} == {("a",), ("b",)}


def test_a_reference_cycle_across_files_terminates(tmp_path: Path) -> None:
    entry = _tree(
        tmp_path,
        {
            "openapi.yaml": _entry(**{"/x": _post({"$ref": "./a.yaml#/A"})}),
            "a.yaml": {"A": {"type": "object", "properties": {"b": {"$ref": "./b.yaml#/B"}}}},
            "b.yaml": {"B": {"type": "object", "properties": {"a": {"$ref": "./a.yaml#/A"}}}},
        },
    )
    document = yaml.safe_load(entry.read_text(encoding="utf-8"))
    result = bundle(document, base=entry)
    assert len(result.document["components"]["schemas"]) == 2


def test_a_missing_file_is_an_error_naming_the_reference(tmp_path: Path) -> None:
    entry = _tree(
        tmp_path,
        {"openapi.yaml": _entry(**{"/x": _post({"$ref": "./gone.yaml#/X"})})},
    )
    document = yaml.safe_load(entry.read_text(encoding="utf-8"))
    result = bundle(document, base=entry)
    assert [f.rule_id for f in result.findings] == ["SPEC-REF-UNREADABLE"]
    assert "gone.yaml" in result.findings[0].message


def test_a_pointer_that_does_not_exist_in_a_real_file_is_an_error(tmp_path: Path) -> None:
    entry = _tree(
        tmp_path,
        {
            "openapi.yaml": _entry(**{"/x": _post({"$ref": "./s.yaml#/Missing"})}),
            "s.yaml": {"X": {"type": "object"}},
        },
    )
    document = yaml.safe_load(entry.read_text(encoding="utf-8"))
    result = bundle(document, base=entry)
    assert [f.rule_id for f in result.findings] == ["SPEC-REF-UNRESOLVED"]
    assert "Missing" in result.findings[0].message


# ------------------------------------------------------------- refusals


def test_an_absolute_path_is_refused(tmp_path: Path) -> None:
    """A portable contract never contains one.

    Which makes refusing it free, and makes following it a way for a document
    to choose which file this process reads.
    """
    entry = _tree(
        tmp_path,
        {"openapi.yaml": _entry(**{"/x": _post({"$ref": "/etc/passwd#/X"})})},
    )
    document = yaml.safe_load(entry.read_text(encoding="utf-8"))
    result = bundle(document, base=entry)
    assert [f.rule_id for f in result.findings] == ["SPEC-REF-ABSOLUTE-REFUSED"]
    assert result.rewritten == {}


def test_a_windows_absolute_path_is_refused_on_every_platform(tmp_path: Path) -> None:
    """The hazard belongs to the document, not to the platform reading it."""
    entry = _tree(
        tmp_path,
        {"openapi.yaml": _entry(**{"/x": _post({"$ref": "C:\\\\secrets\\\\keys.yaml#/X"})})},
    )
    document = yaml.safe_load(entry.read_text(encoding="utf-8"))
    result = bundle(document, base=entry)
    assert [f.rule_id for f in result.findings] == ["SPEC-REF-ABSOLUTE-REFUSED"]


def test_a_remote_reference_is_not_fetched_by_default(tmp_path: Path) -> None:
    fetched: list[str] = []

    entry = _tree(
        tmp_path,
        {"openapi.yaml": _entry(**{"/x": _post({"$ref": "https://evil.test/s.yaml#/X"})})},
    )
    document = yaml.safe_load(entry.read_text(encoding="utf-8"))
    result = bundle(document, base=entry, fetch=lambda url: fetched.append(url) or "")
    assert fetched == [], "a URL in a document must not make this process call it"
    assert [f.rule_id for f in result.findings] == ["SPEC-REF-REMOTE-REFUSED"]


def test_the_opt_in_actually_fetches(tmp_path: Path) -> None:
    """A flag that changes nothing is worse than no flag.

    So the permitted path is exercised, not just the refused one.
    """
    fetched: list[str] = []

    def fetch(url: str) -> str:
        fetched.append(url)
        return yaml.safe_dump({"X": {"type": "object", "properties": {"a": {"type": "string"}}}})

    entry = _tree(
        tmp_path,
        {"openapi.yaml": _entry(**{"/x": _post({"$ref": "https://api.test/s.yaml#/X"})})},
    )
    document = yaml.safe_load(entry.read_text(encoding="utf-8"))
    result = bundle(document, base=entry, allow_remote=True, fetch=fetch)
    assert fetched == ["https://api.test/s.yaml"]
    schemas = result.document["components"]["schemas"]
    assert [sorted(s["properties"]) for s in schemas.values()] == [["a"]]


def test_a_relative_ref_inside_a_fetched_document_is_still_a_fetch(tmp_path: Path) -> None:
    """And it resolves against the URL, not against the working directory.

    Resolving it locally would read whichever file happened to sit at that
    relative path next to the entry document -- a remote document choosing a
    local file, which is worse than the fetch it replaced.
    """
    fetched: list[str] = []

    def fetch(url: str) -> str:
        fetched.append(url)
        if url.endswith("root.yaml"):
            return yaml.safe_dump({"X": {"$ref": "./nested/inner.yaml#/Y"}})
        return yaml.safe_dump({"Y": {"type": "string"}})

    entry = _tree(
        tmp_path,
        {"openapi.yaml": _entry(**{"/x": _post({"$ref": "https://api.test/d/root.yaml#/X"})})},
    )
    document = yaml.safe_load(entry.read_text(encoding="utf-8"))
    bundle(document, base=entry, allow_remote=True, fetch=fetch)
    assert fetched == [
        "https://api.test/d/root.yaml",
        "https://api.test/d/nested/inner.yaml",
    ]


def test_the_file_budget_reports_when_it_stops(tmp_path: Path) -> None:
    """Silent truncation would leave schemas absent with nothing said."""
    files: dict[str, Any] = {
        "openapi.yaml": _entry(**{f"/p{i}": _post({"$ref": f"./s{i}.yaml#/X"}) for i in range(6)})
    }
    for i in range(6):
        files[f"s{i}.yaml"] = {"X": {"type": "object"}}
    entry = _tree(tmp_path, files)
    document = yaml.safe_load(entry.read_text(encoding="utf-8"))
    result = bundle(document, base=entry, max_files=3)
    capped = [f for f in result.findings if f.rule_id == "SPEC-REF-BUNDLE-CAPPED"]
    assert len(capped) == 1, "the cap is reported once, not per skipped ref"
    assert "absent from the model" in capped[0].message
