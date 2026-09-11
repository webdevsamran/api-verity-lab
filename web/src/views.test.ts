/**
 * Named routes somebody wants to come back to.
 *
 * Two things matter here and neither is the happy path: a storage accessor
 * that throws must not take the dashboard down, and a stored value that is not
 * what this module wrote must not either.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MAX_VIEWS, add, currentHash, load, remove, save, suggestName } from './views'

const KEY = 'apiverity.views.v1'

beforeEach(() => window.localStorage.clear())
afterEach(() => vi.restoreAllMocks())

describe('round trip', () => {
  it('keeps what was saved', () => {
    expect(save([{ name: 'Errors', hash: '/contract?sev=ERROR' }])).toBe(true)
    expect(load()).toEqual([{ name: 'Errors', hash: '/contract?sev=ERROR' }])
  })

  it('starts empty', () => {
    expect(load()).toEqual([])
  })
})

describe('storage that does not cooperate', () => {
  it('survives a getItem that throws', () => {
    // Not merely empty: with site data blocked the accessor itself throws, and
    // an unguarded read takes the whole dashboard down for a feature nobody
    // was using.
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    expect(load()).toEqual([])
  })

  it('reports a setItem that throws rather than pretending it worked', () => {
    // Returning true here is how somebody finds out on their next visit that
    // the thing they saved was never saved.
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('quota')
    })
    expect(save([{ name: 'x', hash: '/home' }])).toBe(false)
  })

  it('discards a stored value that is not a list of views', () => {
    for (const junk of ['{"not":"a list"}', '[1,2,3]', 'not json at all', '[{"name":1}]']) {
      window.localStorage.setItem(KEY, junk)
      expect(load()).toEqual([])
    }
  })

  it('keeps the entries it recognises and drops the rest', () => {
    window.localStorage.setItem(
      KEY,
      JSON.stringify([{ name: 'ok', hash: '/home' }, { nope: true }]),
    )
    expect(load()).toEqual([{ name: 'ok', hash: '/home' }])
  })
})

describe('add', () => {
  it('replaces a view with the same name', () => {
    // Somebody who saves "Errors" twice means to update it. Two rows called
    // "Errors" pointing at different filters is a list nobody can use.
    const once = add([], { name: 'Errors', hash: '/contract?sev=ERROR' })
    const twice = add(once, { name: 'Errors', hash: '/contract?sev=WARN' })
    expect(twice).toEqual([{ name: 'Errors', hash: '/contract?sev=WARN' }])
  })

  it('trims and caps the name', () => {
    const [view] = add([], { name: '  ' + 'x'.repeat(80) + '  ', hash: '/home' })
    expect(view.name).toHaveLength(60)
  })

  it('ignores a name that is only whitespace', () => {
    expect(add([], { name: '   ', hash: '/home' })).toEqual([])
  })

  it('keeps the most recent when the limit is reached', () => {
    let views: ReturnType<typeof add> = []
    for (let i = 0; i < MAX_VIEWS + 5; i++) {
      views = add(views, { name: `v${i}`, hash: `/home?i=${i}` })
    }
    expect(views).toHaveLength(MAX_VIEWS)
    expect(views[views.length - 1].name).toBe(`v${MAX_VIEWS + 4}`)
    expect(views.some((v) => v.name === 'v0')).toBe(false)
  })
})

describe('remove', () => {
  it('takes out the named one and leaves the rest', () => {
    const views = [
      { name: 'a', hash: '/home' },
      { name: 'b', hash: '/contract' },
    ]
    expect(remove(views, 'a')).toEqual([{ name: 'b', hash: '/contract' }])
    expect(remove(views, 'missing')).toEqual(views)
  })
})

describe('suggestName', () => {
  it('names the page and its filters', () => {
    // "contract" and "contract with sev=ERROR" are two different views, and a
    // list where both are called "contract" is worse than no list.
    expect(suggestName('/contract?sev=ERROR')).toBe('contract · sev=ERROR')
  })

  it('is just the page when there are no filters', () => {
    expect(suggestName('/overview')).toBe('overview')
  })

  it('calls the empty route home', () => {
    expect(suggestName('/')).toBe('home')
  })
})

describe('currentHash', () => {
  it('drops the leading hash', () => {
    window.location.hash = '#/contract?sev=ERROR'
    expect(currentHash()).toBe('/contract?sev=ERROR')
  })

  it('calls an empty location home', () => {
    window.location.hash = ''
    expect(currentHash()).toBe('/home')
  })
})
