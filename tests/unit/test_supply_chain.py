"""What the supply-chain page says a release does, bound to the workflow.

A page describing provenance a release does not actually produce is worse than
no page: procurement reads it, and nobody finds out it was aspirational until
somebody tries to verify a download. So each concrete claim on
`docs/supply-chain.md` is asserted against `.github/workflows/release.yml`
here.

What is deliberately **not** asserted is that any of it has run. It is on the
tag-push path, no tag has been cut since it was added, and a test cannot make
that untrue. The page says so in those words, and this file checks that the
page still says so — because the temptation, once the steps exist, is to start
describing them as though they had fired.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOW = _ROOT / ".github" / "workflows" / "release.yml"
_DOC = _ROOT / "docs" / "supply-chain.md"


def _release() -> dict[str, Any]:
    return yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))


def _steps(job: str) -> list[dict[str, Any]]:
    return list(_release()["jobs"][job]["steps"])


def _names(job: str) -> list[str]:
    return [str(step.get("name") or step.get("uses") or "") for step in _steps(job)]


def _uses(job: str, prefix: str) -> dict[str, Any] | None:
    for step in _steps(job):
        if str(step.get("uses", "")).startswith(prefix):
            return step
    return None


# ------------------------------------------------------------- the artifacts


def test_the_release_writes_checksums() -> None:
    """`sha256sum -c SHA256SUMS` is what a downloader runs. Recomputing a hash
    they have nothing to compare against is not verification."""
    assert any("Checksums" in name for name in _names("build"))
    body = " ".join(str(step.get("run", "")) for step in _steps("build"))
    assert "SHA256SUMS" in body


def test_the_release_generates_an_sbom_from_the_tree_it_built() -> None:
    """The `sbom` job in ci.yml scans `main` on every push, which answers a
    different question: what is in the branch, not what is in this release."""
    step = _uses("build", "anchore/sbom-action")
    assert step is not None
    assert step["with"]["format"] == "spdx-json"


def test_the_distributions_are_attested() -> None:
    step = _uses("build", "actions/attest-build-provenance")
    assert step is not None
    subject = str(step["with"]["subject-path"])
    assert ".whl" in subject and ".tar.gz" in subject


def test_the_sbom_is_bound_to_those_artifacts() -> None:
    """An SBOM sitting beside a release says what somebody scanned. An
    attested one says it describes these exact bytes."""
    step = _uses("build", "actions/attest-sbom")
    assert step is not None
    assert step["with"]["sbom-path"].endswith(".spdx.json")


@pytest.mark.parametrize("job", ["build", "docker-image"])
def test_a_job_that_attests_asks_for_the_two_permissions_it_needs(job: str) -> None:
    """`id-token` for the OIDC exchange with Sigstore, `attestations` to record
    the result. Missing either fails at the last step of a release that has
    already tagged."""
    permissions = _release()["jobs"][job]["permissions"]
    assert permissions.get("id-token") == "write"
    assert permissions.get("attestations") == "write"


def test_no_other_job_asks_for_attestation_permission() -> None:
    """Requested per job rather than at the workflow level, so everything else
    keeps the read-only default."""
    jobs = _release()["jobs"]
    holders = {
        name
        for name, job in jobs.items()
        if (job.get("permissions") or {}).get("attestations") == "write"
    }
    assert holders == {"build", "docker-image"}


# ------------------------------------------------------------------ the image


def test_the_image_is_attested_by_digest_not_by_tag() -> None:
    """A tag can be moved onto different bytes, and an attestation naming one
    would then describe an image nobody is running."""
    step = _uses("docker-image", "actions/attest-build-provenance")
    assert step is not None
    assert "subject-digest" in step["with"]
    assert "steps.push.outputs.digest" in str(step["with"]["subject-digest"])


def test_the_push_step_is_addressable_by_the_attestation() -> None:
    """`${{ steps.push.outputs.digest }}` resolves to nothing if the build step
    has no id, and the attestation would then be made over an empty subject."""
    push = _uses("docker-image", "docker/build-push-action")
    assert push is not None
    assert push.get("id") == "push"


# ------------------------------------------------------------------- the pypi


def test_the_sbom_and_checksums_are_removed_before_the_pypi_upload() -> None:
    """`twine` uploads every file in the directory and rejects the ones that
    are not distributions -- which fails the upload with the release already
    tagged."""
    body = " ".join(str(step.get("run", "")) for step in _steps("pypi-publish"))
    assert "SHA256SUMS" in body
    assert ".spdx.json" in body


def test_the_github_release_still_gets_them() -> None:
    """They are removed from the PyPI job's copy of the artifact, not from the
    artifact."""
    body = " ".join(str(step.get("run", "")) for step in _steps("github-release"))
    assert "dist/*" in body


# -------------------------------------------------------------- the honesty


def test_the_page_says_the_workflow_has_not_run() -> None:
    """The temptation, once the steps exist, is to describe them as though
    they had fired. The first `v*` tag is what turns the page into a fact, and
    until then it has to say so."""
    text = _DOC.read_text(encoding="utf-8")
    assert "configured and unexercised" in text


def test_the_page_names_what_is_not_done() -> None:
    """A supply-chain page that lists only what it has is a clean bill of
    health for everything it does not."""
    text = _DOC.read_text(encoding="utf-8")
    assert "## What is not done" in text
    for claim in (
        "not signed with a long-lived key",
        "not pinned by hash",
        "generated, not curated",
    ):
        assert claim in text, f"docs/supply-chain.md no longer says {claim!r}"


def test_the_page_gives_the_command_that_verifies() -> None:
    """A provenance nobody is told how to check is a provenance nobody
    checks."""
    text = _DOC.read_text(encoding="utf-8")
    assert "gh attestation verify" in text
    assert "oci://" in text
