/* Team / enterprise pages: org dashboard, environments, approvals, policies,
 * runs/jobs, audit log, webhooks, users. */
import { Badge, Empty, PageHead } from '../components/ui'
import type { PageProps } from './types'

export function OrgDashboard({ data }: { data: PageProps['data'] }) {
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

export function EnvironmentsPage({ data }: { data: PageProps['data'] }) {
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

export function ApprovalsPage({ data }: { data: PageProps['data'] }) {
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

export function PoliciesPage({ data }: { data: PageProps['data'] }) {
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

export function JobsPage({ data }: { data: PageProps['data'] }) {
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

export function AuditPage({ data }: { data: PageProps['data'] }) {
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

export function WebhooksPage({ data }: { data: PageProps['data'] }) {
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

export function UsersPage({ data }: { data: PageProps['data'] }) {
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
