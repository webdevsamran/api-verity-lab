# Awesome-list submissions

Prepared entries for the lists where this project belongs, so submitting one is
a copy-paste rather than an afternoon of writing.

**These are drafts, not submissions.** Opening a pull request against somebody
else's repository is the maintainer's to do, from an account with a history —
that is why `DIST-05` is listed as waiting on an account owner in
[roadmap status](roadmap-status.md).

## Before submitting anything

Every one of these lists has contribution rules, and most of them have a
maintainer tired of drive-by self-promotion. Read `CONTRIBUTING.md` on the list
first, and:

- **Submit to the section the project actually belongs in.** An API governance
  engine in a "testing" list's mocking section wastes everybody's time.
- **One list at a time.** A dozen simultaneous pull requests from one account
  on one day reads as a campaign, because it is one.
- **Do not inflate.** These entries say what the tool does. If a reviewer
  checks one claim and finds it optimistic, the entry is declined and so is the
  next one.
- **Say it is yours.** Several lists require disclosure of self-submission, and
  the ones that do not still prefer it.

## The entries

### For OpenAPI and API-tooling lists

```markdown
- [api-verity-lab](https://github.com/webdevsamran/api-verity-lab) - API contract governance in one tool: breaking-change rules, runtime drift detection, schema-driven fuzzing and performance budgets for OpenAPI, Swagger 2.0, AsyncAPI, GraphQL, gRPC, MCP and WSDL, under one contract model and one result format.
```

### For contract-testing lists

```markdown
- [api-verity-lab](https://github.com/webdevsamran/api-verity-lab) - Versioned breaking-change rules with stable ids, semver policy, and drift detection that compares the declared contract against the running service. Multi-protocol; CLI-first; Apache-2.0.
```

### For MCP and AI-agent lists

```markdown
- [api-verity-lab](https://github.com/webdevsamran/api-verity-lab) - Governance for MCP tool surfaces: breaking-change rules for `tools/list`, declared-vs-live drift, tool-description poisoning detection, a signed lockfile, and call budgets. Findings map to the OWASP MCP and Agentic Top 10.
```

### For DevOps and CI lists

```markdown
- [api-verity-lab](https://github.com/webdevsamran/api-verity-lab) - Contract gate for CI: fails a pull request on breaking API changes, comments with the non-breaking alternative, exports SARIF, and runs in merge queues. Seven spec formats, one exit-code contract.
```

### For SOAP and enterprise-integration lists

```markdown
- [api-verity-lab](https://github.com/webdevsamran/api-verity-lab) - WSDL 1.1 / SOAP breaking-change analysis, including SOAPAction, binding style and SOAP version changes that break every generated stub while leaving message schemas identical.
```

## Candidate lists

Verify each is still maintained before submitting — several well-known lists
have been archived, and an entry in an archived list is a backlink nobody
follows.

| List | Section that fits |
|---|---|
| `awesome-openapi3` | Tooling / validators and linters |
| `awesome-api` | Testing and contract tooling |
| `awesome-rest` | Tools |
| `awesome-mcp-servers` / `awesome-mcp` | Tooling around MCP, not an MCP server itself |
| `awesome-devops` | Testing, quality gates |
| `awesome-python` | Testing, or API tooling |
| `awesome-graphql` | Tooling / schema management |
| `awesome-grpc` | Tooling |
| `awesome-asyncapi` | Tooling |
| `awesome-static-analysis` | Multi-language / API |

## What not to claim

Three things this project's own documentation is careful about, and an
awesome-list entry is the easiest place to get them wrong:

1. **Do not say MCP governance is unclaimed.** It is falsifiable in one npm
   search: a Cisco-backed Apache-2.0 tool ships static manifest diffing with 35
   rules. The open ground is *drift* and *fleet posture*.
2. **Do not say it replaces oasdiff, Spectral or Pact.** It does not, this
   project's own [comparison](competitive-analysis.md) says so, and a reviewer
   who checks will find that out.
3. **Do not list it as installable from PyPI until it is.** See
   [Installing](install.md) for what actually works today.
