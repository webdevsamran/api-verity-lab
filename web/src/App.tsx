import { useEffect, useMemo, useState } from 'react'

/* ---------- types mirroring apiverity result artifacts ---------- */
interface Finding { rule_id: string; severity: 'ERROR' | 'WARN' | 'INFO'; message: string }
interface Change { id: string; kind: string; direction: string; description: string }
interface TestResultRow { case_id: string; operation_key: string; kind: string; status: string; actual_status: number | null; violations: string[] }
interface DriftRow { operation_key: string; rule_id: string; message: string }
interface PerfOp { operation_key: string; p50_ms: number; p95_ms: number; p99_ms: number; errors: number; throughput_rps: number }
interface OpCoverage { operation_key: string; exercised: boolean; declared_statuses: string[]; statuses_seen: number[] }
interface DemoData {
  meta: { tool: string; generated_from: string; label: string }
  diff: { old_version: string; new_version: string; changes: Change[] }
  breaking: { findings: Finding[] }
  test: { total: number; passed: number; failed: number; results: TestResultRow[] }
  drift: { findings: DriftRow[] }
  performance: { operations: PerfOp[] }
  coverage: { overall_percent: number; operations: OpCoverage[] }
}

const SEV_COLORS: Record<string, string> = { ERROR: '#e5484d', WARN: '#f5a623', INFO: '#3b82f6' }

function useDemoData() {
  const [data, setData] = useState<DemoData | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    fetch('./demo-data.json')
      .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then(setData)
      .catch((e) => setError(String(e)))
  }, [])
  return { data, error }
}

/* ---------- shared UI ---------- */
function Badge({ children, color }: { children: React.ReactNode; color?: string }) {
  return <span className="badge" style={color ? { background: color } : undefined}>{children}</span>
}
function SeverityBadge({ sev }: { sev: string }) {
  return <Badge color={SEV_COLORS[sev]}>{sev}</Badge>
}
function Empty({ msg }: { msg: string }) {
  return <div className="empty">{msg}</div>
}
function BarChart({ rows }: { rows: { label: string; value: number; max: number }[] }) {
  return (
    <div className="chart">
      {rows.map((r) => (
        <div key={r.label} className="chart-row">
          <span className="chart-label">{r.label}</span>
          <div className="chart-track">
            <div className="chart-fill" style={{ width: `${Math.min(100, (r.value / r.max) * 100)}%` }} />
          </div>
          <span className="chart-value">{r.value}</span>
        </div>
      ))}
    </div>
  )
}

/* ---------- pages ---------- */
function HomePage({ data }: { data: DemoData | null }) {
  if (!data) return <Empty msg="Loading demo results…" />
  const cards = [
    ['Changes detected', data.diff.changes.length],
    ['Breaking findings', data.breaking.findings.filter((f) => f.severity === 'ERROR').length],
    ['Test cases', `${data.test.passed}/${data.test.total} passed`],
    ['Drift findings', data.drift.findings.length],
    ['Contract coverage', `${data.coverage.overall_percent}%`],
  ] as const
  return (
    <>
      <p className="muted">{data.meta.label}</p>
      <div className="cards">{cards.map(([k, v]) => (
        <div key={k} className="card"><div className="card-value">{v}</div><div className="card-key">{k}</div></div>
      ))}</div>
    </>
  )
}

function DiffPage({ data }: { data: DemoData | null }) {
  if (!data) return <Empty msg="Loading…" />
  return (
    <>
      <h2>Diff Review <span className="muted">{data.diff.old_version} → {data.diff.new_version}</span></h2>
      <table><thead><tr><th>ID</th><th>Kind</th><th>Direction</th><th>Description</th></tr></thead>
        <tbody>{data.diff.changes.map((c) => (
          <tr key={c.id}><td><code>{c.id}</code></td><td>{c.kind}</td><td>{c.direction}</td><td>{c.description}</td></tr>
        ))}</tbody></table>
    </>
  )
}

function BreakingPage({ data }: { data: DemoData | null }) {
  const [filter, setFilter] = useState<string>('ALL')
  if (!data) return <Empty msg="Loading…" />
  const severities = ['ALL', 'ERROR', 'WARN', 'INFO']
  const shown = data.breaking.findings.filter((f) => filter === 'ALL' || f.severity === filter)
  return (
    <>
      <h2>Breaking Changes</h2>
      <div className="filters">{severities.map((s) => (
        <button key={s} className={filter === s ? 'active' : ''} onClick={() => setFilter(s)}>{s}</button>
      ))}</div>
      {shown.length === 0 ? <Empty msg="No findings at this severity." /> : (
        <table><thead><tr><th>Rule</th><th>Severity</th><th>Message</th></tr></thead>
          <tbody>{shown.map((f, i) => (
            <tr key={i}><td><code>{f.rule_id}</code></td><td><SeverityBadge sev={f.severity} /></td><td>{f.message}</td></tr>
          ))}</tbody></table>
      )}
    </>
  )
}

function TestRunsPage({ data }: { data: DemoData | null }) {
  if (!data) return <Empty msg="Loading…" />
  return (
    <>
      <h2>Test Runs <span className="muted">{data.test.passed}/{data.test.total} passed</span></h2>
      <table><thead><tr><th>Case</th><th>Operation</th><th>Kind</th><th>Status</th><th>HTTP</th><th>Violations</th></tr></thead>
        <tbody>{data.test.results.map((r) => (
          <tr key={r.case_id}>
            <td><code>{r.case_id}</code></td><td>{r.operation_key}</td><td>{r.kind}</td>
            <td><Badge color={r.status === 'pass' ? '#2ea043' : '#e5484d'}>{r.status}</Badge></td>
            <td>{r.actual_status ?? '—'}</td><td>{r.violations.join('; ') || '—'}</td>
          </tr>
        ))}</tbody></table>
    </>
  )
}

function DriftPage({ data }: { data: DemoData | null }) {
  if (!data) return <Empty msg="Loading…" />
  return (
    <>
      <h2>Runtime Drift</h2>
      {data.drift.findings.length === 0 ? <Empty msg="No drift detected." /> : (
        <table><thead><tr><th>Rule</th><th>Operation</th><th>Message</th></tr></thead>
          <tbody>{data.drift.findings.map((d, i) => (
            <tr key={i}><td><code>{d.rule_id}</code></td><td>{d.operation_key}</td><td>{d.message}</td></tr>
          ))}</tbody></table>
      )}
    </>
  )
}

function PerfPage({ data }: { data: DemoData | null }) {
  if (!data) return <Empty msg="Loading…" />
  const max = Math.max(...data.performance.operations.map((o) => o.p99_ms), 1)
  return (
    <>
      <h2>Performance (p95 / p99 ms)</h2>
      <BarChart rows={data.performance.operations.map((o) => ({ label: `${o.operation_key} p95`, value: o.p95_ms, max }))} />
      <BarChart rows={data.performance.operations.map((o) => ({ label: `${o.operation_key} p99`, value: o.p99_ms, max }))} />
    </>
  )
}

function CoveragePage({ data }: { data: DemoData | null }) {
  if (!data) return <Empty msg="Loading…" />
  return (
    <>
      <h2>Contract Coverage <span className="muted">{data.coverage.overall_percent}%</span></h2>
      <BarChart rows={data.coverage.operations.map((o) => ({
        label: o.operation_key,
        value: o.statuses_seen.length,
        max: Math.max(o.declared_statuses.length, 1),
      }))} />
      <table><thead><tr><th>Operation</th><th>Exercised</th><th>Declared statuses</th><th>Seen</th></tr></thead>
        <tbody>{data.coverage.operations.map((o) => (
          <tr key={o.operation_key}><td>{o.operation_key}</td>
            <td><Badge color={o.exercised ? '#2ea043' : '#e5484d'}>{o.exercised ? 'yes' : 'no'}</Badge></td>
            <td>{o.declared_statuses.join(', ')}</td><td>{o.statuses_seen.join(', ') || '—'}</td></tr>
        ))}</tbody></table>
    </>
  )
}

/* ---------- shell ---------- */
const PAGES = [
  ['home', 'Home'], ['diff', 'Diff Review'], ['breaking', 'Breaking Changes'],
  ['tests', 'Test Runs'], ['drift', 'Runtime Drift'], ['perf', 'Performance'],
  ['coverage', 'Coverage'],
] as const

export default function App() {
  const [page, setPage] = useState<string>('home')
  const [dark, setDark] = useState(true)
  const { data, error } = useDemoData()
  useEffect(() => {
    document.documentElement.dataset.theme = dark ? 'dark' : 'light'
  }, [dark])
  const content = useMemo(() => {
    switch (page) {
      case 'diff': return <DiffPage data={data} />
      case 'breaking': return <BreakingPage data={data} />
      case 'tests': return <TestRunsPage data={data} />
      case 'drift': return <DriftPage data={data} />
      case 'perf': return <PerfPage data={data} />
      case 'coverage': return <CoveragePage data={data} />
      default: return <HomePage data={data} />
    }
  }, [page, data])

  return (
    <div className="app">
      <header className="topbar">
        <strong>API Verity Lab</strong>
        <nav>{PAGES.map(([id, label]) => (
          <button key={id} className={page === id ? 'active' : ''} onClick={() => setPage(id)}>{label}</button>
        ))}</nav>
        <button aria-label="toggle theme" onClick={() => setDark(!dark)}>{dark ? '☀️' : '🌙'}</button>
      </header>
      {error && <div className="banner error">Failed to load demo data: {error}</div>}
      <main>{content}</main>
      <footer className="muted">Created by @webdevsamran · Apache-2.0 · demo data generated from bundled fixtures</footer>
    </div>
  )
}