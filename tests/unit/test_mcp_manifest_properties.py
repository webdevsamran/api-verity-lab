"""Property-based cover for the MCP manifest loader.

CONTRIBUTING.md expects Hypothesis for schema and diff logic, and the loader is
both. The example-based suite in `test_mcp_manifest.py` pins the behaviours
that were designed; these pin the invariants that have to hold for inputs
nobody wrote down.

The volatile-field property is the one that matters. A single hand-written
example proves `ttlMs` and `cacheScope` are ignored for the two values that
example happens to use; generating them proves the loader never reads them at
all, which is what the whitelist was for.
"""

from __future__ import annotations

from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from apiverity.diff.engine import diff_services
from apiverity.specs.mcp import load_manifest

pytestmark = pytest.mark.property

#: Tool names the specification permits, kept to the shape a server would use.
_names = st.from_regex(r"\A[a-z][a-z0-9_]{0,20}\Z", fullmatch=True)

_scalars = st.sampled_from(["string", "integer", "number", "boolean"])

_properties = st.dictionaries(
    st.from_regex(r"\A[a-z][a-z0-9_]{0,10}\Z", fullmatch=True),
    _scalars.map(lambda t: {"type": t}),
    max_size=4,
)


@st.composite
def tools(draw: Any) -> dict[str, Any]:
    props = draw(_properties)
    # A tool with no properties is legal (`list_regions` in the fixtures takes
    # none), and `sampled_from([])` is `nothing()`, which cannot fill a list at
    # all -- so the empty case has to be handled rather than drawn.
    required = (
        draw(st.lists(st.sampled_from(sorted(props)), max_size=2, unique=True)) if props else []
    )
    return {
        "name": draw(_names),
        "description": draw(st.text(max_size=30)),
        "inputSchema": {
            "type": "object",
            "properties": props,
            "required": sorted(required),
        },
    }


#: Every field on a list-result envelope that is cache or pagination state.
_volatile = st.fixed_dictionaries(
    {
        "ttlMs": st.integers(min_value=0, max_value=10**9),
        "cacheScope": st.sampled_from(["public", "private"]),
        "resultType": st.sampled_from(["complete", "partial"]),
    }
)


def _unique(tool_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop duplicate names, which are a separate (reported) condition."""
    seen: set[str] = set()
    out = []
    for tool in tool_list:
        if tool["name"] not in seen:
            seen.add(tool["name"])
            out.append(tool)
    return out


@settings(max_examples=60, deadline=None)
@given(tool_list=st.lists(tools(), min_size=1, max_size=4), a=_volatile, b=_volatile)
def test_cache_state_never_produces_a_change(
    tool_list: list[dict[str, Any]], a: dict[str, Any], b: dict[str, Any]
) -> None:
    """Two manifests differing *only* in envelope state must diff to nothing."""
    tool_list = _unique(tool_list)
    before, _ = load_manifest({"tools": tool_list, **a})
    after, _ = load_manifest({"tools": tool_list, **b})
    assert diff_services(before, after) == []


@settings(max_examples=60, deadline=None)
@given(tool_list=st.lists(tools(), min_size=1, max_size=4))
def test_loading_is_idempotent(tool_list: list[dict[str, Any]]) -> None:
    """The same payload twice must produce the same contract, byte for byte.

    AGENTS.md: identical inputs produce byte-identical artifacts. A loader that
    depended on dict iteration order would pass a single example and fail here.
    """
    tool_list = _unique(tool_list)
    first, _ = load_manifest({"tools": tool_list})
    second, _ = load_manifest({"tools": tool_list})
    assert first.model_dump_json() == second.model_dump_json()


@settings(max_examples=60, deadline=None)
@given(tool_list=st.lists(tools(), min_size=1, max_size=4))
def test_a_manifest_never_differs_from_itself(tool_list: list[dict[str, Any]]) -> None:
    """The floor under every diff claim: no change where nothing changed."""
    tool_list = _unique(tool_list)
    service, _ = load_manifest({"tools": tool_list})
    again, _ = load_manifest({"tools": tool_list})
    assert diff_services(service, again) == []


@settings(max_examples=40, deadline=None)
@given(tool_list=st.lists(tools(), min_size=1, max_size=4), label_a=_names, label_b=_names)
def test_the_manifest_label_is_not_part_of_a_tool_identity(
    tool_list: list[dict[str, Any]], label_a: str, label_b: str
) -> None:
    """Two dumps of one server, saved under different filenames, are equal."""
    tool_list = _unique(tool_list)
    a, _ = load_manifest({"tools": tool_list}, label=label_a)
    b, _ = load_manifest({"tools": tool_list}, label=label_b)
    assert a.operation_keys() == b.operation_keys()
    assert diff_services(a, b) == []


@settings(max_examples=40, deadline=None)
@given(tool_list=st.lists(tools(), min_size=1, max_size=5))
def test_every_loaded_tool_is_reachable_by_its_own_key(
    tool_list: list[dict[str, Any]],
) -> None:
    tool_list = _unique(tool_list)
    service, _ = load_manifest({"tools": tool_list})
    for operation in service.operations:
        assert service.find_operation(operation.key) is operation
