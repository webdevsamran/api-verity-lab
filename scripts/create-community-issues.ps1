# Creates the roadmap community issues (run once by the maintainer).
$repo = "webdevsamran/api-verity-lab"

$issues = @(
  @{ Title = "rules: expand request/response-aware compatibility catalog";
     Body = "## Goal`nGrow the breaking-change rule catalog beyond the current set, keeping the request-vs-response direction model.`n`n## Candidate rules`n- Response enum value removal vs addition asymmetry`n- Nested property requiredness flips inside arrays of objects`n- Discriminator mapping changes on polymorphic schemas`n- Content-type negotiation narrowing (e.g. dropping application/xml)`n- Default value introduction changing client-visible behavior`n`n## Acceptance criteria`n- Each rule has: id, severity default, docs entry in docs/rule-catalog.md, unit tests covering both directions (request/response), and a fixture demonstrating it." },
  @{ Title = "graphql: full operation-level testing and fuzzing support";
     Body = "## Context`nGraphQL schemas already load into the normalized contract model and field/type/nullability/enum diffs work.`n`n## Work items`n- Parse persisted operations (.graphql files) into Operation entries`n- Generate schema-driven queries/mutations from the normalized model`n- Drift checks against live GraphQL endpoints (introspection-based)`n- Error-shape assertions (data/errors envelope validation)`n`n## Acceptance criteria`n- `apiverity test schema.graphql --base-url ...` runs positive/negative query cases; drift reports undocumented field usage." },
  @{ Title = "grpc: descriptor-set based compatibility checking";
     Body = "## Context`nProto loading covers service/RPC removal, field-number reuse, wire-type risks, enum changes.`n`n## Work items`n- Accept compiled FileDescriptorSet input (`--descriptor-set`) alongside .proto sources`n- Message field presence semantics (proto3 optional vs oneof) in diff rules`n- Streaming RPC direction changes (unary -> bidi) as breaking`n- Reserved-range overlap detection`n`n## Note`nDo not claim complete protobuf compatibility until each rule is covered by tests." },
  @{ Title = "plugins: AsyncAPI spec adapter";
     Body = "## Goal`nAdd an `apiverity.specs` plugin normalizing AsyncAPI 2.x/3.x documents (channels as operations, messages as schemas).`n`n## Design notes`n- Reuse the OpenAPI ref resolver where possible`n- Map publish/subscribe to the direction-aware diff model`n- Plugin must register via the `apiverity.specs` entry point and declare PLUGIN_API_VERSION" },
  @{ Title = "fuzz: pluggable case generators and grammar-based payloads";
     Body = "## Goal`nExpose the case-generation pipeline through `apiverity.generators` so third parties can add strategies.`n`n## Candidates`n- Unicode/normalization edge cases in string fields`n- Deeply nested payload depth limits`n- Numeric boundary sweeps driven by multiple-of/exclusive bounds`n- Header injection safety cases (defensive only - no exploit library)" },
  @{ Title = "stateful: assisted workflow inference from explicit links";
     Body = "## Goal`nSuggest workflow manifests from explicit OpenAPI links objects only - never auto-generate destructive sequences.`n`n## Behavior`n- `apiverity workflow --infer spec.yaml` emits a draft YAML manifest with all steps commented out`n- Destructive methods (DELETE) always require manual uncommenting`n- Output includes suggested variable extraction paths from response examples" },
  @{ Title = "drift: recorded-traffic comparison mode hardening";
     Body = "## Goal`nStrengthen `apiverity drift` when comparing sanitized HAR corpora against contracts.`n`n## Work items`n- Aggregate drift frequency per finding across corpus entries`n- Detect systematically missing headers vs one-off omissions`n- Support content-negotiation aware body schema selection`n- Emit a corpus-quality summary (entries skipped due to redaction, unmatched routes)" },
  @{ Title = "reports: SARIF location enrichment and HTML self-containment";
     Body = "## Goal`nImprove report fidelity.`n`n## Work items`n- SARIF: emit region info (line/column) from SourceLocation when available`n- HTML: inline fonts/CSS fully for offline viewing; add shareable filter state in URL hash`n- Markdown: collapsible sections per severity for large result sets" },
  @{ Title = "web: split App.tsx into routed pages with lazy loading";
     Body = "## Context`nThe demo app currently implements all 15 pages as views inside App.tsx (~14 view switch cases). Functionally complete but monolithic.`n`n## Proposal`n- Move each view to src/pages/<Page>.tsx`n- Add react-router with lazy() imports for code splitting`n- Keep the existing shareable-filter URL hash behavior`n- Preserve vitest coverage of navigation and error states" },
  @{ Title = "performance: percentile confidence intervals and warmup controls";
     Body = "## Goal`nMake regression gates statistically sound.`n`n## Work items`n- Report sample counts alongside p50/p90/p95/p99`n- Optional warmup phase excluded from measurements`n- Configurable tolerance per metric (not just global percent)`n- Document noise floors for CI stability in docs/ci.md" }
)

foreach ($i in $issues) {
  gh issue create --repo $repo --title $i.Title --body $i.Body
}
Write-Host "created $($issues.Count) community issues"