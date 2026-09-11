/**
 * Named routes somebody wants to come back to.
 *
 * The URL already carries the whole view -- `#/contract?sev=ERROR` is the
 * page and its filters, and `setParam` writes every change into it -- so a
 * saved view needs to store nothing but a name and that string. Anything more
 * would be a second representation of the same state, and the two would
 * disagree the first time a filter was added.
 *
 * ## Where they live, and what that costs
 *
 * `localStorage`, which means **this browser**. Not the server, not the
 * account, not the other laptop. That is a real limitation and the UI says so
 * rather than letting somebody discover it by opening the dashboard somewhere
 * else; the shareable form of a view is its URL, which is why every one of
 * these is a link.
 *
 * Every read and write is guarded. `localStorage` is not merely empty in a
 * private window -- the accessor itself throws when site data is blocked, and
 * an unguarded read takes the whole dashboard down for a feature nobody was
 * using.
 */

const KEY = 'apiverity.views.v1'

/** Beyond this the list stops being a shortcut and becomes a second nav. */
export const MAX_VIEWS = 20

export interface SavedView {
  name: string
  /** The hash route, without the leading `#`: `/contract?sev=ERROR`. */
  hash: string
}

function isView(value: unknown): value is SavedView {
  const v = value as SavedView
  return Boolean(v) && typeof v.name === 'string' && typeof v.hash === 'string'
}

/**
 * What is saved, or an empty list.
 *
 * A stored value that is not a list of views is discarded rather than
 * crashing: the alternative is a dashboard that will not load until somebody
 * clears site data, over a convenience feature.
 */
export function load(): SavedView[] {
  try {
    const raw = window.localStorage.getItem(KEY)
    if (!raw) return []
    const parsed: unknown = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed.filter(isView).slice(0, MAX_VIEWS) : []
  } catch {
    return []
  }
}

/** True when the write actually happened, so the caller can say if it did not. */
export function save(views: SavedView[]): boolean {
  try {
    window.localStorage.setItem(KEY, JSON.stringify(views.slice(0, MAX_VIEWS)))
    return true
  } catch {
    return false
  }
}

/** The current route, in the form a saved view stores. */
export function currentHash(): string {
  return window.location.hash.replace(/^#/, '') || '/home'
}

/**
 * Add a view, replacing one with the same name.
 *
 * By name, not by hash. Somebody who saves "Errors" twice means to update it;
 * two rows called "Errors" pointing at different filters is a list nobody can
 * use.
 */
export function add(views: SavedView[], view: SavedView): SavedView[] {
  const name = view.name.trim().slice(0, 60)
  if (!name) return views
  const rest = views.filter((v) => v.name !== name)
  return [...rest, { name, hash: view.hash }].slice(-MAX_VIEWS)
}

export function remove(views: SavedView[], name: string): SavedView[] {
  return views.filter((v) => v.name !== name)
}

/**
 * A default name for the route, when somebody does not type one.
 *
 * The page plus its filters, because "contract" and "contract, sev=ERROR" are
 * two different views and a list where both are called "contract" is worse
 * than no list.
 */
export function suggestName(hash: string): string {
  const [path, query = ''] = hash.replace(/^\//, '').split('?')
  const page = path || 'home'
  const params = new URLSearchParams(query)
  const parts = [...params.entries()].map(([k, v]) => `${k}=${v}`)
  return parts.length ? `${page} · ${parts.join(', ')}` : page
}
