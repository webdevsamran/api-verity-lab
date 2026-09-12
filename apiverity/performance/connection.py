"""What it costs to open the connection, measured apart from what runs over it.

`docs/capability-status.md` carried "TLS timing breakdown -- PARTIAL" for a
long time, and the honest reason is that a per-request breakdown of DNS, TCP
and TLS is not a thing this tool can produce. `httpx` exposes no hook between
"resolve" and "handshake", and the load run pools connections on purpose -- so
for all but the first request of a run, the DNS lookup and the handshake cost
exactly nothing. Amortising a handshake into a p95 would describe a service
nobody is running.

So it is measured as what it is: **a one-off probe of connection
establishment**, taken before the load run, with a plain statement that the
requests in that run reuse a pooled connection and do not pay it again. Four
numbers a reader can act on --

    dns_ms   how long the name took to resolve
    tcp_ms   how long the socket took to connect
    tls_ms   how long the handshake took
    total_ms the three of them

-- plus what the handshake actually negotiated, which is the part that turns a
number into a decision: a TLS 1.2 handshake is roughly two round trips and a
1.3 one is roughly one, and knowing which you got is more useful than knowing
it took 84 ms.

## What this does not measure

- **Per-request TLS.** There is none, in a pooled client. If you want the cold
  cost, this probe is it.
- **Session resumption.** The probe opens a fresh connection with no session
  ticket, so it reports the *cold* handshake. A real client with a warm ticket
  pays less, sometimes much less.
- **HTTP/2 or HTTP/3 setup.** ALPN is reported, so you can see what was
  negotiated; the protocol's own connection preface is not timed separately.
- **Anything about the network on the day.** One sample, from here to there,
  now. It is a probe, not a monitor, and the report says how many samples it
  took.
"""

from __future__ import annotations

import contextlib
import socket
import ssl
import time
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel

#: Long enough that a slow but working target is measured rather than reported
#: as broken; short enough that an unreachable one does not stall a run.
DEFAULT_TIMEOUT = 5.0


class ConnectionProbe(BaseModel):
    """One cold connection to the target, broken into its phases.

    Every duration is milliseconds. `None` means *not measured*, never zero:
    a plain-HTTP target has no handshake to time, and reporting `0.0` for it
    would read as an instantaneous one.
    """

    host: str = ""
    port: int = 0
    scheme: str = ""
    dns_ms: float | None = None
    tcp_ms: float | None = None
    tls_ms: float | None = None
    total_ms: float | None = None
    #: What the handshake negotiated. A TLS 1.2 handshake is about two round
    #: trips and a 1.3 one about one, which is usually the actionable half of
    #: the measurement.
    tls_version: str | None = None
    cipher: str | None = None
    alpn: str | None = None
    #: How many addresses the name resolved to. A name with one A record and a
    #: name with eight behave differently under failure, and neither shows up
    #: in a latency percentile.
    addresses: int = 0
    #: Set when the probe could not complete. The other fields are then
    #: whatever was measured before it failed.
    error: str | None = None
    #: Said in the artifact, not only in this docstring: the load run reuses a
    #: pooled connection, so this cost is paid once and is not in the
    #: percentiles.
    note: str = (
        "a single cold connection, measured before the load run. Requests during the run "
        "reuse a pooled connection and do not pay this again, so it is reported beside the "
        "percentiles rather than inside them."
    )

    def as_dict(self) -> dict[str, Any]:
        return self.model_dump()


def _default_port(scheme: str) -> int:
    return 443 if scheme == "https" else 80


def probe(base_url: str, *, timeout: float = DEFAULT_TIMEOUT) -> ConnectionProbe:
    """Open one connection to `base_url` and time each phase of it."""
    parts = urlsplit(base_url)
    scheme = (parts.scheme or "http").lower()
    host = parts.hostname or ""
    port = parts.port or _default_port(scheme)
    result = ConnectionProbe(host=host, port=port, scheme=scheme)
    if not host:
        result.error = f"no host in {base_url!r}"
        return result

    started = time.perf_counter()
    try:
        t0 = time.perf_counter()
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
        result.dns_ms = round((time.perf_counter() - t0) * 1000.0, 3)
        result.addresses = len(infos)
    except OSError as exc:
        result.error = f"could not resolve {host}: {exc}"
        return result

    family, socktype, proto, _canon, address = infos[0]
    sock: socket.socket | None = None
    try:
        sock = socket.socket(family, socktype, proto)
        sock.settimeout(timeout)
        t0 = time.perf_counter()
        sock.connect(address)
        result.tcp_ms = round((time.perf_counter() - t0) * 1000.0, 3)

        if scheme == "https":
            # The default context: verification on, hostname checked. A probe
            # that disabled either would report a handshake nobody's client
            # performs, and would quietly turn this tool into one that talks to
            # servers it cannot authenticate.
            context = ssl.create_default_context()
            # And TLS 1.2 at the floor, for the same reason rather than a
            # different one. `create_default_context` still permits 1.0 and
            # 1.1 on many builds; browsers and every Python HTTP client in
            # this project's dependency list have refused both since 2020. A
            # probe that negotiated 1.0 would report a comfortable handshake
            # time for an endpoint no real client can reach, which is the one
            # answer a performance measurement must not give.
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.set_alpn_protocols(["h2", "http/1.1"])
            t0 = time.perf_counter()
            wrapped = context.wrap_socket(sock, server_hostname=host)
            result.tls_ms = round((time.perf_counter() - t0) * 1000.0, 3)
            result.tls_version = wrapped.version()
            cipher = wrapped.cipher()
            result.cipher = cipher[0] if cipher else None
            result.alpn = wrapped.selected_alpn_protocol()
            sock = wrapped
    except ssl.SSLError as exc:
        # Said plainly, because "handshake failure" against a server that is
        # up and answering reads as a bug in this tool rather than a finding
        # about the server.
        detail = f"{type(exc).__name__}: {exc}"
        if "protocol" in str(exc).lower() or "version" in str(exc).lower():
            detail += (
                " -- this probe requires TLS 1.2 or newer, as every current"
                " client does; a server offering only 1.0 or 1.1 is unreachable"
                " for them too"
            )
        result.error = detail
    except OSError as exc:
        result.error = f"{type(exc).__name__}: {exc}"
    finally:
        if sock is not None:
            with contextlib.suppress(OSError):
                sock.close()

    result.total_ms = round((time.perf_counter() - started) * 1000.0, 3)
    return result


__all__ = ["DEFAULT_TIMEOUT", "ConnectionProbe", "probe"]
