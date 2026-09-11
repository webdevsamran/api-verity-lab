/**
 * The failure a tour usually has is pointing at something that is not there.
 *
 * A step anchored to a selector that matches nothing leaves a highlight at
 * (0, 0) and a caption describing a control the reader cannot see, which is
 * worse than not running at all: it teaches them the tour is lying.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import Tour from './Tour'
import { TOUR_KEY, markTourSeen, tourSeen } from '../tour-state'

/** The controls the real steps are anchored to. */
function topbar(include: string[] = ['source', 'views', 'search', 'theme']) {
  const host = document.createElement('div')
  host.innerHTML = `
    <div class="topbar-actions">
      ${include.includes('source') ? '<button class="btn-ghost" aria-label="Data source: bundled artifact. Activate to change.">Demo</button>' : ''}
      ${include.includes('search') ? '<button class="btn-ghost" aria-label="Search and commands">Search</button>' : ''}
      ${include.includes('theme') ? '<button class="btn-ghost" aria-label="Theme: system. Activate to change.">Theme</button>' : ''}
    </div>
    ${include.includes('views') ? '<div class="saved-views"><button>Views</button></div>' : ''}
  `
  document.body.appendChild(host)
  return host
}

beforeEach(() => {
  window.localStorage.clear()
  document.body.innerHTML = ''
})
afterEach(() => vi.restoreAllMocks())

describe('steps that have nowhere to point', () => {
  it('counts only the steps whose control is on the page', async () => {
    topbar(['source', 'theme'])
    render(<Tour onClose={() => {}} />)
    expect(await screen.findByText('1 of 2')).toBeTruthy()
  })

  it('never shows a step for a missing control', async () => {
    topbar(['search'])
    render(<Tour onClose={() => {}} />)
    expect(await screen.findByText('1 of 1')).toBeTruthy()
    expect(screen.getByRole('heading', { level: 3 }).textContent).toBe('Jump anywhere')
  })

  it('does not run at all when nothing it describes is present', async () => {
    const onClose = vi.fn()
    render(<Tour onClose={onClose} />)
    await waitFor(() => expect(onClose).toHaveBeenCalled())
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('and does not mark itself seen in that case', async () => {
    // Nothing was shown, so nothing was learned. Marking it seen would spend
    // the one chance this has.
    const onClose = vi.fn()
    render(<Tour onClose={onClose} />)
    await waitFor(() => expect(onClose).toHaveBeenCalled())
    expect(window.localStorage.getItem(TOUR_KEY)).toBeNull()
  })
})

describe('walking through it', () => {
  it('advances, goes back, and ends on Done', async () => {
    topbar()
    const onClose = vi.fn()
    render(<Tour onClose={onClose} />)

    expect(await screen.findByText('1 of 4')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    expect(screen.getByText('2 of 4')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Back' }))
    expect(screen.getByText('1 of 4')).toBeTruthy()

    for (let i = 0; i < 3; i++) fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    fireEvent.click(screen.getByRole('button', { name: 'Done' }))
    expect(onClose).toHaveBeenCalled()
  })

  it('has no Back on the first step', async () => {
    topbar()
    render(<Tour onClose={() => {}} />)
    await screen.findByText('1 of 4')
    expect(screen.queryByRole('button', { name: 'Back' })).toBeNull()
  })

  it('closes on Escape and remembers', async () => {
    topbar()
    const onClose = vi.fn()
    render(<Tour onClose={onClose} />)
    await screen.findByText('1 of 4')
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(onClose).toHaveBeenCalled()
    expect(window.localStorage.getItem(TOUR_KEY)).toBe('1')
  })

  it('takes focus, so a keyboard reader is inside it', async () => {
    topbar()
    render(<Tour onClose={() => {}} />)
    await screen.findByText('1 of 4')
    expect(document.activeElement).toBe(screen.getByRole('dialog'))
  })
})

describe('storage that refuses', () => {
  it('says so rather than reappearing silently every visit', async () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    topbar()
    const onClose = vi.fn()
    render(<Tour onClose={onClose} />)
    await screen.findByText('1 of 4')
    fireEvent.click(screen.getByRole('button', { name: 'Skip' }))

    expect(onClose).not.toHaveBeenCalled()
    expect(screen.getByRole('status').textContent).toContain('will show again next visit')
  })
})

describe('tourSeen', () => {
  it('is false before and true after', () => {
    expect(tourSeen()).toBe(false)
    expect(markTourSeen()).toBe(true)
    expect(tourSeen()).toBe(true)
  })

  it('reports seen when storage throws, rather than offering an undismissable tour', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    expect(tourSeen()).toBe(true)
  })
})
