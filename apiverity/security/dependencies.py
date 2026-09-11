"""The files and URLs a contract declares a dependency on.

A multi-file OpenAPI document is a dependency graph.
`$ref: ../../shared/error.yaml` is a build-time dependency on a tree somebody
else maintains, and `$ref: https://schemas.example.com/money.yaml` is a
build-time dependency on a server somebody else operates -- one this process
fetches, at an address the *document* chose.

OWASP files that under MCP04 (supply chain) and it is the same hazard for a
plain contract: the schema your gate validated against is whatever that host
served the moment your build ran.

## What the bundler already knew

`specs/bundle.py` records every external reference it rewrites --
`BundleResult.rewritten`, keyed by the ref exactly as the document wrote it --
and every source it read. The OpenAPI parser copied the source list to
`self.sources`, and **nothing read either**. So a run that pulled four files
reported a `contract_hash` for the entry document and said nothing about the
other three, and an artifact that names one file for a four-file contract is
provenance that does not name what it came from.

`Service.dependencies` carries the declared references now -- the ref strings,
not the resolved paths, because what a reader can act on is what the document
says -- and these checks are about what is in it.

## The rules, and what each is actually claiming

**`SEC-DEP-REMOTE`** -- a `$ref` to a URL. Not a defect on its own; plenty of
organisations publish shared schemas that way. It is a fact the report has to
carry, because the verdict depended on a response nobody in the repository
controls.

**`SEC-DEP-UNPINNED`** -- a remote ref whose URL carries no version, tag or
commit. `https://schemas.example.com/money.yaml` resolves to whatever is served
today; the same contract validated tomorrow may be validated against something
else, and the diff between the two runs will blame your API for the change.

**`SEC-DEP-OUTSIDE-TREE`** -- a reference that climbs out of the entry
document's directory. Normal inside a monorepo, and a defect the moment the
document leaves one: whoever downloads the published contract gets a `$ref` to
nothing. INFO, and the hint says which of the two it is.

There is deliberately **no integrity rule**. Nothing here can verify that a
remote schema is the one you reviewed: `$ref` has no digest, there is no
lockfile for it, and inventing a checksum sidecar only this tool understands
would be a mechanism nobody else honours. `SEC-DEP-UNPINNED` says what to do
instead.
"""

from __future__ import annotations

import posixpath
import re

from apiverity.core.model import Finding, Service, Severity

#: Something in the path that fixes what will be served: a semantic version, a
#: `v2`, a 7+ character hex commit, or a date. Deliberately broad -- the
#: question is "did somebody pin this", and a false negative costs a warning
#: nobody needed rather than a missing one.
_PINNED = re.compile(
    r"(?:^|[/@_.-])(?:"
    r"v?\d+\.\d+(?:\.\d+)?"  # 1.2, v1.2.3
    r"|v\d+"  # v2
    r"|[0-9a-f]{7,40}"  # a commit
    r"|\d{4}-\d{2}-\d{2}"  # a dated iteration
    r")(?:[/@_.-]|$)",
    re.IGNORECASE,
)


def is_remote(reference: str) -> bool:
    return reference.startswith(("http://", "https://"))


def is_pinned(url: str) -> bool:
    """Whether a remote reference names something anybody could re-fetch.

    Only the path and query are considered. A host is not a pin:
    `api.v2.example.com/schema.yaml` still serves whatever is there today, and
    counting the `v2` in the hostname would call it pinned.
    """
    without_fragment = url.split("#", 1)[0]
    _, _, after_scheme = without_fragment.partition("://")
    _, _, tail = after_scheme.partition("/")
    return bool(_PINNED.search(tail))


def escapes_tree(reference: str) -> bool:
    """Whether a file reference climbs out of the entry document's directory."""
    if is_remote(reference):
        return False
    location = reference.split("#", 1)[0]
    if not location:
        return False
    return posixpath.normpath(location).startswith("..")


def check_dependencies(service: Service) -> list[Finding]:
    """Every declared external reference, as findings.

    A contract with none produces nothing: a single-file document has no
    supply chain, and saying so on every run would be noise in the reports of
    the people who least need it.
    """
    out: list[Finding] = []
    for reference in service.dependencies:
        if is_remote(reference):
            out.append(_remote_finding(reference))
            if not is_pinned(reference):
                out.append(_unpinned_finding(reference))
        elif escapes_tree(reference):
            out.append(_outside_tree_finding(reference))
    return out


def _remote_finding(url: str) -> Finding:
    return Finding(
        rule_id="SEC-DEP-REMOTE",
        severity=Severity.WARN,
        message=(
            f"this contract references {url}, so part of the schema it is validated "
            "against is whatever that host serves"
        ),
        hint=(
            "Not a defect on its own -- shared schemas are often published this way. "
            "It is a fact the report has to carry, because the verdict depended on a "
            "response nobody in this repository controls. Vendor the file into the "
            "contract's own tree if that is not acceptable. Note that this tool only "
            "fetches it when `--allow-remote-refs` is given; without that the schema "
            "behind the ref is absent from the model."
        ),
    )


def _unpinned_finding(url: str) -> Finding:
    return Finding(
        rule_id="SEC-DEP-UNPINNED",
        severity=Severity.WARN,
        message=(
            f"{url} names no version, tag or commit, so it resolves to whatever is served today"
        ),
        hint=(
            "Pin it: a path carrying a semantic version, a `v2`, a commit or a dated "
            "iteration is one anybody can re-fetch. Without that, the same contract "
            "validated tomorrow may be validated against something else, and the diff "
            "between the two runs will blame your API for the change."
        ),
    )


def _outside_tree_finding(reference: str) -> Finding:
    return Finding(
        rule_id="SEC-DEP-OUTSIDE-TREE",
        severity=Severity.INFO,
        message=(
            f"this contract references {reference}, which is outside the directory the "
            "entry document lives in"
        ),
        hint=(
            "Normal inside a monorepo, and a defect the moment the document leaves one: "
            "whoever downloads the published contract gets a `$ref` to nothing. "
            "`apiverity export` bundles the tree, which is the portable form."
        ),
    )


__all__ = ["check_dependencies", "escapes_tree", "is_pinned", "is_remote"]
