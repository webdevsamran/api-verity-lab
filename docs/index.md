# api-verity-lab

**Unified API contract governance, breaking-change analysis, schema-driven
testing, runtime drift detection, traffic replay and performance regression
for OpenAPI, AsyncAPI, GraphQL and gRPC.**

Every supported spec format compiles into one normalized contract model, and
every engine downstream reads that model rather than the original document.
That is what lets a breaking-change rule, a fuzz generator and a drift check
agree about what an operation is.

## Start here

| If you want to | Read |
|---|---|
| Understand the design | [Architecture](architecture.md) |
| Know which rule fired, and why | [Rule catalog](rule-catalog.md) |
| Know what each format supports | [Spec support](spec-support.md) · [Protocol support](protocol-support.md) |
| Gate a pipeline on contract changes | [CI contract gate](ci.md) |
| Use it as a library | [SDK](sdk.md) |
| Branch on results in a script | [Exit codes](exit-codes.md) |
| Judge whether it is ready for you | [Capability status](capability-status.md) · [Product gaps](product-gaps.md) |

## What this project promises about its own output

It is a verification tool, so one class of bug matters more than the rest: the
tool asserting something it did not establish. Three habits follow, and each is
enforced in CI rather than intended.

- **Never assert what the run did not establish.** A field that cannot be
  derived reads `unknown`, with a reason. Provenance in an artifact that gates
  someone else's build has to be earned.
- **Documented output is captured, never written.** The examples in the README
  come from real runs; the rule catalogue is generated from the code; the
  competitive table is rendered from committed API data. CI fails when a
  generated file and its source disagree.
- **Counts are derived.** Rule totals, command counts and page counts come
  from the source, not from prose that was true once.

The [rule catalog](rule-catalog.md) is generated. The
[competitive analysis](competitive-analysis.md) is rendered from data fetched
by a checked-in script. If either disagrees with its source, the build fails.
