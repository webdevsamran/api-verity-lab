# eBPF capture: evaluated, not built

**Decision: no. `apiverity capture` covers the case, and eBPF costs an order of
magnitude more to maintain than it adds here.**

This is the write-up the roadmap asked for — study the prior art before
committing — and it is a decision document rather than a design.

## What was looked at

[Keploy](https://github.com/keploy/keploy), checked 2026-09-11: 18,452 stars,
Apache-2.0, Go, released `v3.6.57` that morning. Its `go.mod` depends on
`github.com/cilium/ebpf v0.21.0`, so eBPF is genuinely in its toolchain rather
than aspirational.

Two observations about the public tree, offered as observations rather than
conclusions: `pkg/core/` contains only `proxy`, and `pkg/core/proxy/` only
`tls`. A GitHub code search for `.c` files in the repository returned nothing,
which is weak evidence — code search does not index everything — but it is
consistent with the position recorded in the market analysis, that since v3
only the generic, HTTP and MySQL parsers are public and the rest compile in
from a private repository.

That matters for this evaluation in a specific way: **the part that would be
worth studying is the part that is not there to study.**

## What eBPF would buy

One thing, and it is real: **the client does not have to be reconfigured.**

`apiverity capture` is a forward proxy. Something has to point at it — a
`HTTP_PROXY` variable, a base URL in a config file, a sidecar rule. In a
service mesh or a container somebody else builds, that is a change to a
deployment you may not own.

Kernel-side capture has no such requirement. Attach, and traffic appears.

## What it would cost

### It is Linux-only, and this project is not

The test matrix runs Ubuntu, Windows and macOS across Python 3.11 and 3.12. An
eBPF capture path exists on one of those three. Every document describing
"capture" would need a platform qualifier, every test would need a skip, and
the feature most likely to be demonstrated to somebody is the one they cannot
run.

### It needs privileges the rest of the tool does not

`CAP_BPF` (Linux 5.8+) or `CAP_SYS_ADMIN` before that, plus `CAP_PERFMON` for
most useful attachments. Nothing else in this project asks for more than the
permission to open a socket and read a file, and a governance tool that wants
root to do its job has changed what it is asking a team to trust it with.

### TLS is where the real cost is

A socket-level kernel hook sees what crosses the socket, which for HTTPS is
ciphertext. Recording it would produce a corpus of encrypted bytes — a capture
that runs, reports success, and contains nothing usable.

The standard answer is uprobes on the TLS library's own read and write symbols
— `SSL_read`/`SSL_write` for OpenSSL, the equivalents for BoringSSL, GnuTLS and
NSS, and Go's `crypto/tls`, which is statically linked into every Go binary at
its own offsets. That is:

- a symbol table per library, per version, per distribution build;
- a fallback for stripped and statically linked binaries;
- a Go-specific path, because Go does not use the system TLS library at all;
- and continuous maintenance as any of those change.

This is not a hard thing to start. It is a hard thing to keep correct, and its
failure mode is silence.

### The failure mode is the one this project treats as worst

An eBPF capture that attaches to the wrong symbol, or to a binary whose TLS it
cannot see into, records nothing and exits zero.

`SAFETY_MODEL.md` names this class directly: the tool asserting something it
did not establish. A corpus that is empty because nothing happened and a corpus
that is empty because the probe never saw anything are the same file, and the
run cannot tell you which it produced. The proxy cannot fail that way — traffic
either goes through it or does not reach the target at all.

## What was decided instead

`apiverity capture`, shipped: a forward-to-one-target proxy that redacts before
writing and names everything it did not record. It carries the same information
into the same HAR corpus, with none of the above.

The cost it does not avoid is the one eBPF exists to solve — something has to
point at it. That is stated in [its own documentation](capture.md) rather than
worked around.

## What would change this

Three things, and none of them is "somebody asked":

1. **A supported capture library to depend on**, rather than uprobe offsets to
   maintain. If the eBPF ecosystem grows a stable, maintained plaintext-capture
   layer that is somebody else's job to keep working, the maintenance argument
   above evaporates.
2. **A Linux-only deployment shape that matters more than the matrix.** If the
   dominant way this tool is run becomes a Linux sidecar, "it works on one of
   three platforms" stops being the objection it is now.
3. **A case the proxy genuinely cannot reach**, reported by somebody who tried
   it. Right now that case is hypothetical, and building for a hypothetical is
   how a project acquires a subsystem nobody uses.

Until one of those, this stays a note rather than a module.
