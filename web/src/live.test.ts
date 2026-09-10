/* The live server the dashboard could not read.
 *
 * The server has twenty-nine routes and every page rendered one static file.
 * Wiring them up is the easy half; the half worth testing is what happens to
 * the sections a server has no source for, because filling those with zeros
 * produces a dashboard reporting "0 failures, 100% coverage" for a service
 * nobody has tested -- which is worse than a blank page and much harder to
 * notice.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { loadLive, readLiveConfig, writeLiveConfig, type LiveConfig } from './live'

const CONFIG: LiveConfig = { baseUrl: 'https://verity.test', token: 'tok', orgId: 7 }

type Responder = (path: string) => { status?: number; body: unknown }

function stubFetch(respond: Responder) {
  const calls: { url: string; headers: Record<string, string> }[] = []
  vi.stubGlobal('fetch', (url: string, init?: RequestInit) => {
    const path = url.replace(CONFIG.baseUrl, '')
    calls.push({ url, headers: (init?.headers ?? {}) as Record<string, string> })
    const { status = 200, body } = respond(path)
    return Promise.resolve({
      ok: status < 400,
      status,
      json: () => Promise.resolve(body),
    } as Response)
  })
  return calls
}

const EVERYTHING: Responder = (path) => {
  if (path.includes('/users')) return { body: { users: [{ id: 1, subject: 'a' }] } }
  if (path.includes('/contracts/')) return { body: { findings: [{ rule_id: 'X' }] } }
  if (path.includes('/contracts')) return { body: { contracts: [{ id: 3, title: 'Catalog' }] } }
  if (path.includes('/environments')) return { body: { environments: [{ id: 1 }] } }
  if (path.includes('/policies')) return { body: { policies: [{ name: 'default' }] } }
  if (path.includes('/approvals')) return { body: { approvals: [] } }
  if (path.includes('/runs')) return { body: { runs: [{ id: 9 }] } }
  if (path.includes('/audit')) return { body: { events: [{ id: 1 }], chain_valid: true } }
  if (path.includes('/webhooks')) return { body: { webhooks: [] } }
  return { status: 404, body: {} }
}

afterEach(() => {
  vi.unstubAllGlobals()
  localStorage.clear()
})

describe('what a live server can fill', () => {
  it('reports the sections it actually loaded', async () => {
    stubFetch(EVERYTHING)
    const result = await loadLive(CONFIG)
    expect(result.available).toContain('org')
    expect(result.available).toContain('contracts')
    expect(result.available).toContain('audit')
    expect(result.failed).toEqual([])
  })

  it('leaves the run-derived sections absent rather than empty', async () => {
    // The assertion this whole file exists for. `test: {total: 0, passed: 0}`
    // renders as a green "0/0 passed"; `undefined` renders as "not gathered".
    stubFetch(EVERYTHING)
    const { data } = await loadLive(CONFIG)
    expect(data.test).toBeUndefined()
    expect(data.performance).toBeUndefined()
    expect(data.coverage).toBeUndefined()
    expect(data.drift).toBeUndefined()
    expect(data.workflow).toBeUndefined()
  })

  it('reads the audit chain verdict instead of assuming it', async () => {
    stubFetch((path) =>
      path.includes('/audit')
        ? { body: { events: [], chain_valid: false } }
        : EVERYTHING(path),
    )
    const { data } = await loadLive(CONFIG)
    expect(data.org?.chain_valid).toBe(false)
  })

  it('does not report a chain as valid when the server did not say', async () => {
    stubFetch((path) => (path.includes('/audit') ? { body: { events: [] } } : EVERYTHING(path)))
    const { data } = await loadLive(CONFIG)
    expect(data.org?.chain_valid).toBe(false)
  })

  it('lists policies, which no route could do until the server grew one', async () => {
    // `Store.list_policies` was written and called by nothing: a policy could
    // be fetched by name, which only helps someone who already knows the name.
    stubFetch(EVERYTHING)
    const result = await loadLive(CONFIG)
    expect(result.available).toContain('policies')
    expect(result.data.org?.policies).toHaveLength(1)
  })
})

describe('partial failure', () => {
  it('renders the other sections when one is refused', async () => {
    // A token without audit permission is an ordinary token. Refusing to show
    // the other seven sections would make the dashboard admin-only.
    stubFetch((path) => (path.includes('/audit') ? { status: 403, body: {} } : EVERYTHING(path)))
    const result = await loadLive(CONFIG)
    expect(result.available).toContain('contracts')
    expect(result.failed.map((f) => f.section)).toEqual(['audit'])
    expect(result.failed[0].reason).toContain('403')
  })

  it('names the failure rather than dropping it', async () => {
    stubFetch(() => ({ status: 500, body: {} }))
    const result = await loadLive(CONFIG)
    expect(result.available).toEqual([])
    expect(result.failed.length).toBeGreaterThan(0)
  })
})

describe('requests', () => {
  it('sends the token as a bearer header', async () => {
    const calls = stubFetch(EVERYTHING)
    await loadLive(CONFIG)
    expect(calls[0].headers.authorization).toBe('Bearer tok')
  })

  it('never puts the token in a URL', async () => {
    // A shareable live-dashboard link would write a bearer token into browser
    // history, the access log, and every outbound `Referer` on the page.
    const calls = stubFetch(EVERYTHING)
    await loadLive(CONFIG)
    for (const call of calls) expect(call.url).not.toContain('tok')
  })

  it('scopes the user list to the configured org', async () => {
    const calls = stubFetch(EVERYTHING)
    await loadLive(CONFIG)
    expect(calls.some((c) => c.url.includes('/v1/orgs/7/users'))).toBe(true)
  })

  it('fetches findings for one contract, not for every contract', async () => {
    const many = (path: string) =>
      path.includes('/contracts/')
        ? { body: { findings: [] } }
        : path.includes('/contracts')
          ? { body: { contracts: [{ id: 1 }, { id: 2 }, { id: 3 }] } }
          : EVERYTHING(path)
    const calls = stubFetch(many)
    await loadLive(CONFIG)
    const findingCalls = calls.filter((c) => /\/contracts\/\d+\/findings/.test(c.url))
    expect(findingCalls).toHaveLength(1)
  })

  it('skips findings entirely when there are no contracts', async () => {
    const calls = stubFetch((path) =>
      path.includes('/contracts') ? { body: { contracts: [] } } : EVERYTHING(path),
    )
    const result = await loadLive(CONFIG)
    expect(calls.some((c) => c.url.includes('/findings'))).toBe(false)
    expect(result.available).not.toContain('findings')
  })
})

describe('stored configuration', () => {
  it('round-trips', () => {
    writeLiveConfig(CONFIG)
    expect(readLiveConfig()).toEqual(CONFIG)
  })

  it('strips a trailing slash so paths do not double up', () => {
    writeLiveConfig({ ...CONFIG, baseUrl: 'https://verity.test/' })
    expect(readLiveConfig()?.baseUrl).toBe('https://verity.test')
  })

  it('treats a config with no server as no live source', () => {
    localStorage.setItem('apiverity-live-source', JSON.stringify({ token: 'x' }))
    expect(readLiveConfig()).toBeNull()
  })

  it('treats unreadable storage as no live source rather than crashing', () => {
    localStorage.setItem('apiverity-live-source', 'not json')
    expect(readLiveConfig()).toBeNull()
  })

  it('clears back to the artifact', () => {
    writeLiveConfig(CONFIG)
    writeLiveConfig(null)
    expect(readLiveConfig()).toBeNull()
  })
})
