/**
 * A four-step walk through the controls somebody cannot guess.
 *
 * Lazily imported, and on most visits never imported at all: it shows once.
 *
 * ## The failure a tour usually has
 *
 * Pointing at something that is not there. A step anchored to a selector that
 * matches nothing leaves a highlight box at (0, 0) and a caption describing a
 * control the reader cannot see — which is worse than not running, because it
 * teaches them the tour is lying.
 *
 * So the steps are filtered against the document **before** anything renders,
 * the counter counts what survived, and a tour with no surviving steps does
 * not run and is not marked as seen. Nothing was shown, so nothing was
 * learned, and marking it seen would spend the one chance this has.
 *
 * ## Dismissal
 *
 * Kept in `localStorage`, which can refuse. If the write fails the tour says
 * so on the last step rather than silently reappearing every visit and leaving
 * the reader to conclude the dashboard is broken.
 */
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { markTourSeen } from '../tour-state'

interface Step {
  /** The control this step is about. */
  selector: string
  title: string
  body: string
}

/** Ordered by how hard the control is to find, not by where it sits. */
const STEPS: Step[] = [
  {
    selector: '.topbar-actions .btn-ghost[aria-label^="Data source"]',
    title: 'Demo data, or yours',
    body:
      'This dashboard is showing artifacts generated from the bundled fixtures. Point it at ' +
      'a self-hosted server, or at an artifact your own run produced, from here.',
  },
  {
    selector: '.saved-views button',
    title: 'Views you come back to',
    body:
      'Every filter writes itself into the URL, so a view is shareable by copying the link. ' +
      'Save one here to name it — saved views live in this browser only.',
  },
  {
    selector: '.topbar-actions .btn-ghost[aria-label^="Search"]',
    title: 'Jump anywhere',
    body: 'Every page is one fuzzy search away. "brk" finds Breaking Changes.',
  },
  {
    selector: '.topbar-actions .btn-ghost[aria-label^="Theme"]',
    title: 'Light, dark, or whatever the system says',
    body: 'Three states, not two: the default follows your operating system.',
  },
]

interface Box {
  top: number
  left: number
  width: number
  height: number
}

export default function Tour({ onClose }: { onClose: () => void }) {
  // Resolved once, before the first paint: a step whose anchor is missing is
  // dropped rather than pointed at.
  const [steps] = useState<Step[]>(() =>
    STEPS.filter((s) => document.querySelector(s.selector) !== null),
  )
  const [index, setIndex] = useState(0)
  const [box, setBox] = useState<Box | null>(null)
  const [stuck, setStuck] = useState(false)
  const panel = useRef<HTMLDivElement>(null)
  const returnFocusTo = useRef<HTMLElement | null>(null)

  const finish = useCallback(() => {
    if (!markTourSeen()) {
      setStuck(true)
      return
    }
    onClose()
  }, [onClose])

  useLayoutEffect(() => {
    const step = steps[index]
    if (!step) return
    const target = document.querySelector(step.selector)
    if (!target) {
      setBox(null)
      return
    }
    const measure = () => {
      const r = target.getBoundingClientRect()
      setBox({ top: r.top, left: r.left, width: r.width, height: r.height })
    }
    measure()
    window.addEventListener('resize', measure)
    window.addEventListener('scroll', measure, true)
    return () => {
      window.removeEventListener('resize', measure)
      window.removeEventListener('scroll', measure, true)
    }
  }, [index, steps])

  useEffect(() => {
    if (!steps.length) {
      // Nothing was shown, so nothing was learned. Deliberately not marked as
      // seen: that would spend the one chance this has.
      onClose()
      return
    }
    returnFocusTo.current = document.activeElement as HTMLElement | null
    panel.current?.focus()
    return () => returnFocusTo.current?.focus?.()
  }, [steps.length, onClose])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') finish()
      else if (e.key === 'ArrowRight') setIndex((i) => Math.min(i + 1, steps.length - 1))
      else if (e.key === 'ArrowLeft') setIndex((i) => Math.max(i - 1, 0))
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [finish, steps.length])

  if (!steps.length) return null
  const step = steps[index]
  const last = index === steps.length - 1

  return (
    <div className="tour-backdrop" role="presentation">
      {box && (
        <div
          className="tour-spot"
          aria-hidden="true"
          style={{ top: box.top - 4, left: box.left - 4, width: box.width + 8, height: box.height + 8 }}
        />
      )}
      <div
        ref={panel}
        className="tour-panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby="tour-title"
        tabIndex={-1}
        style={box ? { top: box.top + box.height + 14, right: 16 } : undefined}
      >
        <p className="tour-count">
          {index + 1} of {steps.length}
        </p>
        <h3 id="tour-title">{step.title}</h3>
        <p>{step.body}</p>
        {stuck && (
          <p className="tour-problem" role="status">
            This browser is not storing site data, so this will show again next visit.
          </p>
        )}
        <div className="tour-actions">
          <button type="button" className="linklike" onClick={finish}>
            Skip
          </button>
          {index > 0 && (
            <button type="button" className="btn btn-ghost" onClick={() => setIndex(index - 1)}>
              Back
            </button>
          )}
          <button
            type="button"
            className="btn"
            onClick={() => (last ? finish() : setIndex(index + 1))}
          >
            {last ? 'Done' : 'Next'}
          </button>
        </div>
      </div>
    </div>
  )
}
