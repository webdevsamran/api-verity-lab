/* Runtime pages: drift, replay, performance, mock. */
import {
  BarChart,
  Badge,
  CopyCmd,
  Empty,
  MethodTag,
  Missing,
  PageHead,
  StatusBadge,
} from '../components/ui'
import type { ConnectionProbe } from '../data'
import type { PageProps } from './types'

export function DriftPage({ data }: { data: PageProps['data'] }) {
  if (!data) return <Empty msg="Loading…" />
  const drift = data.drift
  if (!drift) return <Missing section="drift" source={data.source} />
  return (
    <>
      <PageHead title="Runtime Drift" sub="declared contract vs observed behavior" />
      {drift.findings.length === 0 ? <Empty msg="No drift detected." /> : (
        <table><thead><tr><th>Rule</th><th>Operation</th><th>Message</th></tr></thead>
          <tbody>{drift.findings.map((d, i) => (
            <tr key={i}><td><code>{d.rule_id}</code></td><td>{d.operation_key}</td><td>{d.message}</td></tr>
          ))}</tbody></table>
      )}
    </>
  )
}

export function ReplayPage({ data }: { data: PageProps['data'] }) {
  if (!data?.replay) return <Empty msg="Loading replay plan…" />
  const m = data.replay.manifest
  const d = data.replay.dry_run
  return (
    <>
      <PageHead title="Traffic Corpus / Replay" sub="dry-run plan only — nothing was sent" />
      <table><tbody>
        <tr><th scope="row">Target</th><td><code>{m.target}</code></td></tr>
        <tr><th scope="row">Safety class</th><td><Badge tone="info">{m.safety_class}</Badge></td></tr>
        <tr><th scope="row">Corpus</th><td><code>{m.corpus}</code> ({m.entries} GET entries)</td></tr>
        <tr><th scope="row">Rate limit</th><td>{m.rate_per_second} req/s max</td></tr>
        <tr><th scope="row">Destructive methods</th><td><StatusBadge ok={!m.destructive_methods_allowed} /> {m.destructive_methods_allowed ? 'allowed' : 'blocked (allowlist required)'}</td></tr>
        <tr><th scope="row">Dry-run result</th><td>{d.sent} sent · {d.skipped} skipped (dry-run)</td></tr>
      </tbody></table>
      <CopyCmd cmd="apiverity replay --corpus demo-corpus.json --target http://127.0.0.1:8080 --dry-run" />
    </>
  )
}

export function PerfPage({ data }: { data: PageProps['data'] }) {
  if (!data) return <Empty msg="Loading…" />
  if (!data.performance) return <Missing section="performance" source={data.source} />
  const ops = data.performance.operations
  const max = Math.max(...ops.map((o) => o.p99_ms), 1)
  return (
    <>
      <PageHead title="Performance" sub="latency percentiles, payload size, and what the connection cost" />
      <BarChart rows={ops.flatMap((o) => [
        { label: `${o.operation_key} p50`, value: o.p50_ms, max },
        { label: `${o.operation_key} p95`, value: o.p95_ms, max },
        { label: `${o.operation_key} p99`, value: o.p99_ms, max },
      ])} />
      <table><thead><tr><th>Operation</th><th>p50 ms</th><th>p95 ms</th><th>p99 ms</th><th>Errors</th><th>req/s</th><th>p95 bytes</th><th>max bytes</th></tr></thead>
        <tbody>{ops.map((o) => (
          <tr key={o.operation_key}><td>{o.operation_key}</td><td>{o.p50_ms.toFixed(1)}</td>
            <td>{o.p95_ms.toFixed(1)}</td><td>{o.p99_ms.toFixed(1)}</td>
            <td>{o.errors}</td><td>{o.throughput_rps.toFixed(1)}</td>
            <td>{fmtBytes(o.bytes_p95)}</td><td>{fmtBytes(o.bytes_max)}</td></tr>
        ))}</tbody></table>
      <ConnectionCard probe={data.performance.connection} />
    </>
  )
}

/* An em dash, not a zero. A report generated before size was measured carries
 * no byte counts at all, and printing `0 B` for one would say the response was
 * empty. */
function fmtBytes(n: number | undefined) {
  if (n === undefined) return '—'
  if (n < 1000) return `${n} B`
  if (n < 1_000_000) return `${(n / 1000).toFixed(1)} kB`
  return `${(n / 1_000_000).toFixed(2)} MB`
}

/**
 * What it cost to open the connection, kept visibly apart from the
 * percentiles.
 *
 * The run pools connections, so the handshake is paid once and is not in any
 * p95 on this page. Somebody reading a 40 ms handshake beside a 12 ms p95 will
 * add them together unless told not to, so the card says so in words.
 */
function ConnectionCard({ probe }: { probe?: ConnectionProbe | null }) {
  if (!probe) return null
  const ms = (v: number | null) => (v === null ? '—' : `${v.toFixed(1)} ms`)
  return (
    <>
      <h3>Connection</h3>
      {probe.error ? (
        <p className="muted">The probe did not complete: <code>{probe.error}</code></p>
      ) : (
        <div className="cards">
          <div className="card"><div className="card-value">{ms(probe.dns_ms)}</div><div className="card-key">DNS</div></div>
          <div className="card"><div className="card-value">{ms(probe.tcp_ms)}</div><div className="card-key">TCP connect</div></div>
          <div className="card">
            <div className="card-value">{ms(probe.tls_ms)}</div>
            <div className="card-key">
              {probe.tls_ms === null ? 'TLS (none — plain HTTP)' : `TLS (${probe.tls_version ?? 'unknown'})`}
            </div>
          </div>
          <div className="card"><div className="card-value">{ms(probe.total_ms)}</div><div className="card-key">Total</div></div>
        </div>
      )}
      <p className="muted">{probe.note}</p>
    </>
  )
}

export function MockPage({ data }: { data: PageProps['data'] }) {
  if (!data) return <Empty msg="Loading…" />
  const contract = data.contract
  if (!contract) return <Missing section="contract" source={data.source} />
  return (
    <>
      <PageHead title="Mock / Virtualization" sub="deterministic schema-driven mock server" />
      <CopyCmd cmd="apiverity mock serve fixtures/apis/crud/openapi.yaml --port 8090 --seed 42" />
      <table><thead><tr><th>Operation</th><th>Method</th><th>Path</th><th>Deterministic responses</th></tr></thead>
        <tbody>{contract.operations.map((o) => (
          <tr key={o.key}><td>{o.key}</td><td><MethodTag method={o.method} /></td>
            <td><code>{o.path}</code></td><td>{o.responses.join(', ')}</td></tr>
        ))}</tbody></table>
    </>
  )
}
