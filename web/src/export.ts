/**
 * Taking a view out of the dashboard: CSV, PNG, and the browser's own PDF.
 *
 * Three formats, and only two of them are produced here. `window.print()` is
 * what "Save as PDF" is — the browser renders it, this file does not — and the
 * button says so. A menu item labelled "Export PDF" over a call to `print()`
 * claims a capability this bundle does not have, in a project whose stated
 * rule is that the tool never asserts what it did not establish.
 *
 * There are no runtime dependencies here, which is also why: a real PDF writer
 * is 300 kB and the entry budget has ten to spare.
 */

/* ------------------------------------------------------------------- CSV */

/**
 * A value that a spreadsheet will not execute.
 *
 * A CSV cell beginning with `=`, `+`, `-`, `@`, a tab or a carriage return is
 * a formula to Excel, Sheets and LibreOffice. Every string in this dashboard
 * that is worth exporting came from somewhere else — a finding message quotes
 * a spec file, an operation key quotes a path — so "the export contains what
 * the document said" is exactly the property that makes this dangerous.
 *
 * Prefixed with an apostrophe, which every spreadsheet reads as "this is
 * text" and strips on display. It is visible in a plain-text read of the file,
 * which is the honest trade: the alternative is a file that runs.
 */
function neutralize(value: string): string {
  return /^[=+\-@\t\r]/.test(value) ? `'${value}` : value
}

function cell(value: unknown): string {
  if (value === null || value === undefined) return ''
  const text = neutralize(typeof value === 'string' ? value : String(value))
  // RFC 4180: quote when the value carries a delimiter, a quote or a newline,
  // and double any quote inside.
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
}

/**
 * Rows as RFC 4180 CSV.
 *
 * `columns` fixes the order and the header. Without it the columns are the
 * union of every row's keys in first-seen order, because a row missing a key
 * is a row with an empty cell, not a row that redefines the table.
 */
export function toCsv(rows: Record<string, unknown>[], columns?: string[]): string {
  const cols = columns ?? [...new Set(rows.flatMap((r) => Object.keys(r)))]
  const head = cols.map(cell).join(',')
  const body = rows.map((row) => cols.map((c) => cell(row[c])).join(','))
  // CRLF, which is what RFC 4180 says and what keeps Excel from treating the
  // whole file as one line on Windows.
  return [head, ...body].join('\r\n') + '\r\n'
}

export function csvBlob(rows: Record<string, unknown>[], columns?: string[]): Blob {
  // A BOM, so Excel reads it as UTF-8 rather than the local code page. Without
  // it an operation key with a non-ASCII character opens as mojibake.
  return new Blob(['﻿', toCsv(rows, columns)], { type: 'text/csv;charset=utf-8' })
}

/* ------------------------------------------------------------------- PNG */

/** Presentational properties a stylesheet sets and a serialized SVG loses. */
const INLINE = [
  'fill',
  'fill-opacity',
  'stroke',
  'stroke-width',
  'stroke-dasharray',
  'stroke-linecap',
  'opacity',
  'font-family',
  'font-size',
  'font-weight',
] as const

export class ExportError extends Error {}

/**
 * A chart that carries its own appearance.
 *
 * The charts here are styled entirely by the external stylesheet — `.series`,
 * `.grid`, `.tick`, each resolving a CSS variable. Serialize the element as it
 * stands and none of that comes with it: the PNG is a black line on a
 * transparent background, which on a dark theme is an empty file and on a
 * light one is a chart with no axes. So every computed presentational property
 * is copied onto the clone before serializing.
 *
 * The background is painted explicitly for the same reason. A transparent PNG
 * of a light-on-dark chart is invisible in every viewer that assumes white --
 * and it has to come from an ancestor that actually declares one, not from
 * `body`, which in this app is transparent.
 *
 * Split out of `svgToPng` so it is testable: jsdom has no canvas, and the part
 * that goes wrong is this one.
 */
export function standalone(svg: SVGSVGElement): SVGSVGElement {
  if (svg.querySelector('image, foreignObject')) {
    // Both pull content this cannot inline, so the PNG would differ from the
    // chart on screen. Refused rather than exported wrong.
    throw new ExportError(
      'this chart embeds an image or foreign content, which cannot be inlined; ' +
        'use the browser print dialog instead',
    )
  }

  const rect = svg.getBoundingClientRect()
  const width = Math.max(1, Math.round(rect.width || svg.clientWidth || 600))
  const height = Math.max(1, Math.round(rect.height || svg.clientHeight || 200))

  const clone = svg.cloneNode(true) as SVGSVGElement
  const live = [svg, ...svg.querySelectorAll('*')]
  const copies = [clone, ...clone.querySelectorAll('*')]
  live.forEach((node, i) => {
    const target = copies[i]
    if (!target) return
    const computed = window.getComputedStyle(node)
    for (const property of INLINE) {
      const value = computed.getPropertyValue(property)
      if (value) target.setAttribute(property, value)
    }
  })
  clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg')
  clone.setAttribute('width', String(width))
  clone.setAttribute('height', String(height))

  const background = document.createElementNS('http://www.w3.org/2000/svg', 'rect')
  background.setAttribute('width', '100%')
  background.setAttribute('height', '100%')
  background.setAttribute('fill', groundUnder(svg))
  clone.insertBefore(background, clone.firstChild)
  return clone
}

/** The custom property this app names its page ground with. */
const GROUND_TOKEN = '--bg'

/**
 * The first opaque background behind an element.
 *
 * The obvious implementation — read `background-color` off `document.body` —
 * returns `rgba(0, 0, 0, 0)` on every page in this app, in both themes. That
 * is not a bug in the stylesheet: CSS propagates the body's background to the
 * canvas when `html` declares none, and the body's own used background then
 * *is* transparent. `body { background: var(--bg) }` paints the window and
 * computes to nothing.
 *
 * That is not the only reason the walk is unreliable. `body` carries a
 * `transition` on `background`, so mid-switch it computes to the colour it is
 * leaving; measured in a browser, the same element answered
 * `rgba(0, 0, 0, 0)` on one call and `rgb(255, 255, 255)` on the next while
 * the dark theme was active and `--bg` was `#0d1117`.
 *
 * So the declared token is consulted first. It is what the stylesheet
 * resolved, it does not interpolate, and it does not disappear into the
 * canvas. The ancestor walk stays as the fallback for a page that does not use
 * this app's tokens at all.
 *
 * The original version read `body` and fell back with `|| '#ffffff'`, which
 * never fired: `rgba(0, 0, 0, 0)` is a non-empty string. Every exported PNG
 * was fully transparent — the exact failure this rect exists to prevent — and
 * the unit test missed it because that string is also truthy. Found by
 * exporting one in a browser and reading the corner pixel.
 */
function groundUnder(element: Element): string {
  const declared = window
    .getComputedStyle(document.documentElement)
    .getPropertyValue(GROUND_TOKEN)
    .trim()
  if (declared && !TRANSPARENT.test(declared)) return declared
  for (let node: Element | null = element; node; node = node.parentElement) {
    const colour = window.getComputedStyle(node).backgroundColor
    if (colour && !TRANSPARENT.test(colour)) return colour
  }
  // Nothing declares one. White, because that is what a browser paints when
  // nothing else does.
  return '#ffffff'
}

/** `transparent`, and any colour whose alpha is zero. */
const TRANSPARENT = /^transparent$|^rgba?\([^)]*,\s*0(\.0+)?\s*\)$/i

export async function svgToPng(svg: SVGSVGElement, scale = 2): Promise<Blob> {
  const clone = standalone(svg)
  const width = Number(clone.getAttribute('width'))
  const height = Number(clone.getAttribute('height'))
  const markup = new XMLSerializer().serializeToString(clone)
  const source = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(markup)}`

  const image = await new Promise<HTMLImageElement>((resolve, reject) => {
    const element = new Image()
    element.onload = () => resolve(element)
    element.onerror = () => reject(new ExportError('the chart could not be rendered to an image'))
    element.src = source
  })

  const canvas = document.createElement('canvas')
  canvas.width = width * scale
  canvas.height = height * scale
  const context = canvas.getContext('2d')
  if (!context) throw new ExportError('this browser did not provide a 2D canvas')
  context.drawImage(image, 0, 0, canvas.width, canvas.height)

  return new Promise<Blob>((resolve, reject) => {
    canvas.toBlob((blob) => {
      // Null rather than an exception is how `toBlob` reports failure, and an
      // unchecked one here is a download button that does nothing.
      if (blob) resolve(blob)
      else reject(new ExportError('the browser produced no image data'))
    }, 'image/png')
  })
}

/* -------------------------------------------------------------- delivery */

/** Hand a blob to the browser under `name`. */
export function download(name: string, blob: Blob): void {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = name
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  // Deferred, because revoking synchronously cancels the download in Safari.
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/**
 * A filename that is stable, sortable, and legal on every filesystem.
 *
 * No colons — `perf-2026-09-11T14:03:22.csv` is unwritable on Windows, and a
 * download that fails silently is worse than one that is ugly.
 */
export function filename(view: string, extension: string, now: Date): string {
  const stamp = now.toISOString().slice(0, 19).replace(/[:T]/g, '-')
  const slug = view.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'view'
  return `apiverity-${slug}-${stamp}.${extension}`
}
