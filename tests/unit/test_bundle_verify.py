"""`apiverity verify` — the check that made SHA256SUMS mean something.

`export` has always written a checksum file and nothing has ever read it. A
bundle emailed between machines, or pulled out of a CI artifact store, could be
altered in any way and nothing would notice; the file was a comment that looked
like a control.

Three failure modes, deliberately reported separately because they mean
different things to whoever is holding the bundle: a digest that no longer
matches (tampered or corrupted), a listed file that is gone (truncated), and a
file present that the manifest never listed (added). "The bundle is wrong" is
not an actionable sentence.
"""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from typing import Any

from apiverity.cli.commands.common import EXIT_FINDINGS, EXIT_OK, EXIT_USAGE
from apiverity.cli.main import main

_ROOT = Path(__file__).resolve().parents[2]


def _run(argv: list[str]) -> tuple[int, dict[str, Any], str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    text = out.getvalue()
    return code, (json.loads(text) if text.strip().startswith("{") else {}), err.getvalue()


def _bundle(tmp_path: Path) -> Path:
    out = tmp_path / "bundle"
    code, _, _ = _run(
        [
            "export",
            "--output",
            str(out),
            "--data",
            '{"tool":"apiverity","command":"breaking","findings":[]}',
            "--spec",
            str(_ROOT / "fixtures/apis/versioned/v1.yaml"),
        ]
    )
    assert code == EXIT_OK
    return out


def test_an_untouched_bundle_verifies(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    code, payload, _ = _run(["verify", str(bundle), "--json"])
    assert code == EXIT_OK
    assert payload["verified"] is True
    assert payload["files_checked"] >= 2
    assert payload["mismatched"] == payload["missing"] == payload["unlisted"] == []


def test_a_tampered_file_is_caught(tmp_path: Path) -> None:
    """The case the checksum existed for and never covered."""
    bundle = _bundle(tmp_path)
    result = bundle / "result.json"
    payload = json.loads(result.read_text(encoding="utf-8"))
    payload["findings"] = ["injected"]
    result.write_text(json.dumps(payload), encoding="utf-8")

    code, report, err = _run(["verify", str(bundle), "--json"])
    assert code == EXIT_FINDINGS
    assert report["verified"] is False
    assert report["mismatched"] == ["result.json"]
    assert "checksum does not match" in err


def test_a_removed_file_is_distinguished_from_a_tampered_one(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    (bundle / "contract-snapshot").unlink()

    code, report, err = _run(["verify", str(bundle), "--json"])
    assert code == EXIT_FINDINGS
    assert report["missing"] == ["contract-snapshot"]
    assert report["mismatched"] == []
    assert "absent from the bundle" in err


def test_an_added_file_is_reported(tmp_path: Path) -> None:
    """A bundle is a closed set; something extra in it was not exported."""
    bundle = _bundle(tmp_path)
    (bundle / "extra.txt").write_text("surprise", encoding="utf-8")

    code, report, _ = _run(["verify", str(bundle), "--json"])
    assert code == EXIT_FINDINGS
    assert report["unlisted"] == ["extra.txt"]


def test_a_directory_that_is_not_a_bundle_is_a_usage_error(tmp_path: Path) -> None:
    """Distinct from a bundle that fails verification.

    "This was never a bundle" and "this bundle is corrupt" call for different
    responses, so they get different exit codes.
    """
    code, _, err = _run(["verify", str(tmp_path)])
    assert code == EXIT_USAGE
    assert "no SHA256SUMS" in err


def test_a_missing_directory_is_a_usage_error(tmp_path: Path) -> None:
    code, _, err = _run(["verify", str(tmp_path / "nope")])
    assert code == EXIT_USAGE
    assert "not a bundle directory" in err


def test_a_malformed_checksum_file_is_refused_rather_than_half_read(tmp_path: Path) -> None:
    """Skipping an unparseable line would silently verify fewer files than it claims."""
    bundle = _bundle(tmp_path)
    (bundle / "SHA256SUMS").write_text("this is not a checksum line\n", encoding="utf-8")
    code, _, err = _run(["verify", str(bundle)])
    assert code == EXIT_USAGE
    assert "malformed" in err


def test_the_checksum_file_is_not_checked_against_itself(tmp_path: Path) -> None:
    """It cannot contain its own digest, so it must be excluded from the closed set."""
    bundle = _bundle(tmp_path)
    _, report, _ = _run(["verify", str(bundle), "--json"])
    assert "SHA256SUMS" not in report["unlisted"]
    assert report["verified"] is True
