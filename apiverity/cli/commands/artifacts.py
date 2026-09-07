"""Artifact commands: report rendering, bundle export, local serving."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from apiverity.cli.commands.common import EXIT_OK, EXIT_USAGE, NL, _emit


def cmd_report(args: argparse.Namespace) -> int:
    """Render a bundle's result.json in the requested format.

    Dispatches through the shared RENDERERS table rather than reimplementing
    each format. This command used to carry its own copy of every renderer,
    and they had already drifted -- its markdown had lost the findings table
    that `apiverity.reports.renderers` still emitted, so the same bundle
    produced two different reports depending on how you asked for it (#22).
    """
    from apiverity.reports.renderers import RENDERERS

    result_path = Path(args.bundle) / "result.json"
    if not result_path.exists():
        print(f"error: no result.json in {args.bundle}", file=sys.stderr)
        return EXIT_USAGE
    data = json.loads(result_path.read_text(encoding="utf-8"))

    renderer = RENDERERS.get(args.format)
    if renderer is None:
        known = ", ".join(sorted(RENDERERS))
        print(f"error: unknown format '{args.format}' (known: {known})", file=sys.stderr)
        return EXIT_USAGE
    print(renderer(data))
    return EXIT_OK


def cmd_export(args: argparse.Namespace) -> int:
    """Write a .apiverity bundle: result.json, contract snapshot+hash,
    config, sanitized failing cases, workflow manifests, performance
    summary and SHA256 checksums."""
    import hashlib

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    payload = (
        json.loads(args.data)
        if args.data.startswith("{")
        else {"tool": "apiverity", "note": args.data}
    )

    if args.spec:
        spec_bytes = Path(args.spec).read_bytes()
        (out / "contract-snapshot").write_bytes(spec_bytes)
        payload["contract_hash"] = hashlib.sha256(spec_bytes).hexdigest()
        payload["contract_snapshot"] = "contract-snapshot"
    if args.config:
        (out / "config.yaml").write_text(
            Path(args.config).read_text(encoding="utf-8"), encoding="utf-8"
        )
    if args.workflow:
        (out / "workflow-manifest.yaml").write_text(
            Path(args.workflow).read_text(encoding="utf-8"), encoding="utf-8"
        )
    if args.perf:
        (out / "performance-summary.json").write_text(
            Path(args.perf).read_text(encoding="utf-8"), encoding="utf-8"
        )

    # sanitized failing cases only (violations + reproduction, no bodies)
    if isinstance(payload.get("results"), list):
        failing = [
            r for r in payload["results"] if isinstance(r, dict) and r.get("status") != "pass"
        ]
        (out / "failing-cases.json").write_text(json.dumps(failing, indent=2), encoding="utf-8")

    (out / "result.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    checksums = {}
    for f in sorted(out.iterdir()):
        if f.is_file():
            checksums[f.name] = hashlib.sha256(f.read_bytes()).hexdigest()
    (out / "SHA256SUMS").write_text(
        NL.join(f"{v}  {k}" for k, v in checksums.items()) + NL, encoding="utf-8"
    )
    _emit(
        {"tool": "apiverity", "command": "export", "bundle": str(out), "files": sorted(checksums)},
        args.json,
    )
    return EXIT_OK


def cmd_serve(args: argparse.Namespace) -> int:
    """Serve a result bundle (or web/dist) on localhost."""
    import functools
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    root = Path(args.directory)
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(root))
    httpd = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    print(f"serving {root} at http://127.0.0.1:{args.port} (Ctrl+C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return EXIT_OK
