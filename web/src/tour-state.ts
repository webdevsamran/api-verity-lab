/**
 * Whether the tour has run, kept out of `Tour.tsx` so the shell can ask
 * without pulling the tour in.
 *
 * `Tour.tsx` is lazy and, on every visit after the first, never fetched. That
 * only holds if the question "has this run?" can be answered without importing
 * it — which is this file, and why it is four lines rather than a method on
 * the component.
 */

export const TOUR_KEY = 'apiverity.tour.v1'

export function tourSeen(): boolean {
  try {
    return window.localStorage.getItem(TOUR_KEY) === '1'
  } catch {
    // Storage refused. Treated as seen rather than offering a tour that can
    // never be dismissed and therefore returns on every visit.
    return true
  }
}

export function markTourSeen(): boolean {
  try {
    window.localStorage.setItem(TOUR_KEY, '1')
    return true
  } catch {
    return false
  }
}
