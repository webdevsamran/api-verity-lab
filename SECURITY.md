# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | ✅        |

## Reporting a vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Use GitHub's private vulnerability reporting:
https://github.com/webdevsamran/api-verity-lab/security/advisories/new

Include: affected component, reproduction steps, impact assessment,
and any suggested fix. You will receive an acknowledgment within 72 hours.

## Security design principles of this project

api-verity-lab is a testing/governance tool that sends requests to APIs.
We take deliberate safety postures:

1. **Local-first**: the mock server binds to `127.0.0.1` by default.
2. **Explicit targets only**: `test`, `replay`, and `drift` only ever send
   traffic to base URLs you explicitly supply on the command line or in a
   workflow manifest's allowlist. Nothing is auto-discovered and probed.
3. **No exploit payload libraries**: security contract checks are static,
   declarative analyses (missing auth declarations, HTTPS policy, CORS
   metadata). We do not ship attack payloads.
4. **Redaction by default**: imported traffic (HAR/logs) is redacted
   (Authorization headers, cookies, API keys, tokens, configured sensitive
   fields) before storage; result bundles never persist secret values from
   auth profiles (they are environment-referenced).
5. **Production replay opt-in**: replaying against a target marked
   `production` requires an explicit `--i-understand-this-is-production`
   flag.
6. **No destructive workflow generation**: stateful workflows are only
   inferred from explicit links or user-authored manifests; destructive
   sequences are never generated automatically.

## Supply chain

- CI uses pinned Action SHAs and least-privilege permissions.
- Dependabot monitors Python and npm dependencies.
- Releases include SBOM artifacts and checksums.