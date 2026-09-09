"""Artifact commands: report rendering, bundle export, local serving."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from apiverity.cli.commands.common import EXIT_FINDINGS, EXIT_OK, EXIT_USAGE, NL, _emit


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


def cmd_verify(args: argparse.Namespace) -> int:
    """Check a bundle against its own SHA256SUMS.

    `export` has always written that file and nothing has ever read it, which
    makes the checksum decorative: a bundle emailed between machines, or
    downloaded from a CI artifact store, could be altered in any way and
    nothing would notice. A checksum nobody verifies is a comment.

    Three distinct failures, reported separately because they mean different
    things: a file whose digest no longer matches (tampered or corrupted), a
    file listed in SHA256SUMS that is gone (truncated), and a file present in
    the bundle that the manifest does not list (added).
    """
    import hashlib

    bundle = Path(args.bundle)
    if not bundle.is_dir():
        print(f"error: not a bundle directory: {bundle}", file=sys.stderr)
        return EXIT_USAGE

    sums = bundle / "SHA256SUMS"
    if not sums.is_file():
        print(
            f"error: {bundle} has no SHA256SUMS; it was not produced by `apiverity export`",
            file=sys.stderr,
        )
        return EXIT_USAGE

    declared: dict[str, str] = {}
    for line in sums.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, _, name = line.partition("  ")
        if not name:
            print(f"error: malformed SHA256SUMS line: {line!r}", file=sys.stderr)
            return EXIT_USAGE
        declared[name] = digest

    present = {f.name for f in bundle.iterdir() if f.is_file() and f.name != "SHA256SUMS"}

    mismatched: list[str] = []
    missing: list[str] = []
    for name, digest in sorted(declared.items()):
        path = bundle / name
        if not path.is_file():
            missing.append(name)
            continue
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            mismatched.append(name)
    unlisted = sorted(present - set(declared))

    ok = not (mismatched or missing or unlisted)
    _emit(
        {
            "tool": "apiverity",
            "command": "verify",
            "bundle": str(bundle),
            "verified": ok,
            "files_checked": len(declared),
            "mismatched": mismatched,
            "missing": missing,
            "unlisted": unlisted,
        },
        args.json,
    )
    if not ok:
        for name in mismatched:
            print(f"error: {name}: checksum does not match SHA256SUMS", file=sys.stderr)
        for name in missing:
            print(
                f"error: {name}: listed in SHA256SUMS but absent from the bundle", file=sys.stderr
            )
        for name in unlisted:
            print(
                f"error: {name}: present in the bundle but not listed in SHA256SUMS",
                file=sys.stderr,
            )
    return EXIT_OK if ok else EXIT_FINDINGS


def cmd_serve(args: argparse.Namespace) -> int:
    """Serve a result bundle (or web/dist) on localhost."""
    import functools
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    root = Path(args.directory)
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(root))
    httpd = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    if getattr(args, "json", False):
        # Before serve_forever blocks, for the same reason as `mock`.
        _emit(
            {
                "tool": "apiverity",
                "command": "serve",
                "base_url": f"http://127.0.0.1:{args.port}",
                "directory": str(root),
            },
            True,
        )
    else:
        print(f"serving {root} at http://127.0.0.1:{args.port} (Ctrl+C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return EXIT_OK
