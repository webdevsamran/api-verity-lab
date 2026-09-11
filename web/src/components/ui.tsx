/* Shared presentational building blocks used by every page.
 *
 * Colour lives in styles.css, not here. This file used to carry
 * `SEV_COLORS = { ERROR: '#e5484d', ... }` and pass the hex through an inline
 * `style`, which meant severity had two sources of truth and only the CSS one
 * followed the theme -- the same red on a white page and a near-black one.
 * Components now emit a class and the stylesheet decides.
 *
 * Charts are hand-drawn SVG for the same reason the app has no router
 * library: `scripts/check-bundle.mjs` budgets the entry chunk at 210 kB, and
 * a charting dependency costs more than every page in this app combined.
 */
import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
  type RefObject,
} from 'react'
import type { DataSource } from '../data'

/* ------------------------------------------------------------- badges */

type Severity = 'ERROR' | 'WARN' | 'INFO' | string

const SEV_CLASS: Record<string, string> = {
  ERROR: 'badge-error',
  WARN: 'badge-warn',
  INFO: 'badge-info',
}

export function Badge({ children, tone = 'neutral' }: { children: ReactNode; tone?: string }) {
  return <span className={`badge badge-${tone}`}>{children}</span>
}

export function SevBadge({ sev }: { sev: Severity }) {
  return <span className={`badge ${SEV_CLASS[sev] ?? 'badge-neutral'}`}>{sev}</span>
}

export function StatusBadge({ ok }: { ok: boolean }) {
  return <span className={`badge ${ok ? 'badge-success' : 'badge-error'}`}>{ok ? 'pass' : 'fail'}</span>
}

export function MethodTag({ method }: { method: string }) {
  const m = (method || '').toUpperCase()
  return <span className={`method method-${m.toLowerCase()}`}>{m}</span>
}

export function DemoTag() {
  return <span className="badge badge-neutral">DEMO DATA</span>
}

/**
 * Which source the app is reading, for the components that describe it.
 *
 * A context rather than a prop threaded through twenty `PageHead` calls: the
 * note under every heading said "static demo artifacts generated from bundled
 * fixtures", which becomes a false statement on every page the moment the
 * dashboard is pointed at a real server -- and a dashboard that misdescribes
 * its own data is the one defect this project cannot afford.
 */
export const SourceContext = createContext<DataSource | undefined>(undefined)

/* --------------------------------------------------------- page frame */

/** One line describing where the numbers on this page came from. */
export function SourceNote() {
  const source = useContext(SourceContext)
  if (source?.kind === 'live') {
    return (
      <>
        <span className="badge badge-live">LIVE</span> read from{' '}
        <code>{source.label}</code> just now.
      </>
    )
  }
  return (
    <>
      <DemoTag /> static demo artifacts generated from bundled fixtures — run the CLI for your
      own APIs.
    </>
  )
}

export function PageHead({ title, sub, note }: { title: string; sub?: string; note?: ReactNode }) {
  return (
    <>
      <h2>
        {title} {sub && <span className="muted">{sub}</span>}
      </h2>
      <p className="muted">{note ?? <SourceNote />}</p>
    </>
  )
}

/* ---------------------------------------------------------- stat cards */

export interface Stat {
  label: string
  value: string | number
  /** Rendered small and dimmed beside the value: "passed", "%", "ms". */
  suffix?: string
  tone?: 'error' | 'warn' | 'success' | 'info'
  /** Optional trend, drawn as a sparkline under the value. */
  trend?: number[]
}

/**
 * One headline number.
 *
 * `suffix` exists because the value and its unit were previously concatenated
 * into one string -- "4/17 passed" rendered at 30px, wrapped onto two lines,
 * and pushed the card taller than its neighbours. The number is the thing to
 * read at a glance; the word beside it is context, and typography should say
 * so.
 */
export function StatCard({ label, value, suffix, tone, trend }: Stat) {
  return (
    <div className="card">
      <div className="card-value" style={tone ? { color: `var(--${tone})` } : undefined}>
        {value}
        {suffix && (
          /* A word gets a space, a symbol does not: "4/17 passed" but "100%".
           * Emitting one literal space for both rendered "100 %". */
          <span className={'card-suffix' + (/^[a-z]/i.test(suffix) ? ' spaced' : '')}>{suffix}</span>
        )}
      </div>
      <div className="card-key">{label}</div>
      {trend && trend.length > 1 && <Sparkline values={trend} />}
    </div>
  )
}

export function StatGrid({ stats }: { stats: Stat[] }) {
  return (
    <div className="cards">
      {stats.map((s) => (
        <StatCard key={s.label} {...s} />
      ))}
    </div>
  )
}

/* ------------------------------------------------------ loading states */

/** Shaped like the content it replaces, so the layout does not jump. */
export function Skeleton({ rows = 5, cards = 0 }: { rows?: number; cards?: number }) {
  return (
    <div role="status" aria-live="polite" aria-busy="true">
      <span className="visually-hidden">Loading…</span>
      {cards > 0 && (
        <div className="cards" aria-hidden="true">
          {Array.from({ length: cards }, (_, i) => (
            <div key={i} className="skeleton skeleton-card" />
          ))}
        </div>
      )}
      <div aria-hidden="true">
        {Array.from({ length: rows }, (_, i) => (
          <div key={i} className="skeleton skeleton-row" style={{ width: `${100 - i * 4}%` }} />
        ))}
      </div>
    </div>
  )
}

export function Empty({ msg, hint }: { msg: string; hint?: ReactNode }) {
  return (
    <div className="empty">
      <h3>{msg}</h3>
      {hint && <p className="muted">{hint}</p>}
    </div>
  )
}

/**
 * A section the current data source does not carry.
 *
 * Distinct from `Empty`, and the distinction is the point: "no findings" is
 * good news, and "this source has no findings section" is no news at all. They
 * render identically as a blank table, which is how six pages sat on a loading
 * state against a stale artifact for months.
 *
 * The hint depends on where the data came from. Telling someone pointed at a
 * live server to regenerate a demo file sends them somewhere that cannot help.
 */
export function Missing({ section, source }: { section: string; source?: DataSource }) {
  const live = source?.kind === 'live'
  return (
    <Empty
      msg={
        live
          ? `A live server has no '${section}' data.`
          : `This artifact carries no '${section}' section.`
      }
      hint={
        live
          ? 'It is the output of a run, not server state. Run the command and publish the artifact, or switch this dashboard back to an artifact source.'
          : 'Regenerate it with scripts/generate-demo-data.py, or point the dashboard at a run that produced one.'
      }
    />
  )
}

/* --------------------------------------------------------------- charts */

export interface BarRow {
  label: string
  value: number
  max: number
  tone?: 'error' | 'warn' | 'info'
}

/** Horizontal bars. Kept as CSS widths -- it is a list, not a plot. */
export function BarChart({ rows, unit = '' }: { rows: BarRow[]; unit?: string }) {
  if (!rows.length) return <Empty msg="Nothing to chart yet" />
  return (
    <div className="chart">
      <table className="visually-hidden">
        <caption>Chart data</caption>
        <thead>
          <tr>
            <th>Item</th>
            <th>Value</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.label}>
              <td>{r.label}</td>
              <td>
                {r.value}
                {unit}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div aria-hidden="true">
        {rows.map((r) => (
          <div key={r.label} className="chart-row">
            <span className="chart-label">{r.label}</span>
            <div className="chart-track">
              <div
                className="chart-fill"
                style={{
                  width: `${Math.min(100, (r.value / Math.max(r.max, 1)) * 100)}%`,
                  background: r.tone ? `var(--${r.tone})` : undefined,
                }}
              />
            </div>
            <span className="chart-value">
              {r.value}
              {unit}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

export interface SeriesPoint {
  label: string
  value: number
}

/**
 * A line plot with an optional budget threshold.
 *
 * The accessible equivalent is a real table, not an aria-label: a label can
 * say "latency over time" but cannot tell anyone what p95 was on Tuesday.
 */
export function LineChart({
  points,
  unit = '',
  budget,
  caption,
  height = 160,
}: {
  points: SeriesPoint[]
  unit?: string
  budget?: number
  caption: string
  height?: number
}) {
  if (points.length < 2) return <Empty msg="Not enough points to plot" />

  const w = 600
  const pad = { top: 12, right: 12, bottom: 22, left: 40 }
  const innerW = w - pad.left - pad.right
  const innerH = height - pad.top - pad.bottom

  const values = points.map((p) => p.value)
  const hi = Math.max(...values, budget ?? 0) * 1.1 || 1
  const x = (i: number) => pad.left + (i / (points.length - 1)) * innerW
  const y = (v: number) => pad.top + innerH - (v / hi) * innerH

  const line = points.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join(' ')
  const area = `${line} L${x(points.length - 1).toFixed(1)},${pad.top + innerH} L${pad.left},${pad.top + innerH} Z`

  return (
    <figure style={{ margin: 0 }}>
      <svg
        className="svg-chart"
        viewBox={`0 0 ${w} ${height}`}
        role="img"
        aria-labelledby={`cap-${caption.replace(/\W/g, '')}`}
        preserveAspectRatio="none"
      >
        <title id={`cap-${caption.replace(/\W/g, '')}`}>{caption}</title>
        {[0, 0.5, 1].map((f) => (
          <line key={f} className="grid" x1={pad.left} x2={w - pad.right} y1={y(hi * f)} y2={y(hi * f)} />
        ))}
        {[0, 0.5, 1].map((f) => (
          <text key={f} className="tick" x={4} y={y(hi * f) + 3}>
            {Math.round(hi * f)}
          </text>
        ))}
        <path className="area" d={area} />
        <path className="series series-animate" d={line} />
        {budget !== undefined && <line className="budget" x1={pad.left} x2={w - pad.right} y1={y(budget)} y2={y(budget)} />}
        {points.map((p, i) => (
          <circle key={p.label} className="dot" cx={x(i)} cy={y(p.value)} r={2.5}>
            <title>{`${p.label}: ${p.value}${unit}`}</title>
          </circle>
        ))}
      </svg>
      <figcaption className="visually-hidden">
        <table>
          <caption>{caption}</caption>
          <thead>
            <tr>
              <th>Point</th>
              <th>Value</th>
            </tr>
          </thead>
          <tbody>
            {points.map((p) => (
              <tr key={p.label}>
                <td>{p.label}</td>
                <td>
                  {p.value}
                  {unit}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </figcaption>
      {budget !== undefined && (
        <div className="chart-legend">
          <span>
            <i style={{ background: 'var(--accent)' }} /> observed
          </span>
          <span>
            <i style={{ background: 'var(--error)' }} /> budget {budget}
            {unit}
          </span>
        </div>
      )}
    </figure>
  )
}

/** A tiny trend line for a table cell. Decorative: the number sits beside it. */
export function Sparkline({ values }: { values: number[] }) {
  if (values.length < 2) return null
  const hi = Math.max(...values) || 1
  const lo = Math.min(...values)
  const span = hi - lo || 1
  const d = values
    .map((v, i) => {
      const px = (i / (values.length - 1)) * 100
      const py = 26 - ((v - lo) / span) * 24
      return `${i ? 'L' : 'M'}${px.toFixed(1)},${py.toFixed(1)}`
    })
    .join(' ')
  return (
    <svg className="sparkline" viewBox="0 0 100 28" preserveAspectRatio="none" aria-hidden="true">
      <path d={d} />
    </svg>
  )
}

/** Severity distribution, as a stacked bar with a readable legend. */
export function SeverityBar({ counts }: { counts: Record<string, number> }) {
  const order = ['ERROR', 'WARN', 'INFO'] as const
  const total = order.reduce((n, k) => n + (counts[k] ?? 0), 0)
  if (!total) return null
  return (
    <div>
      <div
        style={{ display: 'flex', height: 10, borderRadius: 'var(--r-full)', overflow: 'hidden' }}
        role="img"
        aria-label={order.map((k) => `${counts[k] ?? 0} ${k}`).join(', ')}
      >
        {order.map((k) =>
          counts[k] ? (
            <div
              key={k}
              className="chart-fill"
              style={{ width: `${((counts[k] ?? 0) / total) * 100}%`, background: `var(--${k.toLowerCase()})` }}
            />
          ) : null,
        )}
      </div>
      <div className="chart-legend">
        {order.map((k) =>
          counts[k] ? (
            <span key={k}>
              <i style={{ background: `var(--${k.toLowerCase()})` }} /> {counts[k]} {k}
            </span>
          ) : null,
        )}
      </div>
    </div>
  )
}

/* ------------------------------------------------------------ big lists */

/** Simple windowed list for large tables (virtualization). */
export function VirtualRows<T>({
  items,
  rowHeight = 36,
  render,
}: {
  items: T[]
  rowHeight?: number
  render: (item: T, index: number) => ReactNode
}) {
  const [scrollTop, setScrollTop] = useState(0)
  const ref = useRef<HTMLDivElement>(null)
  const viewport = 480
  if (items.length <= 40) return <>{items.map((it, i) => render(it, i))}</>
  const start = Math.max(0, Math.floor(scrollTop / rowHeight) - 5)
  const end = Math.min(items.length, start + Math.ceil(viewport / rowHeight) + 10)
  return (
    <div
      ref={ref}
      style={{ maxHeight: viewport, overflowY: 'auto' }}
      onScroll={(e) => setScrollTop((e.target as HTMLDivElement).scrollTop)}
    >
      <div style={{ height: items.length * rowHeight, position: 'relative' }}>
        <div style={{ position: 'absolute', top: start * rowHeight }}>
          {items.slice(start, end).map((it, i) => render(it, start + i))}
        </div>
      </div>
    </div>
  )
}

export function Filters({
  options,
  active,
  onPick,
  label = 'filters',
}: {
  options: string[]
  active: string
  onPick: (v: string) => void
  label?: string
}) {
  return (
    <div className="filters" role="group" aria-label={label}>
      {options.map((o) => (
        <button
          key={o}
          type="button"
          className={active === o ? 'active' : ''}
          aria-pressed={active === o}
          onClick={() => onPick(o)}
        >
          {o}
        </button>
      ))}
    </div>
  )
}

/* --------------------------------------------------------- interactions */

/**
 * Copy a command, and say so.
 *
 * `navigator.clipboard` is undefined on insecure origins and rejects when the
 * document is not focused, and the previous version chained `.then` off it
 * unguarded -- so on plain HTTP the button threw and did nothing visible. It
 * reports failure now, because a copy button that silently does nothing is
 * worse than one that admits it.
 */
export function CopyCmd({ cmd, label }: { cmd: string; label?: string }) {
  const [state, setState] = useState<'idle' | 'copied' | 'failed'>('idle')
  const timer = useRef<number | undefined>(undefined)

  useEffect(() => () => window.clearTimeout(timer.current), [])

  const copy = async () => {
    try {
      if (!navigator.clipboard) throw new Error('clipboard unavailable')
      await navigator.clipboard.writeText(cmd)
      setState('copied')
    } catch {
      setState('failed')
    }
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => setState('idle'), 1800)
  }

  return (
    <button type="button" className="btn" onClick={copy} aria-live="polite">
      <code style={{ border: 0, background: 'none', padding: 0 }}>{label ?? cmd}</code>
      <span className="muted">
        {state === 'copied' ? '✓ copied' : state === 'failed' ? '⚠ press ⌘C' : 'copy'}
      </span>
    </button>
  )
}

/* -------------------------------------------------------------- exports */

/**
 * Take this view out of the dashboard.
 *
 * Three buttons, and the third is honest about what it is. CSV and PNG are
 * produced here; "Print / Save as PDF" hands the page to the browser's own
 * dialog, because a real PDF writer costs more than the entire entry budget
 * and a button labelled "Export PDF" over `window.print()` claims a capability
 * this bundle does not have.
 *
 * Failure is reported, never swallowed -- the same rule `CopyCmd` follows.
 * `canvas.toBlob` signals failure by handing back `null`, so the unguarded
 * version of this is a download button that looks fine and does nothing.
 */
export function Exports({
  view,
  rows,
  columns,
  chartIn,
}: {
  view: string
  rows?: Record<string, unknown>[]
  columns?: string[]
  chartIn?: RefObject<HTMLElement | null>
}) {
  const [error, setError] = useState<string>('')

  const saveCsv = async () => {
    setError('')
    const { csvBlob, download, filename } = await import('../export')
    download(filename(view, 'csv', new Date()), csvBlob(rows ?? [], columns))
  }

  const savePng = async () => {
    setError('')
    const svg = chartIn?.current?.querySelector('svg')
    if (!svg) {
      setError('no chart on screen to save')
      return
    }
    try {
      const { download, filename, svgToPng } = await import('../export')
      download(filename(view, 'png', new Date()), await svgToPng(svg))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'the image could not be produced')
    }
  }

  const empty = !rows || rows.length === 0
  return (
    <div className="exports" role="group" aria-label={`export ${view}`}>
      <button
        type="button"
        onClick={saveCsv}
        disabled={empty}
        // A header-only file looks like a successful export of nothing, and
        // the reader finds out after opening it.
        title={empty ? 'nothing on screen to export' : `download ${view} as CSV`}
      >
        CSV
      </button>
      {chartIn && (
        <button type="button" onClick={savePng} title={`download the ${view} chart as PNG`}>
          PNG
        </button>
      )}
      <button type="button" onClick={() => window.print()} title="opens the browser print dialog">
        Print / Save as PDF
      </button>
      {error && (
        <span className="export-error" role="status">
          {error}
        </span>
      )}
    </div>
  )
}
