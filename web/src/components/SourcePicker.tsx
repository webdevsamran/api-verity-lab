/* Point the dashboard at a self-hosted server, or back at the demo artifact.
 *
 * Lazily loaded, like the command palette: it is a form most sessions never
 * open, and putting it in the shell would charge every visitor to the public
 * demo for a feature only self-hosted users need.
 *
 * The token field is a password input backed by `localStorage`, and there is
 * deliberately no way to put it in the URL. A shareable live-dashboard link
 * would be the convenient design, and it would write a bearer token into
 * browser history, the server's access log, and the `Referer` header of every
 * outbound link on the page -- which is exactly what `SEC-APIKEY-IN-QUERY`
 * reports about other people's contracts.
 */
import { useEffect, useRef, useState } from 'react'
import type { LiveConfig } from '../live'

export interface SourcePickerProps {
  live: LiveConfig | null
  onChange: (config: LiveConfig | null) => void
  onClose: () => void
}

export default function SourcePicker({ live, onChange, onClose }: SourcePickerProps) {
  const [baseUrl, setBaseUrl] = useState(live?.baseUrl ?? '')
  const [token, setToken] = useState(live?.token ?? '')
  const [orgId, setOrgId] = useState(String(live?.orgId ?? 1))
  const firstField = useRef<HTMLInputElement>(null)

  useEffect(() => {
    firstField.current?.focus()
  }, [])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    const trimmed = baseUrl.trim().replace(/\/+$/, '')
    if (!trimmed) {
      onChange(null)
    } else {
      onChange({ baseUrl: trimmed, token: token.trim(), orgId: Number(orgId) || 1 })
    }
    onClose()
  }

  return (
    <div className="palette-backdrop" onClick={onClose} role="presentation">
      <div
        className="palette"
        role="dialog"
        aria-modal="true"
        aria-labelledby="source-title"
        onClick={(e) => e.stopPropagation()}
      >
        <form onSubmit={submit} className="source-form">
          <h3 id="source-title">Data source</h3>
          <p className="muted">
            Leave the server blank to read the bundled <code>demo-data.json</code>. A live
            server fills the org, contract, environment, approval, run, audit and webhook
            views; the run-derived sections stay empty, because a server holds state rather
            than the output of a run.
          </p>

          <label htmlFor="source-url">Server base URL</label>
          <input
            id="source-url"
            ref={firstField}
            type="url"
            inputMode="url"
            placeholder="https://verity.internal"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
          />

          <label htmlFor="source-token">API token</label>
          <input
            id="source-token"
            type="password"
            autoComplete="off"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            aria-describedby="source-token-note"
          />
          <p id="source-token-note" className="muted">
            Stored in this browser only, and never placed in the URL.
          </p>

          <label htmlFor="source-org">Organisation id</label>
          <input
            id="source-org"
            type="number"
            min="1"
            value={orgId}
            onChange={(e) => setOrgId(e.target.value)}
          />

          <div className="source-actions">
            <button type="submit" className="btn">
              Use this source
            </button>
            <button type="button" className="btn btn-ghost" onClick={onClose}>
              Cancel
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
