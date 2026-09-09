/* The agent-governance pages, and the distinction that matters most in them:
 * a section that was never generated is not a section that is loading.
 *
 * `web/public/demo-data.json` went stale for months because the generator
 * raised on a renamed field and nothing ran it in CI. Six pages guarded on
 * `data?.replay`-style checks and rendered "Loading…" the whole time, which
 * reads as a broken app rather than an absent input. These pages say which
 * section is missing and how to produce it. */
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { BudgetsPage, FleetPage, PoisoningPage } from './agents'
import type { AgentsSection, DemoData } from '../data'

const AGENTS: AgentsSection = {
  fleet: [
    {
      name: 'orders-mcp',
      endpoint: 'http://127.0.0.1:1/mcp',
      tools_declared: 3,
      tools_served: 3,
      protocol_revision: '2026-07-28',
      era: 'modern',
      auth: { anonymous_access: 'refused-401', target_classification: 'local' },
      findings: [],
      duration_ms: 4,
    },
    {
      name: 'partner-mcp',
      endpoint: 'http://127.0.0.1:2/mcp',
      tools_declared: 3,
      tools_served: 4,
      protocol_revision: '2026-07-28',
      era: 'modern',
      auth: { anonymous_access: 'served', anonymous_tool_count: 4 },
      findings: [
        {
          rule_id: 'MCP-DRIFT-TOOL-UNDECLARED',
          severity: 'WARN',
          message: 'tool export_all_orders is served but absent from the manifest',
          tool: 'export_all_orders',
        },
      ],
      duration_ms: 5,
    },
  ],
  poisoning: {
    manifest: 'fixtures/mcp/tools_poisoned.json',
    tools: 6,
    findings: [
      {
        rule_id: 'MCP-POISON-INVISIBLE-TEXT',
        severity: 'ERROR',
        message: 'carries zero-width space in its description',
        operation_key: 'tool notify_team',
      },
    ],
  },
  budget: {
    window: '1m',
    limits: [
      { operation_key: 'tool cancel_order', max_calls: 0, window: '1m' },
      { operation_key: 'tool search_orders', max_calls: 3, window: '1m' },
    ],
    calls_observed: 7,
    findings: [
      {
        rule_id: 'BUDGET-EXCEEDED',
        severity: 'ERROR',
        message: "'tool search_orders' allows 3 call(s) per 1m and reached 5",
        operation_key: 'tool search_orders',
      },
    ],
  },
}

const withAgents = { agents: AGENTS } as unknown as DemoData
const withoutAgents = {} as unknown as DemoData

describe('a missing section is not a loading state', () => {
  it.each([
    ['fleet', FleetPage],
    ['poisoning', PoisoningPage],
    ['budgets', BudgetsPage],
  ])('%s says the artifact has no agents section', (_name, Page) => {
    render(<Page data={withoutAgents} />)
    expect(screen.getByText(/carries no 'agents' section/)).toBeTruthy()
    expect(screen.queryByText(/Loading/)).toBeNull()
  })

  it.each([
    ['fleet', FleetPage],
    ['poisoning', PoisoningPage],
    ['budgets', BudgetsPage],
  ])('%s still shows a loading state before any data arrives', (_name, Page) => {
    render(<Page data={null as unknown as DemoData} />)
    expect(screen.getByText(/Loading/)).toBeTruthy()
  })
})

describe('fleet', () => {
  it('lists every server twice: once in the table, once with its findings', () => {
    render(<FleetPage data={withAgents} />)
    expect(screen.getAllByText('orders-mcp')).toHaveLength(2)
    expect(screen.getAllByText('partner-mcp')).toHaveLength(2)
  })

  it('says a server matches rather than showing an empty verdict', () => {
    render(<FleetPage data={withAgents} />)
    expect(screen.getByText('matches')).toBeTruthy()
  })

  it('counts servers that answer an unauthenticated caller', () => {
    render(<FleetPage data={withAgents} />)
    expect(screen.getByText('Serving tools anonymously')).toBeTruthy()
    expect(screen.getByText('4 tools without a credential')).toBeTruthy()
  })

  it('grades anonymous access the way the engine graded it', () => {
    /* The same fact is INFO on a laptop and ERROR on a public host. A flat
     * red pass/fail badge told every reader a local dev server was failing,
     * which is how a column stops being read. */
    const graded = {
      agents: {
        ...AGENTS,
        fleet: [
          {
            ...AGENTS.fleet[1],
            findings: [
              {
                rule_id: 'MCP-AUTH-ANONYMOUS-LIST',
                severity: 'INFO' as const,
                message: 'the server returned all 4 tools to a request carrying no credential',
              },
            ],
          },
        ],
      },
    } as unknown as DemoData
    const { container } = render(<FleetPage data={graded} />)
    const badge = [...container.querySelectorAll('.badge')].find((el) =>
      el.textContent?.includes('without a credential'),
    )
    expect(badge?.className).toContain('badge-info')
  })

  it('shows the served and declared counts when they disagree', () => {
    render(<FleetPage data={withAgents} />)
    expect(screen.getByText(/3 declared/)).toBeTruthy()
  })
})

describe('poisoning', () => {
  it('groups findings under the tool they were found on', () => {
    render(<PoisoningPage data={withAgents} />)
    expect(screen.getByText('tool notify_team')).toBeTruthy()
    expect(screen.getByText('MCP-POISON-INVISIBLE-TEXT')).toBeTruthy()
  })

  it('names the manifest that was scanned', () => {
    render(<PoisoningPage data={withAgents} />)
    expect(screen.getByText('fixtures/mcp/tools_poisoned.json')).toBeTruthy()
  })
})

describe('budgets', () => {
  it('renders a zero allowance as never rather than as 0', () => {
    render(<BudgetsPage data={withAgents} />)
    expect(screen.getByText('never')).toBeTruthy()
  })

  it('shows the breach', () => {
    render(<BudgetsPage data={withAgents} />)
    expect(screen.getByText('BUDGET-EXCEEDED')).toBeTruthy()
  })
})
