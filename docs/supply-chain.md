# Supply chain: what a release carries, and how to check it

Procurement asks for three things about a build now: a bill of materials, a
signed statement of where the artifacts came from, and a way to verify both
without trusting the party that produced them. This page says what this
project publishes, what it does not, and — the part most pages leave out —
what has actually been exercised.

## What a tagged release publishes

| Artifact | Where |
|---|---|
| `.whl` and `.tar.gz` | the GitHub release, and PyPI once Trusted Publishing is enabled |
| `SHA256SUMS` | the GitHub release. `sha256sum -c SHA256SUMS` |
| `api-verity-lab.spdx.json` | the GitHub release. SPDX 2.3 JSON, generated from the same tree that produced the artifacts |
| SLSA build provenance | GitHub's attestation store, Sigstore-backed |
| SBOM attestation | the same, binding that SBOM to those exact artifacts |
| Container image provenance | pushed to GHCR alongside the image, attested **by digest** |

## Verifying

```bash
gh attestation verify api_verity_lab-0.2.0-py3-none-any.whl --repo webdevsamran/api-verity-lab
```

```bash
gh attestation verify oci://ghcr.io/webdevsamran/api-verity-lab-server:0.2.0 \
  --repo webdevsamran/api-verity-lab
```

Both check a signature made during the workflow run against Sigstore's public
transparency log. There is no key here for anyone to lose or leak: the
signature comes from the workflow's OIDC identity, and what it attests is
*which workflow, at which commit, produced these exact bytes*.

The image is attested by **digest**, not by tag. A tag can be moved onto
different bytes, and an attestation naming a tag would then describe an image
nobody is running.

## What is not done

**The image is not signed with a long-lived key.** Provenance is a signed
statement about the build; a cosign keypair would be a signed statement about
the publisher. The second needs a key somebody keeps safe, and a key stored
badly is worse than no key — this project does not currently have anywhere
good to keep one.

**Dependencies are not pinned by hash.** `pyproject.toml` declares ranges, so
a `pip install` resolves them at install time. The SBOM records what *this*
build resolved; it does not make your install resolve the same.

**The SBOM is generated, not curated.** It is
[anchore/sbom-action](https://github.com/anchore/sbom-action)'s output over the
repository. It carries what that scanner found and nothing anyone reviewed by
hand.

**None of this has run yet.** These steps are on the tag-push path, and this
project has not cut a tagged release since they were added. The workflow is
configured and unexercised, and saying otherwise would be exactly the kind of
claim the rest of this repository refuses to make. The first `v*` tag is what
turns this page from a description into a fact.

## Actions are pinned, and the comment is checked

Every third-party action is pinned to a full commit SHA, and
`scripts/check_action_pins.py` runs in CI to confirm that the trailing
`# vX.Y.Z` comment names a tag that really points at that SHA.

That check exists because it caught a real defect: five `uses:` lines pinned
`actions/setup-python@5fda3b95a4ea` and annotated it `# v5.6.0` when the SHA is
**v7.0.0** — two majors newer. A reviewer auditing the supply chain would have
read the comment and concluded the repository ran a version it did not. The pin
was the control; the comment was what anyone actually read.

Resolving a SHA to its tags needs the network, so the check degrades honestly:
without a token it reports every pin as *unresolved* rather than as *verified*.
An unauthenticated run that printed "all pins verified" would be the same
defect in a new place.

## Where else this is covered

- [`docs/audit-export.md`](audit-export.md) — the server's audit log as
  evidence that leaves the building
- [`docs/evidence.md`](evidence.md) — dated, checksummed records for SOC 2,
  ISO 42001, DORA and the EU AI Act
- [`SECURITY.md`](security.md) — reporting a vulnerability
