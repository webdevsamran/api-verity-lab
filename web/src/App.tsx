/* App shell: theme, navigation, command palette, hash-routed page rendering.
 *
 * Pages load as separate chunks (#23), so this file and the data fetch are all
 * the initial download carries. Hovering or tab-focusing a nav link starts its
 * chunk early, which hides the fetch behind the time it takes to move the
 * pointer the rest of the way. `scripts/check-bundle.mjs` fails the build if a
 * page module is ever statically imported from here.
 *
 * The command palette is lazily loaded for the same reason: it is a few
 * kilobytes that most sessions never open, and putting it in the shell would
 * charge every visitor for it.
 */
import { Suspense, lazy, useCallback, useEffect, useMemo, useState } from 'react'
import ChunkBoundary from './components/ChunkBoundary'
import { SourceContext, Skeleton } from './components/ui'
import { SavedViews } from './components/SavedViews'
import { useData } from './hooks/useData'
import { NAV, prefetchGroup, resolvePage } from './pages'
import { useRoute } from './router'

const CommandPalette = lazy(() => import('./components/CommandPalette'))
const SourcePicker = lazy(() => import('./components/SourcePicker'))

type ThemeMode = 'dark' | 'light' | 'system'

const THEME_KEY = 'apiverity-theme'
const THEME_ORDER: ThemeMode[] = ['system', 'light', 'dark']
const THEME_LABEL: Record<ThemeMode, string> = {
  system: '💻 system',
  light: '☀️ light',
  dark: '🌙 dark',
}

/** Read the stored preference. Mirrors the pre-paint script in index.html. */
function storedTheme(): ThemeMode {
  try {
    const raw = localStorage.getItem(THEME_KEY)
    if (raw === 'dark' || raw === 'light' || raw === 'system') return raw
  } catch {
    /* localStorage throws outright in some privacy modes. */
  }
  return 'system'
}

interface ViewTransitionLike {
  finished?: Promise<unknown>
  ready?: Promise<unknown>
  updateCallbackDone?: Promise<unknown>
}

/**
 * Cross-fade a synchronous DOM change through the View Transitions API.
 *
 * Used for the theme switch, which flips one attribute and repaints the whole
 * page -- exactly the shape this API is for. It is deliberately *not* used for
 * route changes: navigation here is a hash change the browser applies after
 * the click handler returns, so wrapping it would capture a before and an
 * after that are identical and animate nothing. Route changes get the
 * `.page-enter` CSS animation instead, which is keyed on the route and
 * genuinely runs.
 *
 * Feature-detected, and skipped entirely for readers who asked for less
 * motion -- a full-page cross-fade is exactly what that setting means.
 */
function withTransition(apply: () => void) {
  const doc = document as Document & {
    startViewTransition?: (cb: () => void) => ViewTransitionLike
  }
  const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  if (!doc.startViewTransition || reduced) {
    apply()
    return
  }
  const transition = doc.startViewTransition(apply)
  /* Every promise a ViewTransition exposes rejects when the transition is
   * abandoned -- a second one starting, the tab being hidden mid-flight -- and
   * an unhandled rejection is what put "InvalidStateError: Transition was
   * aborted because of invalid state" in the console three times over. An
   * abandoned cross-fade is a normal outcome, not a failure: the DOM change
   * still happened, only the animation did not. */
  for (const settled of [transition?.finished, transition?.ready, transition?.updateCallbackDone]) {
    settled?.catch(() => undefined)
  }
}

export default function App() {
  const route = useRoute()
  const { data, error, retry, live, setLive } = useData()
  const [theme, setTheme] = useState<ThemeMode>(storedTheme)
  const [menuOpen, setMenuOpen] = useState(false)
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [sourceOpen, setSourceOpen] = useState(false)

  /* The attribute write is what gets cross-faded, not the state update.
   *
   * Wrapping `setTheme` in `startViewTransition` instead loses clicks: a
   * transition started while another is still running aborts the first, and
   * the update inside it goes with it. Clicking the toggle three times from
   * "system" landed on "light" rather than back on "system" -- two of the
   * three presses vanished. React state now changes immediately and only the
   * paint is animated, so every press counts and the cross-fade is decoration
   * on top rather than a gate in front. */
  useEffect(() => {
    withTransition(() => {
      if (theme === 'system') delete document.documentElement.dataset.theme
      else document.documentElement.dataset.theme = theme
    })
    try {
      localStorage.setItem(THEME_KEY, theme)
    } catch {
      /* A theme preference is not worth breaking the page over. */
    }
  }, [theme])

  useEffect(() => {
    setMenuOpen(false)
    window.scrollTo(0, 0)
  }, [route.page])

  /* Cmd/Ctrl-K opens the palette, Escape closes it. Bound on the window so it
   * works wherever focus happens to be, and guarded so it does not steal the
   * shortcut from a text field the reader is typing in. */
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null
      const typing = target?.tagName === 'INPUT' || target?.tagName === 'TEXTAREA'
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setPaletteOpen((open) => !open)
      } else if (e.key === '/' && !typing && !paletteOpen) {
        e.preventDefault()
        setPaletteOpen(true)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [paletteOpen])

  const cycleTheme = useCallback(() => {
    setTheme((current) => THEME_ORDER[(THEME_ORDER.indexOf(current) + 1) % THEME_ORDER.length])
  }, [])

  const Page = resolvePage(route.page)
  /* Keyed on the route's serialised params rather than the Route object,
   * which is a fresh instance on every hash event and would re-render every
   * page on every navigation. */
  const content = useMemo(
    () => <Page data={data} route={route} />,
    [Page, route, data],
  )

  return (
    <div className="app">
      <a className="skip-link" href="#main">
        Skip to content
      </a>

      <header className="topbar">
        <button
          type="button"
          className="btn btn-ghost menu-btn"
          aria-label="Toggle navigation"
          aria-expanded={menuOpen}
          aria-controls="primary-nav"
          onClick={() => setMenuOpen(!menuOpen)}
        >
          ☰
        </button>
        <span className="brand">API Verity Lab</span>
        <div className="topbar-actions">
          <SavedViews />
          <button
            type="button"
            className="btn btn-ghost"
            onClick={() => setPaletteOpen(true)}
            aria-label="Search and commands"
          >
            <span aria-hidden="true">⌕</span> Search <kbd>⌘K</kbd>
          </button>
          <button
            type="button"
            className={'btn btn-ghost' + (live ? ' btn-live' : '')}
            onClick={() => setSourceOpen(true)}
            aria-label={
              live ? `Data source: live at ${live.baseUrl}. Activate to change.` : 'Data source: bundled artifact. Activate to change.'
            }
          >
            <span aria-hidden="true">{live ? '\u25CF' : '\u25CB'}</span>{' '}
            {live ? 'Live' : 'Demo data'}
          </button>
          <button
            type="button"
            className="btn btn-ghost"
            onClick={cycleTheme}
            aria-label={`Theme: ${theme}. Activate to change.`}
          >
            {THEME_LABEL[theme]}
          </button>
        </div>
      </header>

      <div className="body">
        <nav
          id="primary-nav"
          className={'sidebar' + (menuOpen ? ' open' : '')}
          aria-label="Primary"
        >
          {NAV.map((g) => (
            <div key={g.group}>
              <div className="nav-group">{g.group}</div>
              {g.items.map(([id, label]) => (
                <a
                  key={id}
                  href={`#/${id}`}
                  className={route.page === id ? 'active' : ''}
                  aria-current={route.page === id ? 'page' : undefined}
                  onMouseEnter={() => prefetchGroup(id)}
                  onFocus={() => prefetchGroup(id)}
                >
                  {label}
                </a>
              ))}
            </div>
          ))}
        </nav>

        <main id="main" tabIndex={-1}>
          {error && (
            <div className="banner error" role="alert">
              <strong>Could not load results.</strong> {error}{' '}
              <button type="button" className="btn" onClick={retry}>
                Retry
              </button>
            </div>
          )}
          {/* Sections the server was asked for and refused. Shown once, at the
            * top, rather than as an error on each page that happens to want
            * one: a token without audit permission is an ordinary token, and
            * seven pages each reporting the same 403 is noise. */}
          {data?.source?.failed && data.source.failed.length > 0 && (
            <div className="banner warn" role="status">
              <strong>Some sections did not load.</strong>{' '}
              {data.source.failed.map((f) => `${f.section} (${f.reason})`).join(', ')}
            </div>
          )}
          <div className="page-enter" key={route.page}>
            <ChunkBoundary what="This page" key={route.page}>
              <SourceContext.Provider value={data?.source}>
                <Suspense fallback={<Skeleton rows={6} cards={4} />}>{content}</Suspense>
              </SourceContext.Provider>
            </ChunkBoundary>
          </div>
        </main>
      </div>

      {paletteOpen && (
        <ChunkBoundary what="The command palette">
          <Suspense fallback={null}>
            <CommandPalette onClose={() => setPaletteOpen(false)} />
          </Suspense>
        </ChunkBoundary>
      )}

      {sourceOpen && (
        <ChunkBoundary what="The data source picker">
          <Suspense fallback={null}>
            <SourcePicker
              live={live}
              onChange={setLive}
              onClose={() => setSourceOpen(false)}
            />
          </Suspense>
        </ChunkBoundary>
      )}

      <footer>
        Created by @webdevsamran · Apache-2.0 ·{' '}
        {live
          ? `live data from ${live.baseUrl}`
          : 'demo artifacts generated locally from bundled fixtures'}
      </footer>
    </div>
  )
}
