/* The performance page, and the two numbers that must not be confused.
 *
 * A handshake shown beside a p95 gets added to it unless the page says not to,
 * and the run pools connections so the handshake is paid once and is in none of
 * the percentiles. That sentence is the test that matters here.
 *
 * The other one is an em dash: a report generated before response size was
 * measured carries no byte counts at all, and printing `0 B` for a missing
 * measurement would say the response was empty. */
import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { PerfPage } from './runtime'
import type { ConnectionProbe, DemoData, PerfOp } from '../data'

const OP: PerfOp = {
  operation_key: 'GET /users',
  p50_ms: 3.1,
  p95_ms: 8.4,
  p99_ms: 12.2,
  errors: 0,
  throughput_rps: 240.5,
  bytes_p50: 840,
  bytes_p95: 4200,
  bytes_max: 1_500_000,
  bytes_total: 42_000,
  bytes_per_second: 90_000,
}

const PROBE: ConnectionProbe = {
  host: 'orders.example.com',
  port: 443,
  scheme: 'https',
  dns_ms: 12.5,
  tcp_ms: 21.0,
  tls_ms: 43.75,
  total_ms: 77.25,
  tls_version: 'TLSv1.3',
  cipher: 'TLS_AES_256_GCM_SHA384',
  alpn: 'h2',
  addresses: 2,
  error: null,
  note: 'a single cold connection, measured before the load run. Requests during the run reuse a pooled connection and do not pay this again, so it is reported beside the percentiles rather than inside them.',
}

const data = (
  operations: PerfOp[] = [OP],
  connection: ConnectionProbe | null = PROBE,
): DemoData =>
  ({
    meta: { tool: 'apiverity', generated_from: 'fixtures', label: 'demo' },
    performance: { operations, connection },
  }) as DemoData

describe('PerfPage', () => {
  it('reports payload size beside latency', () => {
    render(<PerfPage data={data()} />)
    const row = screen.getByText('GET /users').closest('tr') as HTMLElement
    expect(within(row).getByText('4.2 kB')).toBeTruthy()
    expect(within(row).getByText('1.50 MB')).toBeTruthy()
  })

  it('shows an em dash rather than 0 B when size was never measured', () => {
    const older: PerfOp = { ...OP }
    delete older.bytes_p95
    delete older.bytes_max
    render(<PerfPage data={data([older])} />)
    const row = screen.getByText('GET /users').closest('tr') as HTMLElement
    expect(within(row).getAllByText('—').length).toBe(2)
  })

  it('says the connection cost is not inside the percentiles', () => {
    render(<PerfPage data={data()} />)
    expect(screen.getByText(/reuse a pooled connection/)).toBeTruthy()
  })

  it('names the TLS version beside the handshake time', () => {
    /* Two round trips or one, which is the actionable half of the number. */
    render(<PerfPage data={data()} />)
    expect(screen.getByText('43.8 ms')).toBeTruthy()
    expect(screen.getByText('TLS (TLSv1.3)')).toBeTruthy()
  })

  it('says a plain-HTTP target has no handshake rather than an instant one', () => {
    render(
      <PerfPage
        data={data([OP], {
          ...PROBE,
          scheme: 'http',
          port: 80,
          tls_ms: null,
          tls_version: null,
          cipher: null,
          alpn: null,
        })}
      />,
    )
    expect(screen.getByText('TLS (none — plain HTTP)')).toBeTruthy()
  })

  it('reports a failed probe rather than blank cards', () => {
    render(
      <PerfPage
        data={data([OP], { ...PROBE, error: 'ConnectionRefusedError: [Errno 111]' })}
      />,
    )
    expect(screen.getByText(/The probe did not complete/)).toBeTruthy()
  })

  it('renders without a probe at all, for reports generated before it existed', () => {
    render(<PerfPage data={data([OP], null)} />)
    expect(screen.queryByText('Connection')).toBeNull()
    expect(screen.getByText('GET /users')).toBeTruthy()
  })
})
