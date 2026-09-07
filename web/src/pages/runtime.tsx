/* Runtime pages: drift, replay, performance, mock. */
import { METHOD_COLORS, BarChart, Badge, CopyCmd, Empty, PageHead, StatusBadge } from '../components/ui'
import type { PageProps } from './types'

export function DriftPage({ data }: { data: PageProps['data'] }) {
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

export function ReplayPage({ data }: { data: PageProps['data'] }) {
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

export function PerfPage({ data }: { data: PageProps['data'] }) {
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

export function MockPage({ data }: { data: PageProps['data'] }) {
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
