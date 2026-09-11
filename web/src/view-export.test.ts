/**
 * Taking a view out of the dashboard, and the two ways that goes wrong.
 *
 * A CSV of findings is a file of strings that came out of somebody else's spec
 * document, opened in a program that executes strings beginning with `=`. A
 * PNG of a chart styled entirely by an external stylesheet is, serialized
 * naively, a black line on a transparent background.
 *
 * One constraint on this file: the spreadsheet-injection cases below use
 * deliberately inert formulas. A realistic payload is in every antivirus
 * signature set, and a test fixture that gets a contributor's checkout
 * quarantined is a worse outcome than a less dramatic example. The code path
 * is the first character, and `=1+1` exercises it exactly as well.
 */
import { describe, expect, it } from 'vitest'
import { ExportError, filename, standalone, toCsv } from './export'

describe('toCsv', () => {
  it('writes the columns in the order it was given', () => {
    expect(toCsv([{ b: 2, a: 1 }], ['a', 'b'])).toBe('a,b\r\n1,2\r\n')
  })

  it('takes the union of keys when no columns are named', () => {
    expect(toCsv([{ a: 1 }, { b: 2 }]).split('\r\n')[0]).toBe('a,b')
  })

  it('leaves an empty cell for a key a row does not have', () => {
    // Not a row that redefines the table: a row missing a key is a row with a
    // gap, and dropping the column would lose the other row's value.
    expect(toCsv([{ a: 1 }, { b: 2 }])).toBe('a,b\r\n1,\r\n,2\r\n')
  })

  it('quotes a value carrying a comma, a quote or a newline', () => {
    const body = toCsv([{ m: 'a,b' }, { m: 'say "hi"' }, { m: 'one\ntwo' }], ['m'])
    expect(body).toContain('"a,b"')
    expect(body).toContain('"say ""hi"""')
    expect(body).toContain('"one\ntwo"')
  })

  it('renders null and undefined as empty rather than as their names', () => {
    expect(toCsv([{ a: null, b: undefined }], ['a', 'b'])).toBe('a,b\r\n,\r\n')
  })

  it('uses CRLF, which is what RFC 4180 says and what Excel reads', () => {
    expect(toCsv([{ a: 1 }], ['a'])).toBe('a\r\n1\r\n')
  })

  describe('a spreadsheet will not execute what comes out of it', () => {
    // Every string worth exporting here came from somewhere else -- a finding
    // message quotes a spec file, an operation key quotes a path -- so "the
    // export contains what the document said" is exactly the property that
    // makes this dangerous.
    it.each(['=1+1', '+1', '-1', '@SUM(A1)', '\tx', '\rx'])('neutralizes %j', (value) => {
      expect(toCsv([{ m: value }], ['m']).slice('m\r\n'.length)).toMatch(/^["']/)
    })

    it('leaves an ordinary value alone', () => {
      expect(toCsv([{ m: 'GET /users' }], ['m'])).toBe('m\r\nGET /users\r\n')
    })

    it('neutralizes before quoting, so the quoted form is safe too', () => {
      // A formula that also needs RFC 4180 quoting. Both have to happen, in
      // that order: quote first and the apostrophe lands inside the quotes,
      // where the spreadsheet has already decided the cell is a formula.
      expect(toCsv([{ m: '=A1&",x"' }], ['m'])).toBe('m\r\n"\'=A1&"",x"""\r\n')
    })
  })
})

describe('filename', () => {
  const when = new Date('2026-09-11T14:03:22.500Z')

  it('carries a sortable stamp', () => {
    expect(filename('drift findings', 'csv', when)).toBe(
      'apiverity-drift-findings-2026-09-11-14-03-22.csv',
    )
  })

  it('has no colon in it', () => {
    // `perf-2026-09-11T14:03:22.csv` is unwritable on Windows, and a download
    // that fails silently is worse than one that is ugly.
    expect(filename('perf', 'png', when)).not.toContain(':')
  })

  it('survives a view name that is entirely punctuation', () => {
    expect(filename('///', 'csv', when)).toContain('apiverity-view-')
  })
})

describe('standalone', () => {
  function chart(inner: string): SVGSVGElement {
    const host = document.createElement('div')
    host.innerHTML = `<svg viewBox="0 0 100 40">${inner}</svg>`
    document.body.appendChild(host)
    return host.querySelector('svg') as SVGSVGElement
  }

  it('copies the computed appearance onto the clone', () => {
    // The whole reason this function exists. The charts are styled by the
    // external stylesheet, and a serialized SVG carries none of it: without
    // this the PNG is a black line on a transparent background.
    const path = withStyle('.series { stroke: rgb(1, 2, 3); stroke-width: 4px; }', () => {
      const svg = chart('<path class="series" d="M0,0 L10,10" />')
      return standalone(svg).querySelector('path') as SVGPathElement
    })
    expect(path.getAttribute('stroke')).toBe('rgb(1, 2, 3)')
    expect(path.getAttribute('stroke-width')).toBe('4px')
  })

  it('paints an OPAQUE background, so the image is not invisible', () => {
    // "Truthy" was the original assertion and it passed while the exported PNG
    // was fully transparent: this app paints its ground on `:root`, `body`
    // computes to `rgba(0, 0, 0, 0)`, and that string is truthy. The bug was
    // found by exporting one in a browser and reading the corner pixel; this
    // is the assertion that would have found it first.
    const first = standalone(chart('<path d="M0,0" />')).firstElementChild as SVGRectElement
    expect(first.tagName).toBe('rect')
    expect(first.getAttribute('fill')).not.toMatch(/^transparent$|,\s*0\s*\)$/)
  })

  /** Apply a stylesheet for one measurement and take it away again.
   *
   * In a `finally`, because a failing assertion inside the block would
   * otherwise leave the rule in the document and fail the next two tests for a
   * reason that has nothing to do with them.
   */
  function withStyle<T>(css: string, measure: () => T): T {
    const style = document.createElement('style')
    style.textContent = css
    document.head.appendChild(style)
    try {
      return measure()
    } finally {
      style.remove()
    }
  }

  it('prefers the ground the stylesheet declares', () => {
    // Measured before the walk, because `body` both disappears into the canvas
    // and interpolates mid-theme-switch. The token does neither.
    const fill = withStyle(':root { --bg: rgb(7, 7, 7); }', () => {
      const rect = standalone(chart('<path d="M0,0" />')).firstElementChild as SVGRectElement
      return rect.getAttribute('fill')
    })
    expect(fill?.replace(/\s+/g, '')).toBe('rgb(7,7,7)')
  })

  it('falls back to an ancestor for a page with no such token', () => {
    const fill = withStyle('.ground { background-color: rgb(9, 9, 9); }', () => {
      const host = document.createElement('div')
      host.className = 'ground'
      host.innerHTML = '<div><svg viewBox="0 0 10 10"><path d="M0,0" /></svg></div>'
      document.body.appendChild(host)
      const svg = host.querySelector('svg') as SVGSVGElement
      const rect = standalone(svg).firstElementChild as SVGRectElement
      const value = rect.getAttribute('fill')
      host.remove()
      return value
    })
    expect(fill).toBe('rgb(9, 9, 9)')
  })

  it('falls back to white when nothing on the page declares a ground', () => {
    const rect = standalone(chart('<path d="M0,0" />')).firstElementChild as SVGRectElement
    expect(rect.getAttribute('fill')).toBe('#ffffff')
  })

  it('carries explicit dimensions and a namespace', () => {
    const clone = standalone(chart('<path d="M0,0" />'))
    expect(clone.getAttribute('xmlns')).toBe('http://www.w3.org/2000/svg')
    expect(Number(clone.getAttribute('width'))).toBeGreaterThan(0)
    expect(Number(clone.getAttribute('height'))).toBeGreaterThan(0)
  })

  it('refuses a chart whose content it cannot inline', () => {
    // Exporting it anyway would produce an image that differs from the chart,
    // which is worse than not producing one.
    expect(() => standalone(chart('<image href="x.png" />'))).toThrow(ExportError)
    expect(() => standalone(chart('<foreignObject><div /></foreignObject>'))).toThrow(/inlined/)
  })

  it('does not touch the element on screen', () => {
    const svg = chart('<path class="series" d="M0,0" />')
    standalone(svg)
    expect(svg.querySelectorAll('rect')).toHaveLength(0)
    expect(svg.getAttribute('width')).toBeNull()
  })
})
