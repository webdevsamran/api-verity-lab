/* Page registry and navigation structure for the app shell.
 *
 * Each of the five page groups is a separate chunk, pulled in the first time
 * a route in it is visited (#23). The shell -- header, sidebar, theme, data
 * fetch -- is all the initial download has to carry.
 *
 * The groups are the split boundary rather than individual pages: a group is
 * one module, so `import('./contract')` is one request that serves all seven
 * contract routes. Splitting per page would mean 30 chunks and a fresh
 * round-trip on nearly every click, which is slower in practice than one
 * slightly larger chunk per section.
 */
import { lazy, type ComponentType } from 'react'
import type { PageProps } from './types'

export type { PageProps }

export const NAV: { group: string; items: [string, string][] }[] = [
  { group: 'Overview', items: [['home', 'Home'], ['catalog', 'API Catalog'], ['docs', 'Docs'], ['plugins', 'Plugins'], ['contributors', 'Contributors'], ['about', 'About']] },
  { group: 'Contract', items: [['explorer', 'Explorer'], ['history', 'Version History'], ['diff', 'Diff Review'], ['breaking', 'Breaking Changes'], ['semver', 'SemVer Verdict'], ['changelog', 'Changelog'], ['rules', 'Rules']] },
  { group: 'Testing', items: [['tests', 'Test Runs'], ['fuzz', 'Fuzz Cases'], ['minimizer', 'Minimizer'], ['workflows', 'Workflows'], ['coverage', 'Coverage']] },
  { group: 'Runtime', items: [['drift', 'Drift'], ['replay', 'Replay'], ['perf', 'Performance'], ['mock', 'Mock']] },
  { group: 'Team', items: [['org', 'Org Dashboard'], ['environments', 'Environments'], ['approvals', 'Approvals'], ['policies', 'Policies'], ['jobs', 'Runs/Jobs'], ['audit', 'Audit Log'], ['webhooks', 'Webhooks'], ['users', 'Users']] },
]

/* The import must be a literal inside the arrow for Vite to see the chunk;
 * a variable indirection defeats static analysis and silently un-splits the
 * build back into one file. */
export const CHUNKS = {
  overview: () => import('./overview'),
  contract: () => import('./contract'),
  testing: () => import('./testing'),
  runtime: () => import('./runtime'),
  team: () => import('./team'),
} as const

type GroupName = keyof typeof CHUNKS

/** Route -> the chunk it lives in and the name it is exported under.
 *
 * One table rather than two parallel maps: a route's group and its export
 * name always change together, and keeping them apart gives two places to get
 * it wrong. `lazy()` does not resolve the export name until the route is
 * actually rendered, so a wrong name here is a blank page on click rather
 * than a build error -- `registry.test.ts` checks every entry against the
 * real module so it fails at test time instead. */
export const ROUTE_TABLE: Record<string, readonly [GroupName, string]> = {
  home: ['overview', 'HomePage'],
  catalog: ['overview', 'CatalogPage'],
  docs: ['overview', 'DocsPage'],
  plugins: ['overview', 'PluginsPage'],
  contributors: ['overview', 'ContributorsPage'],
  about: ['overview', 'AboutPage'],
  explorer: ['contract', 'ExplorerPage'],
  history: ['contract', 'HistoryPage'],
  diff: ['contract', 'DiffPage'],
  breaking: ['contract', 'BreakingPage'],
  semver: ['contract', 'SemverPage'],
  changelog: ['contract', 'ChangelogPage'],
  rules: ['contract', 'RulesPage'],
  tests: ['testing', 'TestRunsPage'],
  fuzz: ['testing', 'FuzzPage'],
  minimizer: ['testing', 'MinimizerPage'],
  workflows: ['testing', 'WorkflowsPage'],
  coverage: ['testing', 'CoveragePage'],
  
  drift: ['runtime', 'DriftPage'],
  replay: ['runtime', 'ReplayPage'],
  perf: ['runtime', 'PerfPage'],
  mock: ['runtime', 'MockPage'],
  org: ['team', 'OrgDashboard'],
  environments: ['team', 'EnvironmentsPage'],
  approvals: ['team', 'ApprovalsPage'],
  policies: ['team', 'PoliciesPage'],
  jobs: ['team', 'JobsPage'],
  audit: ['team', 'AuditPage'],
  webhooks: ['team', 'WebhooksPage'],
  users: ['team', 'UsersPage'],
}

/** Wrap one named export of a group module as a lazily-loaded component. */
function page(group: GroupName, exportName: string): ComponentType<PageProps> {
  return lazy(async () => {
    const module = (await CHUNKS[group]()) as unknown as Record<string, unknown>
    const component = module[exportName]
    if (typeof component !== 'function') {
      throw new Error(`page '${exportName}' is missing from the '${group}' chunk`)
    }
    return { default: component as ComponentType<PageProps> }
  })
}

/** Start fetching a route's chunk without rendering it. */
export function prefetchGroup(routeName: string): void {
  const entry = ROUTE_TABLE[routeName]
  if (entry) void CHUNKS[entry[0]]()
}

const PAGES: Record<string, ComponentType<PageProps>> = Object.fromEntries(
  Object.entries(ROUTE_TABLE).map(([route, [group, exportName]]) => [
    route,
    page(group, exportName),
  ]),
)

/** Every route the shell knows about. */
export const ROUTES = Object.keys(PAGES)

/** Resolve a route name to its page component; unknown routes fall back to home. */
export function resolvePage(name: string): ComponentType<PageProps> {
  return PAGES[name] ?? PAGES.home
}
