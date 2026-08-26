import { render, screen, waitFor } from '@testing-library/react'
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { resetDataCache } from './data'

const demoPayload = {
  meta: { tool: 'apiverity', generated_from: 'fixtures', label: 'EXAMPLE RUN' },
  diff: { old_version: '1', new_version: '2', changes: [] },
  breaking: { findings: [] },
  test: { total: 0, passed: 0, failed: 0, results: [] },
  drift: { findings: [] },
  performance: { operations: [] },
  coverage: { overall_percent: 100, operations: [] },
  rules: { count: 0, catalog: [] },
  workflow: { name: 'wf', description: null,
    result: { status: 'pass', steps: [], cleanup_steps: [], variables: {} } },
  contract: { title: 'T', version: '1', operations: [] },
}

beforeAll(() => {
  vi.stubGlobal('fetch', vi.fn(() =>
    Promise.resolve(new Response(JSON.stringify(demoPayload), { status: 200 })),
  ))
})

describe('App shell', () => {
  beforeEach(() => {
    resetDataCache()
    window.location.hash = '#/home'
  })

  it('renders the brand and sidebar navigation links', async () => {
    render(<App />)
    expect(screen.getByText('API Verity Lab')).toBeTruthy()
    for (const label of ['Explorer', 'Breaking Changes', 'Drift',
      'Performance', 'Coverage', 'Docs', 'About']) {
      expect(screen.getByRole('link', { name: label })).toBeTruthy()
    }
    await waitFor(() => expect(screen.getByText(/EXAMPLE RUN/)).toBeTruthy())
  })

  it('navigates to a page via hash routing', async () => {
    render(<App />)
    window.location.hash = '#/breaking'
    await waitFor(() =>
      expect(screen.getByText(/Breaking Changes/)).toBeTruthy())
  })

  it('shows an error banner when demo data fails to load', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response('{}', { status: 500 }))))
    render(<App />)
    await waitFor(() =>
      expect(screen.getByText(/Failed to load demo data/)).toBeTruthy())
  })
})