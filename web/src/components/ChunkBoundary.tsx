/* An error boundary for lazily-loaded route and widget chunks.
 *
 * Without one, a dynamic import that fails unmounts the whole React tree and
 * the reader gets a blank page. That is not a hypothetical: this app splits
 * every page group into its own chunk, and a chunk 404s routinely in one very
 * ordinary situation -- the site is redeployed while someone has it open, so
 * their loaded HTML asks for `CommandPalette-Bod-eZ1M.js` and the server now
 * only has `CommandPalette-CdygCUKU.js`. Pressing ⌘K blanked the dashboard.
 *
 * A stale chunk is recoverable and the recovery is a reload, so that is what
 * this offers. Errors that are not import failures are shown rather than
 * swallowed, because a silent catch-all boundary hides real bugs.
 */
import { Component, type ErrorInfo, type ReactNode } from 'react'

interface Props {
  children: ReactNode
  /** What failed, named for the reader: "the command palette", "this page". */
  what: string
}

interface State {
  error: Error | null
}

/** Vite and Rollup phrase this differently across versions; match loosely. */
function isStaleChunk(error: Error): boolean {
  const text = `${error.name} ${error.message}`.toLowerCase()
  return (
    text.includes('dynamically imported module') ||
    text.includes('failed to fetch dynamically') ||
    text.includes('importing a module script failed') ||
    text.includes('chunkloaderror')
  )
}

export default class ChunkBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Kept: a blank region with no trace is the hardest kind of bug to report.
    // eslint-disable-next-line no-console
    console.error(`ChunkBoundary caught an error in ${this.props.what}`, error, info)
  }

  render(): ReactNode {
    const { error } = this.state
    if (!error) return this.props.children

    if (isStaleChunk(error)) {
      return (
        <div className="banner warn" role="alert">
          <strong>A newer version is available.</strong> Part of the app could not be loaded
          because it changed since this page opened.{' '}
          <button type="button" className="btn" onClick={() => window.location.reload()}>
            Reload
          </button>
        </div>
      )
    }

    return (
      <div className="banner error" role="alert">
        <strong>{this.props.what} failed to render.</strong> {error.message}{' '}
        <button type="button" className="btn" onClick={() => this.setState({ error: null })}>
          Try again
        </button>
      </div>
    )
  }
}
