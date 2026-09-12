---
description: >-
  What to switch on at your scale: one developer with one API, a team with several services, an organisation under audit, or a team shipping AI agents.
---

# Who this is for

The same tool at three scales. Nothing below is a different edition — there is
one build, and the difference is how much of it you switch on.

## One developer, one API

You own a service. You do not have a platform team, an API council or a
governance framework, and you would like to stop breaking your own consumers by
accident.

**Start here, and stop.** Two commands do most of the work:

```bash
apiverity init                                   # writes .apiverity.yaml, gate OFF
apiverity breaking old.yaml openapi.yaml         # what did I just break?
```

The gate starts **off** on purpose. A check that fails on its first run against
an API with three years of history gets removed rather than adopted, so
`init` writes a config that reports and does not fail until you decide it
should.

What is worth switching on next, in order of value for effort:

| | |
|---|---|
| The [CI gate](ci.md) | One `uses:` line. It comments on the pull request with the non-breaking alternative rather than only blocking. |
| [`--check-semver`](rule-catalog.md) | Catches the version number that did not move when the contract did. |
| [`drift --base-url`](mcp-drift.md) against staging | Finds out that the deployment and the document disagree before a consumer does. |
| [Editor diagnostics](lsp.md) | The rules as you type, in VS Code, Neovim, JetBrains, Helix, Zed or Emacs. |

Nothing here needs a server, an account, or a network connection you did not
ask for.

## A team with several services

Now the questions change. It is less "did I break it" and more "who does this
break, and who has to be told".

```bash
apiverity sweep .  --base ../main                # every contract in the monorepo
apiverity breaking old new --consumers consumers.yaml   # whose build goes red
apiverity graph .  --dependents-of shared/money.yaml    # who shares this schema
apiverity digest sweep.json --since last-week.json      # weekly, per team
```

| | |
|---|---|
| [Blast radius](blast-radius.md) | Turns `severity: ERROR` into "this breaks checkout-service and mobile-v3". |
| [Ownership routing](digest.md) | `CODEOWNERS` decides which channel hears about a finding. Routing is the difference between an alert and a muted channel. |
| [Rule packs](plugin-authoring.md) or the [policy DSL](policy-dsl.md) | Your house style as a package your other repositories install, rather than a fork. |
| [Severity profiles](rule-catalog.md) | `strict` / `balanced` / `advisory`, instead of overriding rules one at a time. |
| [Suppressions](ci.md#suppressions) | With an owner, a reason and an **expiry** — the escape hatch that stops a team disabling the whole gate. |
| [Merge queues](merge-queue.md) | Two individually-safe pull requests can combine into a breaking change, and the queue is the only place that combination is ever built. |

## An organisation with compliance obligations

Audit, evidence, isolation and the ability to answer "prove it".

```bash
apiverity evidence run-*.json -o evidence/       # dated, checksummed pack
apiverity audit export --db server.db --org-id 1 # independently verifiable
apiverity freeze on --reason "incident 4821"     # stop releases now
apiverity serve                                  # orgs, RBAC, approvals, can-i-deploy
```

| | |
|---|---|
| [Evidence packs](evidence.md) | SOC 2, ISO/IEC 42001, DORA and the EU AI Act, with the controls each artifact speaks to — and the ones it does not. |
| [Compliance mapping](compliance-mapping.md) | OWASP API Top 10, MCP Top 10 and Agentic Top 10, including a **"what this tool cannot see"** section per framework. |
| [Tamper-evident audit](audit-export.md) | A hash chain somebody can verify without trusting your server. |
| [OIDC](oidc.md) | Your identity provider, with signature, issuer, audience and expiry all actually checked. |
| [Air-gapped install](air-gapped.md) | A Helm chart, a container image, vendored schemas, and an [egress map](egress.md) generated from the source rather than promised in prose. |
| [Kill switch](kill-switch.md) | Named explicitly in agent-governance audit expectations, and it is one command. |

There is no enterprise edition. Everything above is in the Apache-2.0 build,
because a governance tool with a paid half is one an auditor cannot fully read.

## Teams shipping AI agents

The newest audience, and the one with the least tooling.

An MCP tool **description** is what an agent routes on. That makes it
executable text that no schema can constrain, and it is the field an attacker
most wants.

```bash
apiverity validate tools.json                   # is a description instructing the agent?
apiverity drift tools.json --base-url ...       # does the server serve what it declares?
apiverity mcp-lock check --base-url ...         # did the surface change unreviewed?
apiverity mcp-inventory --include-home          # what is this machine even configured to reach?
apiverity budget calls.json --budget budgets.yaml
```

| | |
|---|---|
| [Tool poisoning](mcp-poisoning.md) | Hidden markup, invisible characters, cross-tool instructions, credential paths in prose. |
| [MCP drift](mcp-drift.md) | Declared versus served, plus specification conformance and an authentication posture probe. |
| [Lockfile](mcp-lock.md) | A signed baseline of the tool surface; CI fails on an unreviewed change. |
| [Call budgets](call-budgets.md) | The single most-cited worry about agent traffic is volume, not correctness. |
| [Agent task packs](agent-tasks.md) | Hand a verified surface to a benchmark that measures whether agents can actually use it. |

Honest framing, because it is checkable in one npm search: **static MCP
manifest diffing is not unclaimed** — a Cisco-backed Apache-2.0 tool does it
with 35 rules. What is open is **declared-versus-running drift** and **fleet
posture**, and that is what this project leads on.

## Not a fit if…

Stated so nobody spends an afternoon finding out:

- **You want a mocking product.** `apiverity mock` exists and is deterministic,
  but [Microcks](https://microcks.io/) and [WireMock](https://wiremock.org/) do
  mocking as their whole job.
- **You want a load-testing tool.** Budgets and load shapes exist; [k6](https://k6.io/)
  is a load engine and this is not.
- **You want consumer-driven contracts with a broker.** [Pact](https://pact.io/)
  owns that, and this project has no broker — recorded as a gap rather than
  implied.
- **Your contract is not written down anywhere.** Start with
  `apiverity infer traffic.har -o draft.yaml`, which drafts one from observed
  traffic — then come back.
