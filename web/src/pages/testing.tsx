/* Testing pages: test runs, fuzz failures, minimizer, workflows, coverage. */
import {
  BarChart,
  Empty,
  Missing,
  PageHead,
  StatusBadge,
  VirtualRows,
} from '../components/ui'
import type { PageProps } from './types'

export function TestRunsPage({ data }: { data: PageProps['data'] }) {
  if (!data) return <Empty msg="Loading…" />
  const test = data.test
  if (!test) return <Missing section="test" source={data.source} />
  return (
    <>
      <PageHead title="Test Runs" sub={`${test.passed}/${test.total} passed`} />
      <table><thead><tr><th>Case</th><th>Operation</th><th>Kind</th><th>Status</th><th>HTTP</th><th>Violations</th></tr></thead>
        <tbody><VirtualRows items={test.results} render={(r) => (
          <tr key={r.case_id}>
            <td><code>{r.case_id}</code></td><td>{r.operation_key}</td><td>{r.kind}</td>
            <td><StatusBadge ok={r.status === 'pass'} /></td>
            <td>{r.actual_status ?? '—'}</td><td>{r.violations.join('; ') || '—'}</td>
          </tr>
        )} /></tbody></table>
    </>
  )
}

export function FuzzPage({ data }: { data: PageProps['data'] }) {
  if (!data) return <Empty msg="Loading…" />
  const test = data.test
  if (!test) return <Missing section="test" source={data.source} />
  const failures = test.results.filter((r) => r.status !== 'pass')
  return (
    <>
      <PageHead title="Generated / Fuzz Cases" sub={`${failures.length} of ${test.total} failing`} />
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

export function MinimizerPage({ data }: { data: PageProps['data'] }) {
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

export function WorkflowsPage({ data }: { data: PageProps['data'] }) {
  if (!data) return <Empty msg="Loading…" />
  const workflow = data.workflow
  if (!workflow) return <Missing section="workflow" source={data.source} />
  const wf = workflow.result
  return (
    <>
      <PageHead title="Stateful Workflow Explorer" sub={workflow.name} />
      <p>{workflow.description}</p>
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

export function CoveragePage({ data }: { data: PageProps['data'] }) {
  if (!data) return <Empty msg="Loading…" />
  const coverage = data.coverage
  if (!coverage) return <Missing section="coverage" source={data.source} />
  return (
    <>
      <PageHead title="Contract Coverage" sub={`${coverage.overall_percent}% overall`} />
      <BarChart rows={coverage.operations.map((o) => ({
        label: o.operation_key,
        value: o.statuses_seen.length,
        max: Math.max(o.declared_statuses.length, 1),
      }))} />
      <table><thead><tr><th>Operation</th><th>Exercised</th><th>Declared statuses</th><th>Seen</th></tr></thead>
        <tbody>{coverage.operations.map((o) => (
          <tr key={o.operation_key}><td>{o.operation_key}</td>
            <td><StatusBadge ok={o.exercised} /></td>
            <td>{o.declared_statuses.join(', ')}</td><td>{o.statuses_seen.join(', ') || '—'}</td></tr>
        ))}</tbody></table>
    </>
  )
}
