# Sponsor api-verity-lab

api-verity-lab is Apache-2.0, runs entirely on your own machines, sends no
telemetry, and has no paid tier. Every feature in it is in the repository you
are reading. That is a deliberate choice, and sponsorship is what makes it a
sustainable one rather than a slowly-abandoned one.

**[→ Sponsor on GitHub](https://github.com/sponsors/webdevsamran)**

## What sponsorship pays for

Honestly, and in the order the money would go:

1. **Maintenance that is not glamorous.** Dependency bumps, Python and Node
   version matrices, the quarterly competitor refresh, keeping 2,800 tests
   green across Linux, macOS and Windows. This is most of the work and none of
   the announcements.
2. **Keeping the claims true.** This project generates its rule catalogue, its
   competitive table, its README examples, its benchmark, its landing pages and
   its roadmap status from the code, and re-checks every one of them in CI.
   That discipline costs real time, and it is the reason anything here can be
   trusted.
3. **Responding to issues from people who are not paying.** The gate this tool
   provides is most valuable to the teams least able to fund it.
4. **The protocols nobody sponsors.** WSDL support exists because enterprises
   still run SOAP, not because it is interesting.

## What it does not buy

Stated plainly, because the alternative is a misunderstanding discovered later:

- **Not priority support, and not an SLA.** This is one maintainer's project.
  Sponsoring makes the work sustainable; it does not create a support contract.
- **Not a feature on demand.** A sponsored feature request is read with real
  attention and is still declined if it would make the tool claim something it
  cannot establish. That rule is the product.
- **Not a logo in the rule output, the CLI, or any artifact this tool
  produces.** Results that gate somebody's deploy do not carry advertising.
- **Not influence over a finding.** No sponsor gets a rule softened, a
  competitor's row edited, or a benchmark rerun until it flatters us. The
  benchmark publishes where this tool loses for exactly this reason.

## Tiers

| | Per month | |
|---|---|---|
| **Supporter** | $5 | Thank-you in `SPONSORS.md`, if you want one. |
| **Backer** | $25 | The above, plus your name or handle in the release notes. |
| **Team** | $100 | The above, plus your logo in this file and on the docs site's sponsors page. |
| **Organisation** | $500 | The above, plus a standing invitation to a quarterly call about what your team needs from a contract gate. Input, not authority. |

Every tier is the same software. There is no sponsor-only build, no licence
key, and nothing behind a paywall — because a governance tool with a hidden
half is a governance tool you cannot audit.

## Current sponsors

**None yet.** This section is written rather than left out so that its absence
is a fact rather than an oversight, and so the first entry does not require a
new file.

If you are the first, you get to decide whether that says your name or
"anonymous".

## Other ways to help, which cost nothing

Sponsorship is not the only useful thing, and for most people it is not the
most useful thing:

- **Run it against a contract you own and open an issue about what it got
  wrong.** A false positive is worth more to this project than a star. It is
  the failure mode that gets a whole rule family switched off, and the only way
  to find one is for somebody to run the tool on an API this repository has
  never seen.
- **Tell it what your protocol does that it models badly.** The gaps are
  written down in [`PRODUCT_GAPS.md`](https://github.com/webdevsamran/api-verity-lab/blob/main/PRODUCT_GAPS.md); the ones that are not
  written down are the expensive ones.
- **Write a rule pack.** [`docs/plugin-authoring.md`](https://github.com/webdevsamran/api-verity-lab/blob/main/docs/plugin-authoring.md)
  and the worked example in
  [`examples/plugins/`](https://github.com/webdevsamran/api-verity-lab/tree/main/examples/plugins/apiverity-house-rules) exist so that
  your house rules do not have to live in a fork.
- **Cite it.** [`CITATION.cff`](https://github.com/webdevsamran/api-verity-lab/blob/main/CITATION.cff) is checked in. Citations compound
  slowly and permanently.
- **Star the repository.** It is the cheapest signal there is and it is how
  other people find the project.

## For companies

If your organisation depends on this in CI, the sponsorship that helps most is
the boring recurring kind at the **Team** or **Organisation** tier, from a
budget line rather than from an individual's card. That is what turns
"maintained by somebody in their evenings" into "maintained".

If procurement needs paperwork: the licence is Apache-2.0, the SBOM ships with
every release, releases carry Sigstore provenance, and the tool makes no
outbound connection you did not ask it to — the full egress map is generated
from the source in [`docs/egress.md`](https://github.com/webdevsamran/api-verity-lab/blob/main/docs/egress.md).
