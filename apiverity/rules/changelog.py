"""Changelog generation from a change set + findings.

Groups entries by service, then operation, then severity, and renders
Markdown or HTML.
"""

from __future__ import annotations

import html
from collections import defaultdict

from apiverity.core.model import Change, Finding, Severity

NL = chr(10)
_SEVERITY_BADGE = {
    Severity.ERROR: "🔴 BREAKING",
    Severity.WARN: "🟡 RISKY",
    Severity.INFO: "🔵 INFO",
}


def _grouped(
    changes: list[Change], findings: list[Finding]
) -> dict[str, dict[str, list[tuple[str, str]]]]:
    """service -> operation -> [(severity_label, text)]"""
    severity_by_change = {f.change_id: f.severity for f in findings if f.change_id}
    grouped: dict[str, dict[str, list[tuple[str, str]]]] = defaultdict(lambda: defaultdict(list))
    for change in changes:
        sev = severity_by_change.get(change.id, Severity.INFO)
        grouped["API"][change.operation_key].append(
            (_SEVERITY_BADGE[sev], f"`{change.id}` {change.description}")
        )
    for finding in findings:
        if finding.change_id is None:
            op = finding.operation_key or "(general)"
            grouped["API"][op].append(
                (_SEVERITY_BADGE[finding.severity], f"`{finding.rule_id}` {finding.message}")
            )
    return grouped


def render_markdown(
    title: str,
    old_version: str,
    new_version: str,
    changes: list[Change],
    findings: list[Finding],
) -> str:
    grouped = _grouped(changes, findings)
    lines = [
        f"# Changelog: {title}",
        "",
        f"**{old_version} → {new_version}**",
        "",
    ]
    counts: dict[str, int] = defaultdict(int)
    for op_entries in grouped.values():
        for items in op_entries.values():
            for badge, _ in items:
                counts[badge] += 1
    if counts:
        lines.append(" | ".join(f"{badge} x{n}" for badge, n in sorted(counts.items())))
        lines.append("")
    for service, operations in sorted(grouped.items()):
        lines.append(f"## {service}")
        lines.append("")
        for op in sorted(operations):
            lines.append(f"### `{op}`")
            lines.append("")
            entries = sorted(operations[op], key=lambda e: 0)
            for badge, text in entries:
                lines.append(f"- {badge} — {text}")
            lines.append("")
    return NL.join(lines)


def render_html(
    title: str,
    old_version: str,
    new_version: str,
    changes: list[Change],
    findings: list[Finding],
) -> str:
    grouped = _grouped(changes, findings)
    parts = [
        "<!doctype html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>Changelog: {html.escape(title)}</title>",
        "<style>",
        "body{font-family:system-ui,sans-serif;margin:2rem;max-width:60rem;}"
        ".breaking{color:#b91c1c}.risky{color:#a16207}.info{color:#1d4ed8}"
        "h3 code{background:#f4f4f5;padding:.1rem .35rem;border-radius:.25rem}"
        "</style></head><body>",
        f"<h1>Changelog: {html.escape(title)}</h1>",
        f"<p><strong>{html.escape(old_version)} → {html.escape(new_version)}</strong></p>",
    ]
    for service, operations in sorted(grouped.items()):
        parts.append(f"<h2>{html.escape(service)}</h2>")
        for op in sorted(operations):
            parts.append(f"<h3><code>{html.escape(op)}</code></h3><ul>")
            for badge, text in operations[op]:
                css = "breaking" if "BREAKING" in badge else "risky" if "RISKY" in badge else "info"
                parts.append(f'<li class="{css}">{html.escape(badge)} — {html.escape(text)}</li>')
            parts.append("</ul>")
    parts.append("</body></html>")
    return "".join(parts)


def generate_changelog(
    title: str,
    old_version: str,
    new_version: str,
    changes: list[Change],
    findings: list[Finding],
    fmt: str = "markdown",
) -> str:
    if fmt == "html":
        return render_html(title, old_version, new_version, changes, findings)
    return render_markdown(title, old_version, new_version, changes, findings)
