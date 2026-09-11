/**
 * The saved-view control in the topbar.
 *
 * Every saved view is a real `<a href="#/...">`, not a button that calls
 * `navigate`. Middle-click opens it in a tab, right-click copies the link, and
 * the link is the shareable form of a view -- which matters, because the saved
 * list itself is not shareable at all.
 */
import { useEffect, useRef, useState } from 'react'
import {
  MAX_VIEWS,
  type SavedView,
  add,
  currentHash,
  load,
  remove,
  save,
  suggestName,
} from '../views'

export function SavedViews() {
  const [open, setOpen] = useState(false)
  const [views, setViews] = useState<SavedView[]>([])
  const [name, setName] = useState('')
  const [problem, setProblem] = useState('')
  const panel = useRef<HTMLDivElement>(null)

  // Read on open rather than on mount: another tab may have saved one, and a
  // list that is stale the moment a second tab exists is worse than no list.
  useEffect(() => {
    if (open) {
      setViews(load())
      setName(suggestName(currentHash()))
      setProblem('')
    }
  }, [open])

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    const onClick = (e: MouseEvent) => {
      if (panel.current && !panel.current.contains(e.target as Node)) setOpen(false)
    }
    window.addEventListener('keydown', onKey)
    window.addEventListener('mousedown', onClick)
    return () => {
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('mousedown', onClick)
    }
  }, [open])

  const commit = (next: SavedView[]) => {
    setViews(next)
    if (!save(next)) {
      // Saying nothing here is how a user finds out on their next visit that
      // the thing they saved was never saved.
      setProblem('this browser is not storing site data, so nothing was kept')
    }
  }

  const onSave = () => {
    const trimmed = name.trim()
    if (!trimmed) {
      setProblem('give it a name')
      return
    }
    if (views.length >= MAX_VIEWS && !views.some((v) => v.name === trimmed)) {
      setProblem(`${MAX_VIEWS} is the limit; remove one first`)
      return
    }
    setProblem('')
    commit(add(views, { name: trimmed, hash: currentHash() }))
  }

  return (
    <div className="saved-views" ref={panel}>
      <button
        type="button"
        className="btn btn-ghost"
        aria-expanded={open}
        aria-haspopup="true"
        onClick={() => setOpen(!open)}
      >
        <span aria-hidden="true">★</span> Views
      </button>

      {open && (
        <div className="saved-panel" role="dialog" aria-label="Saved views">
          <label htmlFor="view-name">Save this view</label>
          <div className="saved-add">
            <input
              id="view-name"
              value={name}
              maxLength={60}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && onSave()}
            />
            <button type="button" className="btn" onClick={onSave}>
              Save
            </button>
          </div>
          {problem && (
            <p className="saved-problem" role="status">
              {problem}
            </p>
          )}

          {views.length === 0 ? (
            <p className="muted">Nothing saved yet.</p>
          ) : (
            <ul className="saved-list">
              {views
                .slice()
                .reverse()
                .map((v) => (
                  <li key={v.name}>
                    {/* A real link: middle-click opens a tab, right-click
                      * copies the URL. The URL is the only shareable form of
                      * a view, since the list itself is per-browser. */}
                    <a href={`#${v.hash}`} onClick={() => setOpen(false)}>
                      {v.name}
                    </a>
                    <button
                      type="button"
                      className="linklike"
                      aria-label={`Remove ${v.name}`}
                      onClick={() => commit(remove(views, v.name))}
                    >
                      ×
                    </button>
                  </li>
                ))}
            </ul>
          )}

          {/* Said here rather than discovered on another machine. */}
          <p className="muted saved-note">
            Saved in this browser only. Share a view by copying its link.
          </p>
        </div>
      )}
    </div>
  )
}
