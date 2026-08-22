"""Report renderers keyed by format name.

Each renderer takes a result payload dict and returns a string.
"""
from __future__ import annotations

import json
from typing import Any, Callable

NL = chr(10)

SEV_COLORS = {"ERROR": "#e5484d", "WARN": "#f5a623"}


def terminal(data: dict[str, Any]) -> str:
    lines = [f"{data.get('command', 'report')}:"]
    for key, value in data.items():
        if key in ("results", "findings") and isinstance(value, list):
            lines.append(f"{key}:")
            for item in value:
                d = item if isinstance(item, dict) else item.model_dump()
                lines.append(
                    f"  [{d.get('severity', d.get('status', ''))}] "
                    f"{d.get('rule_id', d.get('case_id', d.get('step', '')))} "
                    f"{d.get('message', d.get('description', ''))}")
        elif not isinstance(value, (dict, list)):
            lines.append(f"{key}: {value}")
    return NL.join(lines)


def markdown(data: dict[str, Any]) -> str:
    lines = [f"# apiverity report — {data.get('command', '?')}", ""]
    for k, v in data.items():
        if k not in ("results", "findings"):
            lines.append(f"- **{k}**: {v}")
    findings = data.get("findings", [])
    if findings:
        lines += ["", "| Rule | Severity | Message |", "|---|---|---|"]
        for f in findings:
            lines.append(f"| `{f.get('rule_id', '')}` | {f.get('severity', '')} "
                         f"| {f.get('message', '')} |")
    return NL.join(lines)


def junit(data: dict[str, Any]) -> str:
    failures = data.get("failed", data.get("errors", 0))
    total = data.get("total", 0)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>' + NL +
        f'<testsuite name="apiverity" tests="{total}" failures="{failures}">' +
        NL + "</testsuite>" + NL)


def html(data: dict[str, Any]) -> str:
    rows = ""
    for f in data.get("findings", []):
        sev = str(f.get("severity", "INFO"))
        color = SEV_COLORS.get(sev, "#3b82f6")
        rows += (
            f"<tr><td><code>{f.get('rule_id', '')}</code></td>"
            f"<td style='color:{color}'><b>{sev}</b></td>"
            f"<td>{f.get('message', '')}</td></tr>")
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>apiverity report</title>"
        "<style>body{font-family:system-ui;margin:2rem;background:#0d1117;"
        "color:#e6edf3}table{border-collapse:collapse;width:100%}"
        "td,th{padding:8px;border-bottom:1px solid #30363d;text-align:left}"
        "</style></head><body><h1>apiverity report</h1>"
        f"<p>{data.get('command', '')} — {data.get('spec', data.get('base_url', ''))}</p>"
        f"<table><tr><th>Rule</th><th>Severity</th><th>Message</th></tr>{rows}"
        "</table></body></html>")


def sarif(data: dict[str, Any]) -> str:
    return json.dumps({
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [{"tool": {"driver": {"name": "apiverity",
                 "informationUri": "https://github.com/webdevsamran/api-verity-lab"}},
                  "results": [
                      {"ruleId": f.get("rule_id", "APIVERITY"),
                       "level": {"ERROR": "error", "WARN": "warning"}.get(
                           str(f.get("severity")), "note"),
                       "message": {"text": f.get("message", "")}}
                      for f in data.get("findings", [])]}]}, indent=2)


RENDERERS: dict[str, Callable[[dict[str, Any]], str]] = {
    "terminal": terminal,
    "markdown": markdown,
    "junit": junit,
    "html": html,
    "sarif": sarif,
}