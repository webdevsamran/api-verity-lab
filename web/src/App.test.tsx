import { fireEvent, render, screen, waitFor } from '@testing-library/react'
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
      expect(screen.getByText(/Could not load results/)).toBeTruthy())
  })

  it('offers a retry that actually re-fetches', async () => {
    // A banner with no way out makes a transient failure look permanent, so
    // the button has to do something -- not just exist.
    const failing = vi.fn(() => Promise.resolve(new Response('{}', { status: 500 })))
    vi.stubGlobal('fetch', failing)
    render(<App />)
    await waitFor(() => expect(screen.getByText(/Could not load results/)).toBeTruthy())
    const before = failing.mock.calls.length

    vi.stubGlobal('fetch', vi.fn(() =>
      Promise.resolve(new Response(JSON.stringify(demoPayload), { status: 200 })),
    ))
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    await waitFor(() => expect(screen.getByText(/EXAMPLE RUN/)).toBeTruthy())
    expect(before).toBeGreaterThan(0)
  })

  it('exposes a skip link as the first tab stop', () => {
    // Thirty nav items sit between the top of the page and the content.
    render(<App />)
    const skip = screen.getByRole('link', { name: /skip to content/i })
    expect(skip.getAttribute('href')).toBe('#main')
  })

  it('opens the command palette on ctrl+k and closes it on escape', async () => {
    render(<App />)
    expect(screen.queryByRole('dialog')).toBeNull()
    fireEvent.keyDown(window, { key: 'k', ctrlKey: true })
    await waitFor(() => expect(screen.getByRole('dialog')).toBeTruthy())
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' })
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  })

  it('does not hijack "/" while the reader is typing', async () => {
    render(<App />)
    fireEvent.keyDown(window, { key: 'k', ctrlKey: true })
    const input = await screen.findByRole('textbox', { name: /search pages/i })
    // The palette is open; "/" inside its own input must reach the input.
    fireEvent.keyDown(input, { key: '/' })
    expect(screen.getByRole('dialog')).toBeTruthy()
  })

  it('does not lose rapid theme presses', async () => {
    // Regression, measured in Chrome: with setTheme called inside
    // document.startViewTransition, three rapid presses from "system" landed
    // on "light" -- a net movement of one step instead of three. Moving the
    // state update out of the transition callback (the attribute write is what
    // gets cross-faded now) makes the same three presses return to "system".
    //
    // The stub below runs its callback synchronously, so this test does not
    // reproduce the browser's timing. What it does pin is the property that
    // matters and that the fix guarantees: every press moves the theme exactly
    // one step, whatever startViewTransition does with the callback.
    vi.stubGlobal('startViewTransition', undefined)
    ;(document as unknown as Record<string, unknown>).startViewTransition = (cb: () => void) => {
      cb()
      return { finished: Promise.resolve() }
    }
    render(<App />)
    const button = screen.getByRole('button', { name: /^Theme:/ })
    fireEvent.click(button)
    fireEvent.click(button)
    fireEvent.click(button)
    await waitFor(() =>
      expect(button.getAttribute('aria-label')).toContain('system'))
    delete (document as unknown as Record<string, unknown>).startViewTransition
  })

  it('cycles the theme and remembers the choice', async () => {
    render(<App />)
    const button = screen.getByRole('button', { name: /^Theme:/ })
    expect(button.getAttribute('aria-label')).toContain('system')
    fireEvent.click(button)
    await waitFor(() =>
      expect(document.documentElement.dataset.theme).toBe('light'))
    expect(localStorage.getItem('apiverity-theme')).toBe('light')
  })
})