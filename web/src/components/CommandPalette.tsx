/* Command palette: fuzzy jump to any of the thirty routes.
 *
 * Lazily imported by App.tsx. Most sessions never open it, and the entry chunk
 * is budgeted at 210 kB in scripts/check-bundle.mjs, so it is charged only to
 * the readers who press the key.
 *
 * Focus handling is the part worth reading. A dialog that traps focus but
 * never returns it strands a keyboard user on the page behind it, so the
 * element that had focus when the palette opened is restored on close.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { NAV } from '../pages'

interface Item {
  id: string
  label: string
  group: string
}

const ITEMS: Item[] = NAV.flatMap((g) => g.items.map(([id, label]) => ({ id, label, group: g.group })))

/**
 * Subsequence match, the same rule editors use: "brk" finds "Breaking
 * Changes". Returns a score so better matches sort first -- a run of adjacent
 * characters beats the same letters scattered across the string.
 */
function score(query: string, text: string): number {
  if (!query) return 1
  const q = query.toLowerCase()
  const t = text.toLowerCase()
  let qi = 0
  let points = 0
  let streak = 0
  for (let ti = 0; ti < t.length && qi < q.length; ti++) {
    if (t[ti] === q[qi]) {
      streak += 1
      points += streak + (ti === 0 ? 4 : 0)
      qi += 1
    } else {
      streak = 0
    }
  }
  return qi === q.length ? points : 0
}

export default function CommandPalette({ onClose }: { onClose: () => void }) {
  const [query, setQuery] = useState('')
  const [cursor, setCursor] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLUListElement>(null)
  const returnFocusTo = useRef<HTMLElement | null>(null)

  const hits = useMemo(() => {
    return ITEMS.map((item) => ({ item, s: score(query, `${item.label} ${item.group}`) }))
      .filter((h) => h.s > 0)
      .sort((a, b) => b.s - a.s)
      .slice(0, 12)
      .map((h) => h.item)
  }, [query])

  useEffect(() => {
    returnFocusTo.current = document.activeElement as HTMLElement | null
    inputRef.current?.focus()
    return () => returnFocusTo.current?.focus?.()
  }, [])

  useEffect(() => setCursor(0), [query])

  /* Keep the highlighted row on screen when arrowing past the fold.
   *
   * `scrollIntoView` is optional-chained because it is genuinely absent in
   * some environments -- jsdom does not implement it, and neither do some
   * embedded webviews. Scrolling is a nicety; throwing here would take the
   * whole palette down with it. */
  useEffect(() => {
    const row = listRef.current?.querySelector('[aria-selected="true"]')
    ;(row as HTMLElement | null)?.scrollIntoView?.({ block: 'nearest' })
  }, [cursor])

  const go = (id: string) => {
    window.location.hash = `/${id}`
    onClose()
  }

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      e.preventDefault()
      onClose()
    } else if (e.key === 'ArrowDown') {
      e.preventDefault()
      setCursor((c) => (hits.length ? (c + 1) % hits.length : 0))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setCursor((c) => (hits.length ? (c - 1 + hits.length) % hits.length : 0))
    } else if (e.key === 'Enter' && hits[cursor]) {
      e.preventDefault()
      go(hits[cursor].id)
    }
  }

  return (
    <div
      className="palette-backdrop"
      /* Only a click that both starts and ends on the backdrop dismisses.
       * Using onClick alone closes the dialog when a drag-select inside the
       * input happens to release outside it. */
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div
        className="palette"
        role="dialog"
        aria-modal="true"
        aria-label="Search pages"
        onKeyDown={onKeyDown}
      >
        <input
          ref={inputRef}
          type="text"
          value={query}
          placeholder="Jump to a page…"
          aria-label="Search pages"
          aria-controls="palette-results"
          aria-activedescendant={hits[cursor] ? `palette-${hits[cursor].id}` : undefined}
          onChange={(e) => setQuery(e.target.value)}
        />
        {hits.length === 0 ? (
          <div className="no-hits">No page matches “{query}”.</div>
        ) : (
          <ul id="palette-results" ref={listRef} role="listbox" aria-label="Results">
            {hits.map((item, i) => (
              <li
                key={item.id}
                id={`palette-${item.id}`}
                role="option"
                aria-selected={i === cursor}
                onMouseEnter={() => setCursor(i)}
                onClick={() => go(item.id)}
              >
                <span>{item.label}</span>
                <span className="group">{item.group}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
