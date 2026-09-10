/* Contract pages: explorer, version history, diff, breaking, semver, rules, changelog. */
import {
  Badge,
  Empty,
  Filters,
  MethodTag,
  Missing,
  PageHead,
  SevBadge,
  StatusBadge,
} from '../components/ui'
import { navigate, setParam, useRoute } from '../router'
import type { PageProps } from './types'

export function ExplorerPage({ data }: { data: PageProps['data'] }) {
  const route = useRoute()
  const selected = route.params.get('op')
  if (!data) return <Empty msg="Loading…" />
  const contract = data.contract
  if (!contract) return <Missing section="contract" source={data.source} />
  const op = contract.operations.find((o) => o.key === selected)
  return (
    <>
      <PageHead title="Contract Explorer" sub={`${contract.title} v${contract.version}`} />
      <div className="split">
        <div>
          {contract.operations.map((o) => (
            <div key={o.key} onClick={() => navigate('explorer', { op: o.key })}
              onKeyDown={(e) => e.key === 'Enter' && navigate('explorer', { op: o.key })}
              role="button" tabIndex={0} className={'op-row' + (selected === o.key ? ' selected' : '')}>
              <MethodTag method={o.method} />{' '}
              <code>{o.path}</code> {o.deprecated && <Badge tone="error">deprecated</Badge>}
            </div>
          ))}
        </div>
        <div>
          {!op ? <Empty msg="Select an endpoint." /> : (
            <>
              <h3><MethodTag method={op.method} /> <code>{op.path}</code></h3>
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

function HistoryPageImpl({ data }: { data: PageProps['data'] }) {
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
export const HistoryPage = HistoryPageImpl

export function DiffPage({ data }: { data: PageProps['data'] }) {
  if (!data) return <Empty msg="Loading…" />
  const diff = data.diff
  if (!diff) return <Missing section="diff" source={data.source} />
  return (
    <>
      <PageHead title="Semantic Diff Review" sub={`${diff.old_version} → ${diff.new_version}`} />
      <table><thead><tr><th>ID</th><th>Kind</th><th>Direction</th><th>Description</th></tr></thead>
        <tbody>{diff.changes.map((c) => (
          <tr key={c.id}><td><code>{c.id}</code></td><td>{c.kind}</td><td>{c.direction}</td><td>{c.description}</td></tr>
        ))}</tbody></table>
    </>
  )
}

export function BreakingPage({ data, route }: PageProps) {
  const filter = route.params.get('sev') ?? 'ALL'
  if (!data) return <Empty msg="Loading…" />
  if (!data.breaking) return <Missing section="breaking" source={data.source} />
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

export function SemverPage({ data }: { data: PageProps['data'] }) {
  if (!data?.semver) return <Empty msg="Loading semver verdict…" />
  const v = data.semver
  return (
    <>
      <PageHead title="SemVer Verdict" sub={`v${v.old_version} → v${v.new_version}`} />
      <p>Required bump: <Badge tone={v.required_bump === 'major' ? 'error' : v.required_bump === 'minor' ? 'warn' : 'success'}>{v.required_bump}</Badge></p>
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

export function RulesPage({ data }: { data: PageProps['data'] }) {
  if (!data) return <Empty msg="Loading…" />
  const rules = data.rules
  if (!rules) return <Missing section="rules" source={data.source} />
  return (
    <>
      <PageHead title="Rule Catalog" sub={`${rules.count} direction-aware rules`} />
      <table><thead><tr><th>Rule</th><th>Severity</th><th>Description</th></tr></thead>
        <tbody>{rules.catalog.map((r) => (
          <tr key={r.rule_id}><td><code>{r.rule_id}</code></td><td><SevBadge sev={r.severity} /></td><td>{r.description}</td></tr>
        ))}</tbody></table>
    </>
  )
}

export function ChangelogPage({ data }: { data: PageProps['data'] }) {
  if (!data?.changelog) return <Empty msg="Loading changelog…" />
  return (
    <>
      <PageHead title="Changelog" sub="release-to-release aggregation" />
      <pre className="detail">{data.changelog.markdown}</pre>
    </>
  )
}
