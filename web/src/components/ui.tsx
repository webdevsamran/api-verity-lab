/* Shared presentational building blocks used by every page. */
import { useRef, useState, type ReactNode } from 'react'

export const SEV_COLORS: Record<string, string> = { ERROR: '#e5484d', WARN: '#f5a623', INFO: '#3b82f6' }
export const METHOD_COLORS: Record<string, string> = {
  GET: '#3b82f6', POST: '#2ea043', PUT: '#f5a623', PATCH: '#a855f7', DELETE: '#e5484d',
}

export function Badge({ children, color }: { children: ReactNode; color?: string }) {
  return <span className="badge" style={color ? { background: color } : undefined}>{children}</span>
}
export function SevBadge({ sev }: { sev: string }) {
  return <Badge color={SEV_COLORS[sev]}>{sev}</Badge>
}
export function StatusBadge({ ok }: { ok: boolean }) {
  return <Badge color={ok ? '#2ea043' : '#e5484d'}>{ok ? 'pass' : 'fail'}</Badge>
}
export function Empty({ msg }: { msg: string }) {
  return <div className="empty">{msg}</div>
}
export function DemoTag() {
  return <Badge color="#6b7280">DEMO DATA</Badge>
}
export function PageHead({ title, sub }: { title: string; sub?: string }) {
  return (
    <>
      <h2>{title} {sub && <span className="muted">{sub}</span>}</h2>
      <p className="muted"><DemoTag /> static demo artifacts generated from bundled fixtures — run the CLI for your own APIs.</p>
    </>
  )
}
export function BarChart({ rows }: { rows: { label: string; value: number; max: number }[] }) {
  return (
    <div className="chart" role="img" aria-label="bar chart">
      {rows.map((r) => (
        <div key={r.label} className="chart-row">
          <span className="chart-label">{r.label}</span>
          <div className="chart-track">
            <div className="chart-fill" style={{ width: `${Math.min(100, (r.value / Math.max(r.max, 1)) * 100)}%` }} />
          </div>
          <span className="chart-value">{r.value}</span>
        </div>
      ))}
    </div>
  )
}
/** Simple windowed list for large tables (virtualization). */
export function VirtualRows<T>({ items, rowHeight = 36, render }: {
  items: T[]; rowHeight?: number; render: (item: T, index: number) => ReactNode
}) {
  const [scrollTop, setScrollTop] = useState(0)
  const ref = useRef<HTMLDivElement>(null)
  const viewport = 480
  if (items.length <= 40) return <>{items.map((it, i) => render(it, i))}</>
  const start = Math.max(0, Math.floor(scrollTop / rowHeight) - 5)
  const end = Math.min(items.length, start + Math.ceil(viewport / rowHeight) + 10)
  return (
    <div ref={ref} style={{ maxHeight: viewport, overflowY: 'auto' }}
      onScroll={(e) => setScrollTop((e.target as HTMLDivElement).scrollTop)}>
      <div style={{ height: items.length * rowHeight, position: 'relative' }}>
        <div style={{ position: 'absolute', top: start * rowHeight }}>
          {items.slice(start, end).map((it, i) => render(it, start + i))}
        </div>
      </div>
    </div>
  )
}
export function Filters({ options, active, onPick }: { options: string[]; active: string; onPick: (v: string) => void }) {
  return (
    <div className="filters" role="group" aria-label="filters">
      {options.map((o) => (
        <button key={o} className={active === o ? 'active' : ''} onClick={() => onPick(o)}>{o}</button>
      ))}
    </div>
  )
}
export function CopyCmd({ cmd }: { cmd: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <button onClick={() => {
      navigator.clipboard?.writeText(cmd).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500) })
    }}>{copied ? 'copied!' : `copy: ${cmd}`}</button>
  )
}
