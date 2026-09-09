import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import ChunkBoundary from './ChunkBoundary'

function Boom({ error }: { error: Error }): never {
  throw error
}

describe('ChunkBoundary', () => {
  it('renders its children when nothing throws', () => {
    render(
      <ChunkBoundary what="This page">
        <p>content</p>
      </ChunkBoundary>,
    )
    expect(screen.getByText('content')).toBeTruthy()
  })

  it('offers a reload when a chunk went stale, rather than blanking the app', () => {
    // The real failure: the site is redeployed while a page is open, so the
    // loaded HTML asks for a chunk filename the server no longer has. Without
    // a boundary the rejected dynamic import unmounts the whole tree and the
    // reader gets a blank page -- which is exactly what pressing Cmd-K did.
    vi.spyOn(console, 'error').mockImplementation(() => {})
    render(
      <ChunkBoundary what="The command palette">
        <Boom error={new TypeError('Failed to fetch dynamically imported module: /assets/x.js')} />
      </ChunkBoundary>,
    )
    expect(screen.getByText(/newer version is available/i)).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Reload' })).toBeTruthy()
    vi.restoreAllMocks()
  })

  it('shows a real error rather than disguising it as a stale chunk', () => {
    // A catch-all that always says "reload" hides genuine bugs behind a
    // plausible excuse, and the reader reloads forever.
    vi.spyOn(console, 'error').mockImplementation(() => {})
    render(
      <ChunkBoundary what="This page">
        <Boom error={new Error('cannot read properties of undefined')} />
      </ChunkBoundary>,
    )
    expect(screen.getByText(/failed to render/i)).toBeTruthy()
    expect(screen.getByText(/cannot read properties of undefined/)).toBeTruthy()
    vi.restoreAllMocks()
  })
})
