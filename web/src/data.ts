/* Data layer: loads demo artifacts (static mode) or self-hosted API results. */

export interface Finding { rule_id: string; severity: 'ERROR' | 'WARN' | 'INFO'; message: string }
export interface Change { id: string; kind: string; direction: string; description: string }
export interface TestResultRow {
  case_id: string; operation_key: string; kind: string; status: string
  actual_status: number | null; violations: string[]; description?: string
  reproduction?: string; minimized?: boolean
}
export interface DriftRow { operation_key: string; rule_id: string; message: string }
export interface PerfOp { operation_key: string; p50_ms: number; p95_ms: number; p99_ms: number; errors: number; throughput_rps: number }
export interface OpCoverage { operation_key: string; exercised: boolean; declared_statuses: string[]; statuses_seen: number[] }
export interface RuleRow { rule_id: string; severity: 'ERROR' | 'WARN' | 'INFO'; description: string }
export interface StepResultRow { step: string; status: string; actual_status: number | null; violations: string[]; duration_ms: number }
export interface WorkflowData { name: string; description: string | null; result: { status: string; steps: StepResultRow[]; cleanup_steps: StepResultRow[]; variables: Record<string, unknown> } }
export interface ContractOp { key: string; method: string; path: string; summary: string | null; deprecated: boolean; parameters: string[]; responses: string[] }
export interface SemverVerdict {
  old_version: string; new_version: string; required_bump: 'major' | 'minor' | 'patch'
  compliant: boolean; findings: Finding[]
}
export interface ReplayManifest {
  target: string; corpus: string; entries: number; rate_per_second: number
  safety_class: string; destructive_methods_allowed: boolean
}
export interface OrgUser { id: number; subject: string; display_name: string; role: string; kind: string }
export interface OrgContract { id: number; title: string; version: string; protocol: string; checksum: string; published_by: string; published_at: string }
export interface Environment { id: number; name: string; base_url: string; safety_class: string; owner: string | null; allowed_modes: string }
export interface Approval { id: number; contract_title: string; from_version: string; to_version: string; justification: string; migration_guide: string | null; status: string; requested_by: string; decided_by: string | null; created_at: string; decided_at: string | null }
export interface RunRow { id: number; kind: string; status: string; requested_by: string; verification_for: string | null; environment: string | null }
export interface AuditEvent { id: number; ts: string; actor: string; action: string; target: string; entry_hash: string; prev_hash: string }
export interface Webhook { id: number; url: string; secret_ref: string; events: string[]; active: number }
export interface CatalogService { title: string; protocol: string; lifecycle: string; owner: string; product: string; versions: string[]; environments: string[] }

export interface DemoData {
  meta: { tool: string; generated_from: string; label: string }
  diff: { old_version: string; new_version: string; changes: Change[] }
  breaking: { findings: Finding[] }
  test: { total: number; passed: number; failed: number; results: TestResultRow[] }
  drift: { findings: DriftRow[] }
  performance: { operations: PerfOp[] }
  coverage: { overall_percent: number; operations: OpCoverage[] }
  rules: { count: number; catalog: RuleRow[] }
  workflow: WorkflowData
  contract: { title: string; version: string; operations: ContractOp[] }
  semver?: SemverVerdict
  changelog?: { markdown: string }
  minimizer?: { attempted: number; results: TestResultRow[] }
  replay?: { manifest: ReplayManifest; dry_run: { target: string; dry_run: boolean; sent: number; skipped: number; statuses: Record<string, number> } }
  org?: {
    org: { id: number; name: string }
    users: OrgUser[]
    contracts: OrgContract[]
    environments: Environment[]
    policies: { name: string; content: string }[]
    approvals: Approval[]
    runs: RunRow[]
    audit_events: AuditEvent[]
    webhooks: Webhook[]
    chain_valid: boolean
  }
  catalog?: { services: CatalogService[] }
}

const cache = new Map<string, Promise<DemoData>>()

/** Load demo data once; `base` allows a self-hosted artifact URL later.
 * Failed loads are never cached — a transient error must not stick for the
 * whole session. */
export function loadData(base = './demo-data.json'): Promise<DemoData> {
  if (!cache.has(base)) {
    const p = fetch(base).then((r) => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      return r.json() as Promise<DemoData>
    })
    p.catch(() => cache.delete(base))
    cache.set(base, p)
  }
  return cache.get(base)!
}

/** Forget cached artifacts (used by tests and manual reload). */
export function resetDataCache(): void {
  cache.clear()
}