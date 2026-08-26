/* App shell: theme cycling, sidebar navigation, hash-routed page rendering. */
import { useEffect, useMemo, useState } from 'react'
import { useData } from './hooks/useData'
import { NAV, resolvePage } from './pages'
import { useRoute } from './router'

type ThemeMode = 'dark' | 'light' | 'system'

export default function App() {
  const route = useRoute()
  const { data, error } = useData()
  const [theme, setTheme] = useState<ThemeMode>('dark')
  const [menuOpen, setMenuOpen] = useState(false)
  useEffect(() => {
    const resolved = theme === 'system'
      ? (window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark')
      : theme
    document.documentElement.dataset.theme = resolved
  }, [theme])
  useEffect(() => { setMenuOpen(false); window.scrollTo(0, 0) }, [route.page])

  const Page = resolvePage(route.page)
  const content = useMemo(
    () => <Page data={data} route={route} />,
    [route.page, route.params.toString(), data],
  )

  return (
    <div className="app">
      <header className="topbar">
        <button className="menu-btn" aria-label="toggle navigation"
          aria-expanded={menuOpen} onClick={() => setMenuOpen(!menuOpen)}>☰</button>
        <strong>API Verity Lab</strong>
        <div className="theme-cycle">
          <button aria-label={`theme: ${theme}; click to change`} onClick={() => {
            setTheme(theme === 'dark' ? 'light' : theme === 'light' ? 'system' : 'dark')
          }}>{theme === 'dark' ? '🌙 dark' : theme === 'light' ? '☀️ light' : '💻 system'}</button>
        </div>
      </header>
      <div className="body">
        <nav className={'sidebar' + (menuOpen ? ' open' : '')} aria-label="primary">
          {NAV.map((g) => (
            <div key={g.group}>
              <div className="nav-group">{g.group}</div>
              {g.items.map(([id, label]) => (
                <a key={id} href={`#/${id}`} className={route.page === id ? 'active' : ''}
                  aria-current={route.page === id ? 'page' : undefined}>{label}</a>
              ))}
            </div>
          ))}
        </nav>
        <main>
          {error && <div className="banner error">Failed to load demo data: {error}</div>}
          {content}
        </main>
      </div>
      <footer className="muted">
        Created by @webdevsamran · Apache-2.0 · demo artifacts generated locally from bundled fixtures
      </footer>
    </div>
  )
}
