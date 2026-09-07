"""Artifact commands: report rendering, bundle export, local serving."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from apiverity.cli.commands.common import EXIT_OK, EXIT_USAGE, NL, _emit


def cmd_report(args: argparse.Namespace) -> int:
    """Render a bundle's result.json in the requested format."""
    result_path = Path(args.bundle) / "result.json"
    if not result_path.exists():
        print(f"error: no result.json in {args.bundle}", file=sys.stderr)
        return EXIT_USAGE
    data = json.loads(result_path.read_text(encoding="utf-8"))
    fmt = args.format
    if fmt == "json":
        print(json.dumps(data, indent=2))
    elif fmt == "markdown":
        lines = [f"# apiverity report — {data.get('command', '?')}"]
        for k, v in data.items():
            if k not in ("results", "findings"):
                lines.append(f"- **{k}**: {v}")
        print(NL.join(lines))
    elif fmt == "junit":
        failures = data.get("failed", data.get("errors", 0))
        total = data.get("total", 0)
        print('<?xml version="1.0" encoding="UTF-8"?>')
        print(f'<testsuite name="apiverity" tests="{total}" failures="{failures}">')
        print("</testsuite>")
    elif fmt == "yaml":
        import yaml

        print(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
    elif fmt == "html":
        rows = ""
        for f in data.get("findings", []):
            sev = str(f.get("severity", "INFO"))
            color = {"ERROR": "#e5484d", "WARN": "#f5a623"}.get(sev, "#3b82f6")
            rows += (
                f"<tr><td><code>{f.get('rule_id', '')}</code></td>"
                f"<td style='color:{color}'><b>{sev}</b></td>"
                f"<td>{f.get('message', '')}</td></tr>"
            )
        print(
            "<!doctype html><html><head><meta charset='utf-8'>"
            "<title>apiverity report</title>"
            "<style>body{font-family:system-ui;margin:2rem;background:#0d1117;"
            "color:#e6edf3}table{border-collapse:collapse;width:100%}"
            "td,th{padding:8px;border-bottom:1px solid #30363d;text-align:left}"
            "</style></head><body><h1>apiverity report</h1>"
            f"<p>{data.get('command', '')} — {data.get('spec', data.get('base_url', ''))}</p>"
            f"<table><tr><th>Rule</th><th>Severity</th><th>Message</th></tr>{rows}"
            "</table></body></html>"
        )
    elif fmt == "sarif":
        sarif = {
            "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
            "version": "2.1.0",
            "runs": [
                {
                    "tool": {
                        "driver": {
                            "name": "apiverity",
                            "informationUri": "https://github.com/webdevsamran/api-verity-lab",
                        }
                    },
                    "results": [
                        {
                            "ruleId": f.get("rule_id", "APIVERITY"),
                            "level": {"ERROR": "error", "WARN": "warning"}.get(
                                str(f.get("severity")), "note"
                            ),
                            "message": {"text": f.get("message", "")},
                        }
                        for f in data.get("findings", [])
                    ],
                }
            ],
        }
        print(json.dumps(sarif, indent=2))
    else:
        print(f"error: unknown format '{fmt}'", file=sys.stderr)
        return EXIT_USAGE
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
