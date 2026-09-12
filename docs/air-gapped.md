---
description: >-
  Running api-verity-lab in a disconnected network: container image, Helm chart, vendored schemas, and an egress map generated from the source rather than promised.
---

# Running this in a disconnected network

Nothing here phones home. That is checkable rather than asserted: every place
the package can open a socket is walked out of the source into
[`docs/egress.md`](egress.md), and CI fails when the list and the code
disagree.

What follows is how to get it across the boundary and what to expect once it is
there.

## What crosses the air gap

Three artifacts, all built on a connected machine:

```bash
# 1. The wheel and its dependencies, as files.
python -m build
pip download api-verity-lab -d bundle/ --no-binary :none:

# 2. The container image, as a tarball.
docker build -t apiverity:0.2.0 .
docker save apiverity:0.2.0 -o bundle/apiverity-0.2.0.tar

# 3. The chart, as a directory. No repository to add.
cp -r deploy/helm/apiverity bundle/chart
```

Inside:

```bash
pip install --no-index --find-links bundle/ api-verity-lab
docker load -i bundle/apiverity-0.2.0.tar
helm install verity bundle/chart
```

`pip install --no-index` is the important flag. Without it pip reaches for
PyPI, fails slowly, and the failure looks like a broken package rather than a
closed network.

## The chart's defaults are already the disconnected ones

| | |
|---|---|
| `image.repository: apiverity` | no registry host, so it resolves to whatever the cluster's own registry serves |
| `image.pullPolicy: IfNotPresent` | does not reach out for a digest it already has |
| `networkPolicy.enabled: false` | see below |

A `NetworkPolicy` denying all egress is available and **off by default**. Not
because the server needs egress — it does not; it serves an API and writes a
file — but because a cluster whose CNI does not implement NetworkPolicy will
apply it cleanly, report success, and enforce nothing. An enforcement you
believe you have is worse than one you know you lack. Turn it on when you know
your CNI honours it:

```bash
helm install verity bundle/chart --set networkPolicy.enabled=true
```

## What the CLI still connects to, and when

Everything in [the egress map](egress.md) is behind a flag naming an address.
In a disconnected network the relevant ones are:

| Flag | What it reaches |
|---|---|
| `--base-url`, `--target` | the service under test, which is inside with you |
| `--allow-remote-refs` | a `$ref` to a host outside. Off by default; leave it off |
| `--otlp-endpoint` | your collector |
| `notify --send` | your webhook |
| a spec given as a URL | whatever that URL is |

None of them fires unless you pass it. There is no version check, no usage
report, and no background connection.

One script in this repository does reach the internet on purpose:
`scripts/fetch_competitor_meta.py` calls the GitHub API to refresh
`data/competitor-meta.json`. It is a maintenance script, not part of the
package, and it is not installed by the wheel.

## What stays behind

**The docs site.** `mkdocs` builds it from this repository; build it outside
and copy `site/`, or read the Markdown.

**The demo dashboard's fonts.** `web/` uses a system font stack and loads
nothing remote, so the built `dist/` is self-contained. Serve it from any
static host inside.

## One thing to check before you trust the install

```bash
apiverity self-test
```

It runs the engines against the bundled fixtures and touches no network. A
clean result means the package installed completely — which is the failure a
partial `pip download` produces, and it produces it silently.
