/* `lazy()` defers the export lookup to render time, so a wrong export name in
 * ROUTE_TABLE is a blank page on click rather than a build error. TypeScript
 * cannot catch it either -- the name is a string. These tests await every
 * chunk for real and check each name against what the module actually
 * exports, which is the only place that mistake can be caught cheaply. */
import { describe, expect, it } from 'vitest'
import { CHUNKS, NAV, ROUTES, ROUTE_TABLE, resolvePage } from './index'

const navRoutes = NAV.flatMap((group) => group.items.map(([id]) => id))

describe('page registry', () => {
  it('has a component for every route in the navigation', () => {
    expect(navRoutes.filter((id) => !ROUTES.includes(id))).toEqual([])
  })

  it('has no registered page the navigation cannot reach', () => {
    expect(ROUTES.filter((id) => !navRoutes.includes(id))).toEqual([])
  })

  it('lists no route twice', () => {
    expect(navRoutes.length).toBe(new Set(navRoutes).size)
  })

  it('falls back to home for an unknown route', () => {
    expect(resolvePage('no-such-page')).toBe(resolvePage('home'))
  })

  it('resolves each route to a distinct component', () => {
    expect(new Set(ROUTES.map((id) => resolvePage(id))).size).toBe(ROUTES.length)
  })
})

describe('every route resolves to something the chunk really exports', () => {
  it.each(Object.entries(ROUTE_TABLE))(
    '%s -> %s',
    async (_route, [group, exportName]) => {
      const module = (await CHUNKS[group]()) as unknown as Record<string, unknown>
      expect(
        typeof module[exportName],
        `'${exportName}' is not exported by the '${group}' chunk; ` +
          `it has ${Object.keys(module).sort().join(', ')}`,
      ).toBe('function')
    },
  )

  it('leaves no page in a chunk unreachable from any route', async () => {
    const claimed = new Set(Object.values(ROUTE_TABLE).map(([, name]) => name))
    const orphans: string[] = []
    for (const [group, load] of Object.entries(CHUNKS)) {
      const module = (await load()) as unknown as Record<string, unknown>
      for (const name of Object.keys(module)) {
        if (name.endsWith('Page') || name.endsWith('Dashboard')) {
          if (!claimed.has(name)) orphans.push(`${group}.${name}`)
        }
      }
    }
    expect(orphans).toEqual([])
  })
})
