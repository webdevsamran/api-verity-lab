/* Page registry and navigation structure for the app shell. */
import type { ReactElement } from 'react'
import {
  AboutPage, CatalogPage, ContributorsPage, DocsPage, HomePage, PluginsPage,
} from './overview'
import {
  BreakingPage, ChangelogPage, DiffPage, ExplorerPage, HistoryPage, RulesPage, SemverPage,
} from './contract'
import {
  CoveragePage, FuzzPage, MinimizerPage, TestRunsPage, WorkflowsPage,
} from './testing'
import { DriftPage, MockPage, PerfPage, ReplayPage } from './runtime'
import {
  ApprovalsPage, AuditPage, EnvironmentsPage, JobsPage, OrgDashboard,
  PoliciesPage, UsersPage, WebhooksPage,
} from './team'
import type { PageProps } from './types'

export type { PageProps }

export const NAV: { group: string; items: [string, string][] }[] = [
  { group: 'Overview', items: [['home', 'Home'], ['catalog', 'API Catalog'], ['docs', 'Docs'], ['plugins', 'Plugins'], ['contributors', 'Contributors'], ['about', 'About']] },
  { group: 'Contract', items: [['explorer', 'Explorer'], ['history', 'Version History'], ['diff', 'Diff Review'], ['breaking', 'Breaking Changes'], ['semver', 'SemVer Verdict'], ['changelog', 'Changelog'], ['rules', 'Rules']] },
  { group: 'Testing', items: [['tests', 'Test Runs'], ['fuzz', 'Fuzz Cases'], ['minimizer', 'Minimizer'], ['workflows', 'Workflows'], ['coverage', 'Coverage']] },
  { group: 'Runtime', items: [['drift', 'Drift'], ['replay', 'Replay'], ['perf', 'Performance'], ['mock', 'Mock']] },
  { group: 'Team', items: [['org', 'Org Dashboard'], ['environments', 'Environments'], ['approvals', 'Approvals'], ['policies', 'Policies'], ['jobs', 'Runs/Jobs'], ['audit', 'Audit Log'], ['webhooks', 'Webhooks'], ['users', 'Users']] },
]

const PAGES: Record<string, (p: PageProps) => ReactElement> = {
  home: HomePage, catalog: CatalogPage, docs: () => <DocsPage />, plugins: () => <PluginsPage />,
  contributors: () => <ContributorsPage />, about: () => <AboutPage />,
  explorer: ExplorerPage, history: HistoryPage, diff: DiffPage, breaking: BreakingPage,
  semver: SemverPage, rules: RulesPage, changelog: ChangelogPage,
  tests: TestRunsPage, fuzz: FuzzPage, minimizer: MinimizerPage, workflows: WorkflowsPage,
  coverage: CoveragePage, drift: DriftPage, replay: ReplayPage, perf: PerfPage, mock: MockPage,
  org: OrgDashboard, environments: EnvironmentsPage, approvals: ApprovalsPage,
  policies: PoliciesPage, jobs: JobsPage, audit: AuditPage, webhooks: WebhooksPage, users: UsersPage,
}

/** Resolve a route name to its page component; unknown routes fall back to home. */
export function resolvePage(name: string): (p: PageProps) => ReactElement {
  return PAGES[name] ?? HomePage
}
