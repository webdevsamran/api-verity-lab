"""The same contract has to hash the same on every machine that reads it.

`contract_hash` is the field a result artifact publishes to say *which
document this is about*. It went into evidence packs, the `.apiverity` bundle,
`can-i-deploy` comparisons and the audit chain, and it was a `sha256` over the
file's raw bytes.

Git hands a Windows working tree CRLF and a Linux one LF for the same commit.
So the same contract, at the same revision, produced two different digests
depending on who ran the tool -- and an evidence pack built on a developer's
machine did not match the one CI built from the identical source. That is
precisely the question a provenance hash exists to answer, answered wrongly.

Nothing caught it for as long as the tool ran on one operating system at a
time. What caught it was the platform matrix: `docs/demo.svg` is generated
from real runs and re-checked in CI, it had been recorded on Windows, and the
digest inside it was one no POSIX machine could reproduce.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from apiverity.core.artifact import contract_hash, normalized_contract_bytes

_CONTRACT = b'openapi: "3.0.3"\ninfo:\n  title: Orders\n  version: 1.0.0\npaths: {}\n'


def test_a_windows_checkout_and_a_posix_one_agree(tmp_path: Path) -> None:
    """The whole point, stated as the two files git actually produces."""
    posix = tmp_path / "lf.yaml"
    windows = tmp_path / "crlf.yaml"
    posix.write_bytes(_CONTRACT)
    windows.write_bytes(_CONTRACT.replace(b"\n", b"\r\n"))

    assert posix.read_bytes() != windows.read_bytes(), "the fixture is not testing anything"
    assert contract_hash(str(posix)) == contract_hash(str(windows))


def test_an_old_mac_line_ending_agrees_too() -> None:
    """Lone CR is rarer than it used to be and still reaches a parser through
    a file somebody converted badly."""
    assert normalized_contract_bytes(b"a\rb") == b"a\nb"
    assert normalized_contract_bytes(b"a\r\nb") == b"a\nb"


def test_the_digest_is_the_one_a_posix_file_has(tmp_path: Path) -> None:
    """Normalizing toward LF rather than toward CRLF, so the digest a Linux
    machine computes over the plain file is the digest everybody gets -- and
    every hash this project has published from CI stays valid."""
    windows = tmp_path / "crlf.yaml"
    windows.write_bytes(_CONTRACT.replace(b"\n", b"\r\n"))
    assert contract_hash(str(windows)) == hashlib.sha256(_CONTRACT).hexdigest()


def test_a_binary_contract_is_hashed_exactly_as_it_is(tmp_path: Path) -> None:
    """A compiled protobuf descriptor set is a contract this tool reads.
    Rewriting bytes inside one would produce a digest that is not the digest
    of any file, which is worse than the problem being fixed."""
    descriptor = b"\x0a\x0d\x00orders.proto\r\n\x12\x06\x00orders"
    path = tmp_path / "descriptor.pb"
    path.write_bytes(descriptor)

    assert normalized_contract_bytes(descriptor) == descriptor
    assert contract_hash(str(path)) == hashlib.sha256(descriptor).hexdigest()


def test_a_text_contract_that_merely_mentions_a_carriage_return_is_still_text() -> None:
    """`\\r` written as two characters in a description is not a carriage
    return, and must not be treated as one."""
    source = b'{"description": "use \\\\r\\\\n between records"}'
    assert normalized_contract_bytes(source) == source


@pytest.mark.parametrize("missing", [None, "", "no/such/contract.yaml"])
def test_an_unreadable_contract_still_produces_a_digest(missing: str | None) -> None:
    """Zeroes rather than an exception: a missing contract is a fact about the
    run, and a provenance field that raises takes the whole artifact with it."""
    assert contract_hash(missing) == "0" * 64


def test_the_fixtures_this_repository_ships_hash_the_same_either_way() -> None:
    """Not a unit of the function -- a check on the actual files, because the
    committed fixtures are what the generated documentation is recorded from,
    and they are the ones that differ between checkouts."""
    root = Path(__file__).resolve().parents[2]
    for name in ("fixtures/mcp/tools_v1.json", "fixtures/mcp/tools_v2.json"):
        raw = (root / name).read_bytes()
        lf = raw.replace(b"\r\n", b"\n")
        assert hashlib.sha256(normalized_contract_bytes(raw)).hexdigest() == (
            hashlib.sha256(lf).hexdigest()
        ), name
