import { render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import App from './App'

// Provide demo data so the app renders its real content path.
beforeAll(() => {
  vi.stubGlobal('fetch', vi.fn(() =>
    Promise.resolve(new Response(JSON.stringify({
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
    }), { status: 200 })),
  ))
})

describe('App shell', () => {
  it('renders the brand and all navigation pages', async () => {
    render(<App />)
    expect(screen.getByText('API Verity Lab')).toBeTruthy()
    for (const label of ['Contract Explorer', 'Breaking Changes', 'Runtime Drift',
      'Performance', 'Coverage', 'Docs', 'About']) {
      expect(screen.getByRole('button', { name: label })).toBeTruthy()
    }
    await waitFor(() => expect(screen.getByText(/EXAMPLE RUN/)).toBeTruthy())
  })

  it('shows an error banner when demo data fails to load', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response('{}', { status: 500 }))))
    render(<App />)
    await waitFor(() =>
      expect(screen.getByText(/Failed to load demo data/)).toBeTruthy())
  })
})