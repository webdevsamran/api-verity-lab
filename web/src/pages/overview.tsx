/* Overview pages: home, catalog, docs, plugins, contributors, about. */
import { Badge, CopyCmd, Empty, PageHead } from '../components/ui'
import type { PageProps } from './types'

export function HomePage({ data }: { data: PageProps['data'] }) {
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

export function CatalogPage({ data }: { data: PageProps['data'] }) {
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

export function DocsPage() {
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

export function PluginsPage() {
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

export function ContributorsPage() {
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

export function AboutPage() {
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
