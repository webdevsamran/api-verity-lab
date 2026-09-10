/* The blast-radius view, and the one sentence on it that has to be right.
 *
 * An operation with no consumer beside it means one of two opposite things:
 * nobody calls it, or nobody wrote it down. The first says the change is safe
 * to ship; the second says nothing at all. Which one it is depends entirely on
 * whether the registry declared itself complete, so the page has to say — and
 * the test that matters most here is the one that reads that sentence.
 *
 * The rest is the accessibility contract every chart in this app is held to:
 * the drawing is decorative, and the information is in a real table. */
import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { BlastRadiusPage } from './team'
import type { BlastSection, DemoData } from '../data'

const BLAST: BlastSection = {
  registry: 'fixtures/consumers/registry.yaml',
  complete: false,
  consumers_registered: 5,
  unclaimed_operations: ['DELETE /users/{id}'],
  by_operation: {
    'DELETE /users/{id}': [],
    'GET /users': ['checkout-service', 'mobile-v3'],
    'POST /users': ['admin-console'],
  },
  by_consumer: {
    'admin-console': {
      team: '@platform',
      contact: '#platform',
      operations: ['POST /users'],
      findings: 2,
    },
    'checkout-service': {
      team: '@payments',
      contact: '#payments-oncall',
      operations: ['GET /users'],
      findings: 3,
    },
    'mobile-v3': {
      team: '@mobile',
      contact: '#mobile-releases',
      operations: ['GET /users'],
      findings: 3,
    },
  },
  errors_by_operation: { 'DELETE /users/{id}': 1, 'GET /users': 3, 'POST /users': 2 },
}

/* No default argument. `data(undefined)` would fall back to it, and the test
 * for a missing section would quietly assert the populated one. */
const data = (blast?: BlastSection) =>
  ({ meta: { tool: 'apiverity', generated_from: 'fixtures', label: 'demo' }, blast }) as DemoData

describe('BlastRadiusPage', () => {
  it('names the consumers and the teams to tell', () => {
    render(<BlastRadiusPage data={data(BLAST)} />)
    expect(screen.getByRole('button', { name: 'checkout-service' })).toBeTruthy()
    expect(screen.getByText('@payments')).toBeTruthy()
    expect(screen.getByText('#mobile-releases')).toBeTruthy()
  })

  it('counts affected consumers against registered ones, not against all findings', () => {
    render(<BlastRadiusPage data={data(BLAST)} />)
    expect(screen.getByText('3 of 5 registered consumers affected')).toBeTruthy()
  })

  it('says an incomplete registry is incomplete, and that nothing was softened', () => {
    render(<BlastRadiusPage data={data(BLAST)} />)
    expect(screen.getByText('incomplete')).toBeTruthy()
    expect(screen.getByText(/Nothing on this page lowers a severity/)).toBeTruthy()
  })

  it('says the opposite when the registry claims to be complete', () => {
    render(<BlastRadiusPage data={data({ ...BLAST, complete: true })} />)
    expect(screen.getByText('complete')).toBeTruthy()
    expect(screen.getByText(/really is called by nobody registered/)).toBeTruthy()
  })

  it('names the operations that are breaking and unclaimed', () => {
    /* The gap an incomplete registry creates, called out rather than left as
     * an empty cell somebody has to notice. */
    render(<BlastRadiusPage data={data(BLAST)} />)
    const note = screen.getByText(/Unclaimed:/).closest('p')
    expect(note).toBeTruthy()
    expect(within(note as HTMLElement).getByText('DELETE /users/{id}')).toBeTruthy()
  })

  it('shows "none registered" rather than an empty cell', () => {
    render(<BlastRadiusPage data={data(BLAST)} />)
    expect(screen.getByText('none registered')).toBeTruthy()
  })

  it('puts the information in a table, not only in the drawing', () => {
    /* Every chart in this app is held to this: a graph that can only be read
     * by looking at it is a graph half the audience cannot read. */
    const { container } = render(<BlastRadiusPage data={data(BLAST)} />)
    const svg = container.querySelector('svg.blast-graph')
    expect(svg?.getAttribute('aria-hidden')).toBe('true')
    const tables = screen.getAllByRole('table')
    expect(tables.length).toBeGreaterThanOrEqual(2)
    expect(within(tables[0]).getByText('GET /users')).toBeTruthy()
  })

  it('filters to one node and back, from the table', () => {
    render(<BlastRadiusPage data={data(BLAST)} />)
    const row = screen.getByRole('button', { name: 'checkout-service' })
    fireEvent.click(row)
    expect(row.getAttribute('aria-pressed')).toBe('true')
    fireEvent.click(screen.getByRole('button', { name: 'Show everything' }))
    expect(
      screen.getByRole('button', { name: 'checkout-service' }).getAttribute('aria-pressed'),
    ).toBe('false')
  })

  it('dims rather than hides the rest of the graph when one node is selected', () => {
    /* The shape of the whole graph is the context that makes one highlighted
     * path mean anything. */
    const { container } = render(<BlastRadiusPage data={data(BLAST)} />)
    expect(container.querySelectorAll('.dim').length).toBe(0)
    fireEvent.click(screen.getByRole('button', { name: 'checkout-service' }))
    expect(container.querySelectorAll('.dim').length).toBeGreaterThan(0)
  })

  it('says the section is absent rather than sitting on "Loading" forever', () => {
    /* Blast radius is the output of a run against a consumer registry, not
     * server state, so a live dashboard legitimately has none. The demo
     * artifact went stale for months and six pages read as a broken app for
     * the whole of it. */
    render(<BlastRadiusPage data={data()} />)
    expect(screen.getByText(/carries no 'blast' section/)).toBeTruthy()
  })

  it('tells a live dashboard why it has none, in different words', () => {
    render(
      <BlastRadiusPage
        data={
          {
            meta: { tool: 'apiverity', generated_from: 'server', label: 'live' },
            source: { kind: 'live', label: 'https://verity.internal', available: [] },
          } as DemoData
        }
      />,
    )
    expect(screen.getByText(/A live server has no 'blast' data/)).toBeTruthy()
  })
})
