import { useEffect, useMemo, useRef, useState } from 'react'
import { loadData, type DemoData } from './data'
import { navigate, setParam, useRoute } from './router'

/* ---------- shared UI ---------- */
const SEV_COLORS: Record<string, string> = { ERROR: '#e5484d', WARN: '#f5a623', INFO: '#3b82f6' }
const METHOD_COLORS: Record<string, string> = {
  GET: '#3b82f6', POST: '#2ea043', PUT: '#f5a623', PATCH: '#a855f7', DELETE: '#e5484d',
}

function Badge({ children, color }: { children: React.ReactNode; color?: string }) {
  return <span className="badge" style={color ? { background: color } : undefined}>{children}</span>
}
function SevBadge({ sev }: { sev: string }) {
  return <Badge color={SEV_COLORS[sev]}>{sev}</Badge>
}
function StatusBadge({ ok }: { ok: boolean }) {
  return <Badge color={ok ? '#2ea043' : '#e5484d'}>{ok ? 'pass' : 'fail'}</Badge>
}
function Empty({ msg }: { msg: string }) {
  return <div className="empty">{msg}</div>
}
function DemoTag() {
  return <Badge color="#6b7280">DEMO DATA</Badge>
}
function PageHead({ title, sub }: { title: string; sub?: string }) {
  return (
    <>
      <h2>{title} {sub && <span className="muted">{sub}</span>}</h2>
      <p className="muted"><DemoTag /> static demo artifacts generated from bundled fixtures — run the CLI for your own APIs.</p>
    </>
  )
}
function BarChart({ rows }: { rows: { label: string; value: number; max: number }[] }) {
  return (
    <div className="chart" role="img" aria-label="bar chart">
      {rows.map((r) => (
        <div key={r.label} className="chart-row">
          <span className="chart-label">{r.label}</span>
          <div className="chart-track">
            <div className="chart-fill" style={{ width: `${Math.min(100, (r.value / Math.max(r.max, 1)) * 100)}%` }} />
          </div>
          <span className="chart-value">{r.value}</span>
        </div>
      ))}
    </div>
  )
}
/** Simple windowed list for large tables (virtualization). */
function VirtualRows<T>({ items, rowHeight = 36, render }: {
  items: T[]; rowHeight?: number; render: (item: T, index: number) => React.ReactNode
}) {
  const [scrollTop, setScrollTop] = useState(0)
  const ref = useRef<HTMLDivElement>(null)
  const viewport = 480
  if (items.length <= 40) return <>{items.map((it, i) => render(it, i))}</>
  const start = Math.max(0, Math.floor(scrollTop / rowHeight) - 5)
  const end = Math.min(items.length, start + Math.ceil(viewport / rowHeight) + 10)
  return (
    <div ref={ref} style={{ maxHeight: viewport, overflowY: 'auto' }}
      onScroll={(e) => setScrollTop((e.target as HTMLDivElement).scrollTop)}>
      <div style={{ height: items.length * rowHeight, position: 'relative' }}>
        <div style={{ position: 'absolute', top: start * rowHeight }}>
          {items.slice(start, end).map((it, i) => render(it, start + i))}
        </div>
      </div>
    </div>
  )
}
function Filters({ options, active, onPick }: { options: string[]; active: string; onPick: (v: string) => void }) {
  return (
    <div className="filters" role="group" aria-label="filters">
      {options.map((o) => (
        <button key={o} className={active === o ? 'active' : ''} onClick={() => onPick(o)}>{o}</button>
      ))}
    </div>
  )
}
function CopyCmd({ cmd }: { cmd: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <button onClick={() => {
      navigator.clipboard?.writeText(cmd).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500) })
    }}>{copied ? 'copied!' : `copy: ${cmd}`}</button>
  )
}
function useData(): { data: DemoData | null; error: string | null } {
  const [data, setData] = useState<DemoData | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    loadData().then(setData).catch((e) => setError(String(e)))
  }, [])
  return { data, error }
}

/* ---------- overview pages ---------- */
function HomePage({ data }: { data: DemoData | null }) {
  if (!data) return <Empty msg="Loading demo results…" />
  const cards: [string, string | number][] = [
    ['Changes detected', data.diff.changes.length],
    ['Breaking findings', data.breaking.findings.filter((f) => f.severity === 'ERROR').length],
    ['Test cases', `${data.test.passed}/${data.test.total} passed`],
    ['Drift findings', data.drift.findings.length],
    ['Contract coverage', `${data.coverage.overall_percent}%`],
    ['Services in catalog', data.catalog?.services.length ?? 0],
  ]
  return (
    <>
      <PageHead title="API Verity Lab" sub={data.meta.label} />
      <div className="cards">{cards.map(([k, v]) => (
        <div key={k} className="card"><div className="card-value">{v}</div><div className="card-key">{k}</div></div>
      ))}</div>
      <h3>Signature workflows</h3>
      <ul>
        <li><code>apiverity diff</code> / <code>breaking</code> — semantic source-aware comparison & explainable compatibility rules</li>
        <li><code>apiverity test</code> / <code>workflow</code> — deterministic schema-derived and stateful verification</li>
        <li><code>apiverity drift</code> / <code>replay</code> / <code>regression</code> — runtime truth vs declared contracts, safely</li>
        <li><code>can-i-deploy</code> — connect contract changes to registered consumers</li>
      </ul>
      <CopyCmd cmd="pip install apiverity-lab && apiverity --help" />
    </>
  )
}

function CatalogPage({ data }: { data: DemoData | null }) {
  if (!data?.catalog) return <Empty msg="Loading catalog…" />
  return (
    <>
      <PageHead title="API Catalog" />
      <table><thead><tr><th>Service</th><th>Product</th><th>Protocol</th><th>Lifecycle</th><th>Owner</th><th>Versions</th><th>Environments</th></tr></thead>
        <tbody>{data.catalog.services.map((s) => (
          <tr key={s.title}><td>{s.title}</td><td>{s.product}</td><td>{s.protocol}</td>
            <td><Badge color="#3b82f6">{s.lifecycle}</Badge></td><td>{s.owner}</td>
            <td>{s.versions.join(', ')}</td><td>{s.environments.join(', ')}</td></tr>
        ))}</tbody></table>
    </>
  )
}

/* ---------- contract pages ---------- */
function ExplorerPage({ data }: { data: DemoData | null }) {
  const route = useRoute()
  const selected = route.params.get('op')
  if (!data) return <Empty msg="Loading…" />
  const op = data.contract.operations.find((o) => o.key === selected)
  return (
    <>
      <PageHead title="Contract Explorer" sub={`${data.contract.title} v${data.contract.version}`} />
      <div className="split">
        <div>
          {data.contract.operations.map((o) => (
            <div key={o.key} onClick={() => navigate('explorer', { op: o.key })}
              onKeyDown={(e) => e.key === 'Enter' && navigate('explorer', { op: o.key })}
              role="button" tabIndex={0} className={'op-row' + (selected === o.key ? ' selected' : '')}>
              <Badge color={METHOD_COLORS[o.method]}>{o.method}</Badge>{' '}
              <code>{o.path}</code> {o.deprecated && <Badge color="#e5484d">deprecated</Badge>}
            </div>
          ))}
        </div>
        <div>
          {!op ? <Empty msg="Select an endpoint." /> : (
            <>
              <h3><Badge color={METHOD_COLORS[op.method]}>{op.method}</Badge> <code>{op.path}</code></h3>
              <p>{op.summary ?? 'No summary.'}</p>
              <p><strong>Parameters:</strong> {op.parameters.join(', ') || '—'}</p>
              <p><strong>Responses:</strong> {op.responses.join(', ')}</p>
            </>
          )}
        </div>
      </div>
    </>
  )
}

function HistoryPage({ data }: { data: DemoData | null }) {
  if (!data?.org) return <Empty msg="Loading version history…" />
  const versions = data.org.contracts.filter((c) => c.title === 'Catalog')
  return (
    <>
      <PageHead title="Contract Version History" sub="Catalog" />
      <table><thead><tr><th>Version</th><th>Protocol</th><th>Checksum</th><th>Published by</th><th>When (UTC)</th></tr></thead>
        <tbody>{versions.map((c) => (
          <tr key={c.id}><td>v{c.version}</td><td>{c.protocol}</td>
            <td><code title={c.checksum}>{c.checksum.slice(0, 12)}…</code></td>
            <td>{c.published_by}</td><td>{new Date(c.published_at).toISOString()}</td></tr>
        ))}</tbody></table>
    </>
  )
}

function DiffPage({ data }: { data: DemoData | null }) {
  if (!data) return <Empty msg="Loading…" />
  return (
    <>
      <PageHead title="Semantic Diff Review" sub={`${data.diff.old_version} → ${data.diff.new_version}`} />
      <table><thead><tr><th>ID</th><th>Kind</th><th>Direction</th><th>Description</th></tr></thead>
        <tbody>{data.diff.changes.map((c) => (
          <tr key={c.id}><td><code>{c.id}</code></td><td>{c.kind}</td><td>{c.direction}</td><td>{c.description}</td></tr>
        ))}</tbody></table>
    </>
  )
}

function BreakingPage({ data, route }: { data: DemoData | null; route: ReturnType<typeof useRoute> }) {
  const filter = route.params.get('sev') ?? 'ALL'
  if (!data) return <Empty msg="Loading…" />
  const shown = data.breaking.findings.filter((f) => filter === 'ALL' || f.severity === filter)
  return (
    <>
      <PageHead title="Breaking Changes" />
      <Filters options={['ALL', 'ERROR', 'WARN', 'INFO']} active={filter}
        onPick={(v) => setParam(route, 'sev', v === 'ALL' ? '' : v)} />
      {shown.length === 0 ? <Empty msg="No findings at this severity." /> : (
        <table><thead><tr><th>Rule</th><th>Severity</th><th>Message</th></tr></thead>
          <tbody>{shown.map((f, i) => (
            <tr key={i}><td><code>{f.rule_id}</code></td><td><SevBadge sev={f.severity} /></td><td>{f.message}</td></tr>
          ))}</tbody></table>
      )}
    </>
  )
}

function SemverPage({ data }: { data: DemoData | null }) {
  if (!data?.semver) return <Empty msg="Loading semver verdict…" />
  const v = data.semver
  return (
    <>
      <PageHead title="SemVer Verdict" sub={`v${v.old_version} → v${v.new_version}`} />
      <p>Required bump: <Badge color={v.required_bump === 'major' ? '#e5484d' : v.required_bump === 'minor' ? '#f5a623' : '#2ea043'}>{v.required_bump}</Badge></p>
      <p>Policy compliant: <StatusBadge ok={v.compliant} /></p>
      {v.findings.length > 0 && (
        <table><thead><tr><th>Rule</th><th>Severity</th><th>Message</th></tr></thead>
          <tbody>{v.findings.map((f, i) => (
            <tr key={i}><td><code>{f.rule_id}</code></td><td><SevBadge sev={f.severity} /></td><td>{f.message}</td></tr>
          ))}</tbody></table>
      )}
    </>
  )
}

function RulesPage({ data }: { data: DemoData | null }) {
  if (!data) return <Empty msg="Loading…" />
  return (
    <>
      <PageHead title="Rule Catalog" sub={`${data.rules.count} direction-aware rules`} />
      <table><thead><tr><th>Rule</th><th>Severity</th><th>Description</th></tr></thead>
        <tbody>{data.rules.catalog.map((r) => (
          <tr key={r.rule_id}><td><code>{r.rule_id}</code></td><td><SevBadge sev={r.severity} /></td><td>{r.description}</td></tr>
        ))}</tbody></table>
    </>
  )
}

function ChangelogPage({ data }: { data: DemoData | null }) {
  if (!data?.changelog) return <Empty msg="Loading changelog…" />
  return (
    <>
      <PageHead title="Changelog" sub="release-to-release aggregation" />
      <pre className="detail">{data.changelog.markdown}</pre>
    </>
  )
}

/* ---------- testing pages ---------- */
function TestRunsPage({ data }: { data: DemoData | null }) {
  if (!data) return <Empty msg="Loading…" />
  return (
    <>
      <PageHead title="Test Runs" sub={`${data.test.passed}/${data.test.total} passed`} />
      <table><thead><tr><th>Case</th><th>Operation</th><th>Kind</th><th>Status</th><th>HTTP</th><th>Violations</th></tr></thead>
        <tbody><VirtualRows items={data.test.results} render={(r) => (
          <tr key={r.case_id}>
            <td><code>{r.case_id}</code></td><td>{r.operation_key}</td><td>{r.kind}</td>
            <td><StatusBadge ok={r.status === 'pass'} /></td>
            <td>{r.actual_status ?? '—'}</td><td>{r.violations.join('; ') || '—'}</td>
          </tr>
        )} /></tbody></table>
    </>
  )
}

function FuzzPage({ data }: { data: DemoData | null }) {
  if (!data) return <Empty msg="Loading…" />
  const failures = data.test.results.filter((r) => r.status !== 'pass')
  return (
    <>
      <PageHead title="Generated / Fuzz Cases" sub={`${failures.length} of ${data.test.total} failing`} />
      {failures.length === 0 ? <Empty msg="No failures — every generated case behaved per contract." /> : (
        <table><thead><tr><th>Case</th><th>Operation</th><th>Kind</th><th>HTTP</th><th>Violations</th></tr></thead>
          <tbody>{failures.map((r) => (
            <tr key={r.case_id}><td><code>{r.case_id}</code></td><td>{r.operation_key}</td><td>{r.kind}</td>
              <td>{r.actual_status ?? '—'}</td><td>{r.violations.join('; ')}</td></tr>
          ))}</tbody></table>
      )}
    </>
  )
}

function MinimizerPage({ data }: { data: DemoData | null }) {
  if (!data?.minimizer) return <Empty msg="Loading minimizer results…" />
  return (
    <>
      <PageHead title="Failure Minimizer" sub={`${data.minimizer.attempted} cases minimized`} />
      {data.minimizer.results.length === 0 ? <Empty msg="No failing cases to minimize in this demo run." /> : (
        <table><thead><tr><th>Case</th><th>Operation</th><th>Status</th><th>Reproduction</th></tr></thead>
          <tbody>{data.minimizer.results.map((r) => (
            <tr key={r.case_id}><td><code>{r.case_id}</code></td><td>{r.operation_key}</td>
              <td><StatusBadge ok={r.status === 'pass'} /></td>
              <td><code>{r.reproduction ?? '—'}</code></td></tr>
          ))}</tbody></table>
      )}
    </>
  )
}

function WorkflowsPage({ data }: { data: DemoData | null }) {
  if (!data) return <Empty msg="Loading…" />
  const wf = data.workflow.result
  return (
    <>
      <PageHead title="Stateful Workflow Explorer" sub={data.workflow.name} />
      <p>{data.workflow.description}</p>
      <p>Status: <StatusBadge ok={wf.status === 'pass'} /></p>
      <h3>Steps</h3>
      <table><thead><tr><th>Step</th><th>Status</th><th>HTTP</th><th>ms</th><th>Notes</th></tr></thead>
        <tbody>{wf.steps.map((s) => (
          <tr key={s.step}><td>{s.step}</td><td><StatusBadge ok={s.status === 'pass'} /></td>
            <td>{s.actual_status ?? '—'}</td><td>{s.duration_ms}</td><td>{s.violations.join('; ') || '—'}</td></tr>
        ))}</tbody></table>
      {wf.cleanup_steps.length > 0 && (<>
        <h3>Cleanup</h3>
        <table><thead><tr><th>Step</th><th>Status</th><th>HTTP</th></tr></thead>
          <tbody>{wf.cleanup_steps.map((s) => (
            <tr key={s.step}><td>{s.step}</td><td>{s.status}</td><td>{s.actual_status ?? '—'}</td></tr>
          ))}</tbody></table>
      </>)}
    </>
  )
}

function CoveragePage({ data }: { data: DemoData | null }) {
  if (!data) return <Empty msg="Loading…" />
  return (
    <>
      <PageHead title="Contract Coverage" sub={`${data.coverage.overall_percent}% overall`} />
      <BarChart rows={data.coverage.operations.map((o) => ({
        label: o.operation_key,
        value: o.statuses_seen.length,
        max: Math.max(o.declared_statuses.length, 1),
      }))} />
      <table><thead><tr><th>Operation</th><th>Exercised</th><th>Declared statuses</th><th>Seen</th></tr></thead>
        <tbody>{data.coverage.operations.map((o) => (
          <tr key={o.operation_key}><td>{o.operation_key}</td>
            <td><StatusBadge ok={o.exercised} /></td>
            <td>{o.declared_statuses.join(', ')}</td><td>{o.statuses_seen.join(', ') || '—'}</td></tr>
        ))}</tbody></table>
    </>
  )
}

/* ---------- runtime pages ---------- */
function DriftPage({ data }: { data: DemoData | null }) {
  if (!data) return <Empty msg="Loading…" />
  return (
    <>
      <PageHead title="Runtime Drift" sub="declared contract vs observed behavior" />
      {data.drift.findings.length === 0 ? <Empty msg="No drift detected." /> : (
        <table><thead><tr><th>Rule</th><th>Operation</th><th>Message</th></tr></thead>
          <tbody>{data.drift.findings.map((d, i) => (
            <tr key={i}><td><code>{d.rule_id}</code></td><td>{d.operation_key}</td><td>{d.message}</td></tr>
          ))}</tbody></table>
      )}
    </>
  )
}

function ReplayPage({ data }: { data: DemoData | null }) {
  if (!data?.replay) return <Empty msg="Loading replay plan…" />
  const m = data.replay.manifest
  const d = data.replay.dry_run
  return (
    <>
      <PageHead title="Traffic Corpus / Replay" sub="dry-run plan only — nothing was sent" />
      <table><tbody>
        <tr><th scope="row">Target</th><td><code>{m.target}</code></td></tr>
        <tr><th scope="row">Safety class</th><td><Badge color="#3b82f6">{m.safety_class}</Badge></td></tr>
        <tr><th scope="row">Corpus</th><td><code>{m.corpus}</code> ({m.entries} GET entries)</td></tr>
        <tr><th scope="row">Rate limit</th><td>{m.rate_per_second} req/s max</td></tr>
        <tr><th scope="row">Destructive methods</th><td><StatusBadge ok={!m.destructive_methods_allowed} /> {m.destructive_methods_allowed ? 'allowed' : 'blocked (allowlist required)'}</td></tr>
        <tr><th scope="row">Dry-run result</th><td>{d.sent} sent · {d.skipped} skipped (dry-run)</td></tr>
      </tbody></table>
      <CopyCmd cmd="apiverity replay --corpus demo-corpus.json --target http://127.0.0.1:8080 --dry-run" />
    </>
  )
}

function PerfPage({ data }: { data: DemoData | null }) {
  if (!data) return <Empty msg="Loading…" />
  const ops = data.performance.operations
  const max = Math.max(...ops.map((o) => o.p99_ms), 1)
  return (
    <>
      <PageHead title="Performance" sub="latency percentiles from measured mock runs" />
      <BarChart rows={ops.flatMap((o) => [
        { label: `${o.operation_key} p50`, value: o.p50_ms, max },
        { label: `${o.operation_key} p95`, value: o.p95_ms, max },
        { label: `${o.operation_key} p99`, value: o.p99_ms, max },
      ])} />
      <table><thead><tr><th>Operation</th><th>p50 ms</th><th>p95 ms</th><th>p99 ms</th><th>Errors</th><th>req/s</th></tr></thead>
        <tbody>{ops.map((o) => (
          <tr key={o.operation_key}><td>{o.operation_key}</td><td>{o.p50_ms.toFixed(1)}</td>
            <td>{o.p95_ms.toFixed(1)}</td><td>{o.p99_ms.toFixed(1)}</td>
            <td>{o.errors}</td><td>{o.throughput_rps.toFixed(1)}</td></tr>
        ))}</tbody></table>
    </>
  )
}

function MockPage({ data }: { data: DemoData | null }) {
  if (!data) return <Empty msg="Loading…" />
  return (
    <>
      <PageHead title="Mock / Virtualization" sub="deterministic schema-driven mock server" />
      <CopyCmd cmd="apiverity mock serve fixtures/apis/crud/openapi.yaml --port 8090 --seed 42" />
      <table><thead><tr><th>Operation</th><th>Method</th><th>Path</th><th>Deterministic responses</th></tr></thead>
        <tbody>{data.contract.operations.map((o) => (
          <tr key={o.key}><td>{o.key}</td><td><Badge color={METHOD_COLORS[o.method]}>{o.method}</Badge></td>
            <td><code>{o.path}</code></td><td>{o.responses.join(', ')}</td></tr>
        ))}</tbody></table>
    </>
  )
}

/* ---------- team / enterprise pages ---------- */
function OrgDashboard({ data }: { data: DemoData | null }) {
  if (!data?.org) return <Empty msg="Loading organization snapshot…" />
  const org = data.org
  const cards: [string, string | number][] = [
    ['Organization', org.org.name],
    ['Members', org.users.filter((u) => u.kind === 'user').length],
    ['Service accounts', org.users.filter((u) => u.kind === 'service_account').length],
    ['Contracts published', org.contracts.length],
    ['Environments', org.environments.length],
    ['Audit chain valid', org.chain_valid ? 'yes' : 'TAMPERED'],
  ]
  return (
    <>
      <PageHead title="Organization Dashboard" sub={org.org.name} />
      <div className="cards">{cards.map(([k, v]) => (
        <div key={k} className="card"><div className="card-value">{String(v)}</div><div className="card-key">{k}</div></div>
      ))}</div>
    </>
  )
}

function EnvironmentsPage({ data }: { data: DemoData | null }) {
  if (!data?.org) return <Empty msg="Loading environments…" />
  return (
    <>
      <PageHead title="Environments / Targets" sub="ownership + safety classification" />
      <table><thead><tr><th>Name</th><th>Base URL</th><th>Safety class</th><th>Owner</th><th>Allowed modes</th></tr></thead>
        <tbody>{data.org.environments.map((e) => (
          <tr key={e.id}><td>{e.name}</td><td><code>{e.base_url}</code></td>
            <td><Badge color={e.safety_class === 'dev' ? '#2ea043' : '#f5a623'}>{e.safety_class}</Badge></td>
            <td>{e.owner ?? '—'}</td><td>{e.allowed_modes}</td></tr>
        ))}</tbody></table>
    </>
  )
}

function ApprovalsPage({ data }: { data: DemoData | null }) {
  if (!data?.org) return <Empty msg="Loading approvals…" />
  return (
    <>
      <PageHead title="Approvals / Exceptions" sub="intentional breaking-change signoff" />
      {data.org.approvals.length === 0 ? <Empty msg="No approvals recorded." /> : (
        <table><thead><tr><th>Contract</th><th>Transition</th><th>Justification</th><th>Status</th><th>Requested by</th><th>Decided by</th></tr></thead>
          <tbody>{data.org.approvals.map((a) => (
            <tr key={a.id}><td>{a.contract_title}</td><td>v{a.from_version} → v{a.to_version}</td>
              <td>{a.justification}</td>
              <td><Badge color={a.status === 'approved' ? '#2ea043' : a.status === 'rejected' ? '#e5484d' : '#f5a623'}>{a.status}</Badge></td>
              <td>{a.requested_by}</td><td>{a.decided_by ?? '—'}</td></tr>
          ))}</tbody></table>
      )}
    </>
  )
}

function PoliciesPage({ data }: { data: DemoData | null }) {
  if (!data?.org) return <Empty msg="Loading policies…" />
  return (
    <>
      <PageHead title="Policies" sub="policy-as-code" />
      {data.org.policies.map((p) => (
        <div key={p.name}>
          <h3><code>{p.name}</code></h3>
          <pre className="detail">{p.content}</pre>
        </div>
      ))}
    </>
  )
}

function JobsPage({ data }: { data: DemoData | null }) {
  if (!data?.org) return <Empty msg="Loading runs…" />
  return (
    <>
      <PageHead title="Runs / Jobs" sub="verification + load executions" />
      <table><thead><tr><th>ID</th><th>Kind</th><th>Status</th><th>Requested by</th><th>Verifies</th><th>Environment</th></tr></thead>
        <tbody>{data.org.runs.map((r) => (
          <tr key={r.id}><td>#{r.id}</td><td>{r.kind}</td>
            <td><Badge color={r.status === 'passed' ? '#2ea043' : r.status === 'running' ? '#3b82f6' : '#e5484d'}>{r.status}</Badge></td>
            <td>{r.requested_by}</td><td>{r.verification_for ?? '—'}</td><td>{r.environment ?? '—'}</td></tr>
        ))}</tbody></table>
    </>
  )
}

function AuditPage({ data }: { data: DemoData | null }) {
  if (!data?.org) return <Empty msg="Loading audit log…" />
  return (
    <>
      <PageHead title="Audit Log" sub={data.org.chain_valid ? 'hash chain verified ✓' : 'CHAIN TAMPERED'} />
      <table><thead><tr><th>#</th><th>When (UTC)</th><th>Actor</th><th>Action</th><th>Target</th><th>Entry hash</th></tr></thead>
        <tbody>{data.org.audit_events.map((e) => (
          <tr key={e.id}><td>{e.id}</td><td>{new Date(e.ts).toISOString()}</td><td>{e.actor}</td>
            <td><code>{e.action}</code></td><td>{e.target}</td>
            <td><code title={e.entry_hash}>{e.entry_hash.slice(0, 10)}…</code></td></tr>
        ))}</tbody></table>
    </>
  )
}

function WebhooksPage({ data }: { data: DemoData | null }) {
  if (!data?.org) return <Empty msg="Loading webhooks…" />
  return (
    <>
      <PageHead title="Webhooks / Integrations" sub="HMAC-signed deliveries" />
      <table><thead><tr><th>URL</th><th>Secret ref</th><th>Events</th><th>Active</th></tr></thead>
        <tbody>{data.org.webhooks.map((w) => (
          <tr key={w.id}><td><code>{w.url}</code></td><td><code>{w.secret_ref}</code></td>
            <td>{w.events.join(', ')}</td><td>{w.active ? 'yes' : 'no'}</td></tr>
        ))}</tbody></table>
    </>
  )
}

function UsersPage({ data }: { data: DemoData | null }) {
  if (!data?.org) return <Empty msg="Loading users…" />
  return (
    <>
      <PageHead title="Users / Teams / Service Accounts" sub="RBAC roles" />
      <table><thead><tr><th>Subject</th><th>Name</th><th>Role</th><th>Kind</th></tr></thead>
        <tbody>{data.org.users.map((u) => (
          <tr key={u.id}><td><code>{u.subject}</code></td><td>{u.display_name}</td>
            <td><Badge color={u.role === 'owner' ? '#a855f7' : u.role === 'admin' ? '#3b82f6' : '#6b7280'}>{u.role}</Badge></td>
            <td>{u.kind}</td></tr>
        ))}</tbody></table>
    </>
  )
}

/* ---------- static pages ---------- */
function DocsPage() {
  return (
    <>
      <h2>Docs</h2>
      <ul>
        <li><strong>Getting started</strong> — README quickstart, install, first diff in under a minute</li>
        <li><strong>Rule catalog</strong> — docs/rule-catalog.md (direction-aware breaking rules + semver policy)</li>
        <li><strong>Spec support</strong> — PROTOCOL_SUPPORT.md (verified levels per protocol)</li>
        <li><strong>Safety model</strong> — SAFETY_MODEL.md (target authorization, replay/load protections)</li>
        <li><strong>Privacy & redaction</strong> — docs/privacy.md</li>
        <li><strong>CI integration</strong> — docs/ci.md (PR gate, JUnit/SARIF, perf budgets)</li>
        <li><strong>Workflow authoring</strong> — docs/workflow-authoring.md</li>
        <li><strong>Self-hosting</strong> — docs/self-hosting.md (server, RBAC, audit, webhooks)</li>
        <li><strong>Plugins</strong> — docs/plugins.md (plugin API v2, conformance kit, scaffolder)</li>
        <li><strong>Competitive analysis</strong> — docs/competitive-analysis.md</li>
      </ul>
    </>
  )
}

const BUILTIN_PLUGINS = [
  ['core-rules', 'rules', 'Direction-aware breaking-change rule pack'],
  ['security-checks', 'checks', 'Defensive security rule pack (auth, CORS, secrets)'],
  ['schema-case-generator', 'generators', 'Deterministic positive/negative case generation'],
  ['report-exporters', 'exporters', 'JSON / JUnit / SARIF / Markdown report export'],
  ['httpx-transport', 'transports', 'Default HTTP transport with safe defaults'],
]

function PluginsPage() {
  return (
    <>
      <PageHead title="Plugin Catalog" sub="plugin API v2 — manifests, capability negotiation, conformance kit" />
      <table><thead><tr><th>Plugin</th><th>Capability</th><th>Description</th></tr></thead>
        <tbody>{BUILTIN_PLUGINS.map(([name, cap, desc]) => (
          <tr key={name}><td><code>{name}</code></td><td><Badge color="#3b82f6">{cap}</Badge></td><td>{desc}</td></tr>
        ))}</tbody></table>
      <CopyCmd cmd="python -m apiverity.plugins.scaffold my-plugin ./plugins" />
    </>
  )
}

function ContributorsPage() {
  return (
    <>
      <h2>Contributors</h2>
      <div className="card">
        <div className="card-value">@webdevsamran</div>
        <div className="card-key">Creator · Founder · Lead Maintainer</div>
      </div>
      <p className="muted">See CONTRIBUTING.md to join — good first tasks are listed in ISSUES.md.</p>
    </>
  )
}

function AboutPage() {
  return (
    <>
      <h2>About</h2>
      <p>
        API Verity Lab is a local-first API reliability laboratory unifying contract
        governance, breaking-change analysis, schema-driven/stateful testing, runtime
        drift detection, safe traffic replay and performance regression for OpenAPI,
        GraphQL and gRPC — one shared contract model instead of a bag of wrappers.
      </p>
      <p className="muted">Apache-2.0 · Created by @webdevsamran · No cloud component required.</p>
    </>
  )
}

/* ---------- shell ---------- */
type PageProps = { data: DemoData | null; route: ReturnType<typeof useRoute> }

const NAV: { group: string; items: [string, string][] }[] = [
  { group: 'Overview', items: [['home', 'Home'], ['catalog', 'API Catalog'], ['docs', 'Docs'], ['plugins', 'Plugins'], ['contributors', 'Contributors'], ['about', 'About']] },
  { group: 'Contract', items: [['explorer', 'Explorer'], ['history', 'Version History'], ['diff', 'Diff Review'], ['breaking', 'Breaking Changes'], ['semver', 'SemVer Verdict'], ['changelog', 'Changelog'], ['rules', 'Rules']] },
  { group: 'Testing', items: [['tests', 'Test Runs'], ['fuzz', 'Fuzz Cases'], ['minimizer', 'Minimizer'], ['workflows', 'Workflows'], ['coverage', 'Coverage']] },
  { group: 'Runtime', items: [['drift', 'Drift'], ['replay', 'Replay'], ['perf', 'Performance'], ['mock', 'Mock']] },
  { group: 'Team', items: [['org', 'Org Dashboard'], ['environments', 'Environments'], ['approvals', 'Approvals'], ['policies', 'Policies'], ['jobs', 'Runs/Jobs'], ['audit', 'Audit Log'], ['webhooks', 'Webhooks'], ['users', 'Users']] },
]

const PAGES: Record<string, (p: PageProps) => React.ReactElement> = {
  home: HomePage, catalog: CatalogPage, docs: () => <DocsPage />, plugins: () => <PluginsPage />,
  contributors: () => <ContributorsPage />, about: () => <AboutPage />,
  explorer: ExplorerPage, history: HistoryPage, diff: DiffPage, breaking: BreakingPage,
  semver: SemverPage, rules: RulesPage, changelog: ChangelogPage,
  tests: TestRunsPage, fuzz: FuzzPage, minimizer: MinimizerPage, workflows: WorkflowsPage,
  coverage: CoveragePage, drift: DriftPage, replay: ReplayPage, perf: PerfPage, mock: MockPage,
  org: OrgDashboard, environments: EnvironmentsPage, approvals: ApprovalsPage,
  policies: PoliciesPage, jobs: JobsPage, audit: AuditPage, webhooks: WebhooksPage, users: UsersPage,
}

type ThemeMode = 'dark' | 'light' | 'system'

export default function App() {
  const route = useRoute()
  const { data, error } = useData()
  const [theme, setTheme] = useState<ThemeMode>('dark')
  const [menuOpen, setMenuOpen] = useState(false)
  useEffect(() => {
    const resolved = theme === 'system'
      ? (window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark')
      : theme
    document.documentElement.dataset.theme = resolved
  }, [theme])
  useEffect(() => { setMenuOpen(false); window.scrollTo(0, 0) }, [route.page])

  const Page = PAGES[route.page] ?? HomePage
  const content = useMemo(
    () => <Page data={data} route={route} />,
    [route.page, route.params.toString(), data],
  )

  return (
    <div className="app">
      <header className="topbar">
        <button className="menu-btn" aria-label="toggle navigation"
          aria-expanded={menuOpen} onClick={() => setMenuOpen(!menuOpen)}>☰</button>
        <strong>API Verity Lab</strong>
        <div className="theme-cycle">
          <button aria-label={`theme: ${theme}; click to change`} onClick={() => {
            setTheme(theme === 'dark' ? 'light' : theme === 'light' ? 'system' : 'dark')
          }}>{theme === 'dark' ? '🌙 dark' : theme === 'light' ? '☀️ light' : '💻 system'}</button>
        </div>
      </header>
      <div className="body">
        <nav className={'sidebar' + (menuOpen ? ' open' : '')} aria-label="primary">
          {NAV.map((g) => (
            <div key={g.group}>
              <div className="nav-group">{g.group}</div>
              {g.items.map(([id, label]) => (
                <a key={id} href={`#/${id}`} className={route.page === id ? 'active' : ''}
                  aria-current={route.page === id ? 'page' : undefined}>{label}</a>
              ))}
            </div>
          ))}
        </nav>
        <main>
          {error && <div className="banner error">Failed to load demo data: {error}</div>}
          {content}
        </main>
      </div>
      <footer className="muted">
        Created by @webdevsamran · Apache-2.0 · demo artifacts generated locally from bundled fixtures
      </footer>
    </div>
  )
}