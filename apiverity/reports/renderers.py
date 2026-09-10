"""Report renderers keyed by format name.

Each renderer takes a result payload dict and returns a string. This module is
the single implementation: `apiverity report` dispatches through `RENDERERS`
rather than carrying its own copy, which is how the two drifted apart before
(#22 -- the CLI's markdown had lost the findings table this module still
emitted).

Payloads arrive as plain dicts, already serialised from `Finding`, so every
lookup here is defensive: a renderer must not raise on a bundle written by an
older version that lacks a key.
"""

from __future__ import annotations

import hashlib
import html as _html
import json
from collections.abc import Callable
from typing import Any

NL = chr(10)

SEV_COLORS = {"ERROR": "#e5484d", "WARN": "#f5a623"}
SEV_ORDER = ("ERROR", "WARN", "INFO")
SARIF_LEVELS = {"ERROR": "error", "WARN": "warning"}
TOOL_URI = "https://github.com/webdevsamran/api-verity-lab"


# --- shared helpers ---------------------------------------------------------


def _findings(data: dict[str, Any]) -> list[dict[str, Any]]:
    raw = data.get("findings", [])
    if not isinstance(raw, list):
        return []
    return [f for f in raw if isinstance(f, dict)]


def _severity(finding: dict[str, Any]) -> str:
    return str(finding.get("severity", "INFO")).upper()


def _location(finding: dict[str, Any]) -> dict[str, Any] | None:
    """The location to report a finding at.

    `new_location` first: a reviewer wants the line in the spec they are
    changing, not the one they are changing away from. Removals only have an
    old location, so that is the fallback.
    """
    for key in ("new_location", "location"):
        value = finding.get(key)
        if isinstance(value, dict) and value.get("file"):
            return value
    return None


def _by_severity(findings: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
    """Group findings by severity, most severe first, skipping empty groups.

    Unknown severities are kept rather than dropped -- a plugin may emit one,
    and silently swallowing findings is the worst failure mode a report has.
    """
    groups = {sev: [f for f in findings if _severity(f) == sev] for sev in SEV_ORDER}
    for sev in sorted({_severity(f) for f in findings} - set(SEV_ORDER)):
        groups[sev] = [f for f in findings if _severity(f) == sev]
    return [(sev, items) for sev, items in groups.items() if items]


def _subject(data: dict[str, Any]) -> str:
    return str(data.get("spec", data.get("base_url", "")))


def _where(finding: dict[str, Any]) -> str:
    """`file:line:column`, trimmed to what is actually known."""
    loc = _location(finding)
    if not loc:
        return ""
    line = loc.get("line") or 0
    if not line:
        return str(loc["file"])
    column = loc.get("column") or 0
    return f"{loc['file']}:{line}" + (f":{column}" if column else "")


# --- terminal ---------------------------------------------------------------


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
                    f"{d.get('message', d.get('description', ''))}"
                )
        elif not isinstance(value, (dict, list)):
            lines.append(f"{key}: {value}")
    return NL.join(lines)


# --- markdown ---------------------------------------------------------------


def _md_cell(value: object) -> str:
    """Make a value safe inside a markdown table cell.

    An unescaped pipe silently splits the row into extra columns, so a rule
    about a field named `a|b` would quietly corrupt the table from that row
    onward.
    """
    return str(value).replace("\\", "\\\\").replace("|", "\\|").replace(NL, " ")


def markdown(data: dict[str, Any]) -> str:
    lines = [f"# apiverity report - {data.get('command', '?')}", ""]
    for key, value in data.items():
        if key not in ("results", "findings"):
            lines.append(f"- **{key}**: {value}")

    findings = _findings(data)
    if not findings:
        return NL.join(lines)

    groups = _by_severity(findings)
    lines += ["", f"## Findings ({len(findings)})", ""]
    lines.append(" | ".join(f"**{sev}**: {len(items)}" for sev, items in groups))

    show_location = any(_where(f) for f in findings)
    header = ["Rule", "Message"] + (["Location"] if show_location else [])
    for sev, items in groups:
        # Collapsible, with ERROR left open: a report with 300 INFO rows is
        # unreadable inline, but nobody should have to click to discover that
        # something broke.
        plural = "s" if len(items) != 1 else ""
        lines += [
            "",
            "<details open>" if sev == "ERROR" else "<details>",
            f"<summary><b>{sev}</b> - {len(items)} finding{plural}</summary>",
            "",
            "| " + " | ".join(header) + " |",
            "|" + "---|" * len(header),
        ]
        for finding in items:
            row = [
                f"`{_md_cell(finding.get('rule_id', ''))}`",
                _md_cell(finding.get("message", "")),
            ]
            if show_location:
                where = _where(finding)
                row.append(f"`{_md_cell(where)}`" if where else "")
            lines.append("| " + " | ".join(row) + " |")
        lines += ["", "</details>"]
    return NL.join(lines)


# --- pull request comment ---------------------------------------------------

#: Lets a workflow find its own previous comment and edit it, instead of
#: adding one per push. A bot that posts twelve comments on a busy branch gets
#: muted, and a muted gate is the same as no gate.
PR_MARKER = "<!-- apiverity:pr-comment:v1 -->"

#: GitHub refuses an issue comment body over 65,536 characters. Budgeting a
#: little under it leaves room for the marker and the footer, and truncation
#: says how much it dropped rather than trailing off.
PR_COMMENT_BUDGET = 60_000

_VERDICT = {
    "blocked": ("Blocked", "This change breaks consumers of the contract."),
    "review": ("Needs review", "Nothing here blocks, but some of it is worth a look."),
    "clear": ("Clear", "No breaking changes found."),
}


def _instead(finding: dict[str, Any]) -> str:
    """The non-breaking alternative a finding carries, if it carries one.

    Written by `breaking --suggest-fix` into `metadata.instead`. Read
    defensively: an artifact from a run without that flag simply has none, and
    a renderer that raised on it would make the flag load-bearing.
    """
    metadata = finding.get("metadata")
    if isinstance(metadata, dict):
        value = metadata.get("instead")
        if isinstance(value, str) and value.strip():
            return value.strip()
    # Deliberately no fallback to `hint`. A hint says *why* the change breaks
    # ("enum values removed: ['guest']"); printing that under "Instead:" tells
    # an author to do the thing they were just told not to do.
    return ""


def _pr_verdict(findings: list[dict[str, Any]]) -> str:
    if any(_severity(f) == "ERROR" for f in findings):
        return "blocked"
    if any(_severity(f) == "WARN" for f in findings):
        return "review"
    return "clear"


def pr_comment(data: dict[str, Any]) -> str:
    """A pull request comment: the verdict, then what to ship instead.

    Deliberately not the markdown report with a different header. Two things
    make a review comment different from a report, and both come from the same
    observation -- a bot that only says no gets switched off:

    Findings are grouped by *rule*, not by severity, and each group carries its
    non-breaking alternative once. Forty rows of "a required field was added"
    followed by the same paragraph forty times is noise; one group of forty
    with one instruction is a review comment.

    And the alternative leads. The objection is one line; the route to shipping
    the same change without breaking anyone is the part the author came for.
    """
    findings = _findings(data)
    verdict = _pr_verdict(findings)
    title, subtitle = _VERDICT[verdict]

    counts = {sev: len(items) for sev, items in _by_severity(findings)}
    tally = ", ".join(f"{count} {sev.lower()}" for sev, count in counts.items())

    subject = _subject(data)
    old_spec, new_spec = data.get("old_spec"), data.get("new_spec")
    lines = [
        PR_MARKER,
        f"## apiverity - {title}",
        "",
        subtitle,
        "",
    ]
    if old_spec and new_spec:
        lines.append(f"`{_md_cell(old_spec)}` -> `{_md_cell(new_spec)}`")
    elif subject:
        lines.append(f"`{_md_cell(subject)}`")
    if tally:
        lines.append("")
        lines.append(f"**{len(findings)} finding(s)**: {tally}")

    summary = data.get("summary")
    advice = data.get("version_advice")
    # Only when `--summary` did not run: its `what_to_do` already opens with
    # the version to release as, and saying it twice in one comment reads as a
    # template that was never looked at.
    if isinstance(advice, dict) and not isinstance(summary, dict):
        suggested = advice.get("suggested_version")
        bump = advice.get("required_bump")
        if suggested:
            note = f"Release this as **{_md_cell(suggested)}**"
            lines += ["", note + (f" (a {_md_cell(bump)} bump)." if bump else ".")]

    # `breaking --summary` already produces the three things a reviewer wants
    # in this order -- the verdict, what changed grouped, and what to do -- so
    # this renders that rather than writing a second, divergent version of it.
    if isinstance(summary, dict):
        lines += _pr_summary(summary)
    elif isinstance(summary, str) and summary.strip():
        lines += ["", "> " + summary.strip().replace(NL, NL + "> ")]

    if not findings:
        lines += ["", "---", _pr_footer(data)]
        return NL.join(lines)

    # Rule order follows severity, then how many findings the rule produced:
    # the thing that broke most is the thing to read first.
    ordered: list[tuple[str, list[dict[str, Any]]]] = []
    for sev in SEV_ORDER + tuple(sorted(set(counts) - set(SEV_ORDER))):
        by_rule: dict[str, list[dict[str, Any]]] = {}
        for finding in findings:
            if _severity(finding) != sev:
                continue
            by_rule.setdefault(str(finding.get("rule_id", "")), []).append(finding)
        ordered += sorted(by_rule.items(), key=lambda item: (-len(item[1]), item[0]))

    body: list[str] = []
    dropped = 0
    used = sum(len(line) + 1 for line in lines)
    for rule_id, group in ordered:
        block = _pr_rule_block(rule_id, group)
        cost = sum(len(line) + 1 for line in block)
        if used + cost > PR_COMMENT_BUDGET:
            dropped += len(group)
            continue
        used += cost
        body += block

    lines += body
    if dropped:
        lines += [
            "",
            f"_{dropped} further finding(s) omitted to fit GitHub's comment size limit. "
            "The full set is in the uploaded `result-v1` artifacts._",
        ]
    lines += ["", "---", _pr_footer(data)]
    return NL.join(lines)


def _pr_summary(summary: dict[str, Any]) -> list[str]:
    """The `--summary` block, rendered for a reviewer rather than a terminal."""
    lines: list[str] = []
    verdict = summary.get("verdict")
    if isinstance(verdict, str) and verdict.strip():
        lines += ["", verdict.strip()]
    for key, heading in (("what_changed", "What changed"), ("what_to_do", "What to do")):
        items = summary.get(key)
        if not isinstance(items, list) or not items:
            continue
        lines += ["", f"**{heading}**", ""]
        lines += [f"- {item}" for item in items if isinstance(item, str)]
    return lines


def _pr_rule_block(rule_id: str, group: list[dict[str, Any]]) -> list[str]:
    sev = _severity(group[0])
    # GitHub emoji shortcodes rather than the characters themselves. They
    # render identically there and the file stays pure ASCII, which matters
    # because this text is written to disk by CI and read back on runners
    # whose default encoding is not always UTF-8 -- the same trap that made
    # `apiverity validate` exit 4 on a contract titled in Japanese.
    icon = {
        "ERROR": ":red_circle:",
        "WARN": ":large_orange_diamond:",
    }.get(sev, ":small_blue_diamond:")
    plural = "s" if len(group) != 1 else ""
    block = [
        "",
        f"### {icon} `{rule_id}` - {len(group)} finding{plural}",
    ]

    instead = next((_instead(f) for f in group if _instead(f)), "")
    if instead:
        # First, and in bold: this is the line the author acts on. The
        # objection below is the evidence for it.
        block += ["", f"**Instead:** {instead}"]

    block += ["", "<details><summary>What changed</summary>", ""]
    for finding in group:
        where = _where(finding)
        message = _md_cell(finding.get("message", ""))
        block.append(f"- {message}" + (f" (`{_md_cell(where)}`)" if where else ""))
    block += ["", "</details>"]
    return block


def _pr_footer(data: dict[str, Any]) -> str:
    version = data.get("tool_version", "")
    rule = "`apiverity explain <RULE-ID>`"
    suffix = f" v{version}" if version else ""
    return (
        f"<sub>apiverity{suffix} - every rule has a documented non-breaking route; "
        f"run {rule} for one. Severity is configurable per rule, and an accepted "
        "change can be recorded rather than argued.</sub>"
    )


# --- junit ------------------------------------------------------------------


def _attr(value: object) -> str:
    return _html.escape(str(value), quote=True)


def junit(data: dict[str, Any]) -> str:
    """JUnit XML with one testcase per finding.

    The previous version declared `tests="N"` over an empty testsuite, so every
    consumer reported zero tests and no failure was attributable to anything.
    A count with none of the cases behind it is not a report.
    """
    findings = _findings(data)
    if not findings:
        # No findings payload at all: fall back to the run's own counters
        # rather than inventing cases that were never produced.
        failures = int(data.get("failed", data.get("errors", 0)) or 0)
        total = int(data.get("total", 0) or 0)
        return NL.join(
            [
                '<?xml version="1.0" encoding="UTF-8"?>',
                f'<testsuite name="apiverity" tests="{total}" failures="{failures}">',
                "</testsuite>",
                "",
            ]
        )

    cases: list[str] = []
    for finding in findings:
        severity = _severity(finding)
        message = str(finding.get("message", ""))
        name = f"{finding.get('rule_id', 'APIVERITY')}: {message}"
        classname = finding.get("operation_key") or data.get("command", "apiverity")
        head = f'  <testcase classname="{_attr(classname)}" name="{_attr(name)}"'
        if severity in ("ERROR", "WARN"):
            body = _html.escape(str(finding.get("hint") or message))
            where = _where(finding)
            if where:
                body = f"{body}{NL}      at {_html.escape(where)}"
            cases.append(
                f"{head}>{NL}"
                f'    <failure type="{_attr(severity)}" message="{_attr(message)}">{NL}'
                f"      {body}{NL}"
                f"    </failure>{NL}  </testcase>"
            )
        else:
            cases.append(f"{head} />")

    failures = sum(1 for f in findings if _severity(f) in ("ERROR", "WARN"))
    return NL.join(
        [
            '<?xml version="1.0" encoding="UTF-8"?>',
            f'<testsuite name="apiverity" tests="{len(findings)}" failures="{failures}">',
            NL.join(cases),
            "</testsuite>",
            "",
        ]
    )


# --- html -------------------------------------------------------------------

# No @font-face, no <link>, no CDN. A report is usually opened from a CI
# artifact on a machine that cannot reach the network, and a stylesheet that
# silently fails to load is a report that silently looks broken.
_HTML_STYLE = (
    "body{font-family:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;"
    "margin:2rem;background:#0d1117;color:#e6edf3;line-height:1.5}"
    "table{border-collapse:collapse;width:100%}"
    "td,th{padding:8px;border-bottom:1px solid #30363d;text-align:left;vertical-align:top}"
    "code{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:.9em}"
    ".filters{display:flex;gap:.5rem;flex-wrap:wrap;margin:1rem 0}"
    ".filters button{background:#161b22;color:#e6edf3;border:1px solid #30363d;"
    "border-radius:999px;padding:.35rem .9rem;cursor:pointer;font:inherit}"
    ".filters button[aria-pressed=true]{background:#1f6feb;border-color:#1f6feb}"
    ".muted{color:#8b949e}.loc{white-space:nowrap}"
)

_HTML_SCRIPT = """
(function () {
  var rows = [].slice.call(document.querySelectorAll('tr[data-severity]'));
  var buttons = [].slice.call(document.querySelectorAll('.filters button'));
  function current() {
    var m = /(?:^|[#&])sev=([A-Za-z]+)/.exec(window.location.hash || '');
    return m ? m[1].toUpperCase() : 'ALL';
  }
  function apply() {
    var sev = current();
    rows.forEach(function (row) {
      row.hidden = sev !== 'ALL' && row.getAttribute('data-severity') !== sev;
    });
    buttons.forEach(function (b) {
      b.setAttribute('aria-pressed', String(b.getAttribute('data-sev') === sev));
    });
    var shown = rows.filter(function (r) { return !r.hidden; }).length;
    var label = document.getElementById('shown');
    if (label) { label.textContent = shown + ' of ' + rows.length + ' shown'; }
  }
  buttons.forEach(function (b) {
    b.addEventListener('click', function () {
      /* Written to the hash rather than held in a variable, so a filtered
         view is a URL you can paste into a review. */
      window.location.hash = 'sev=' + b.getAttribute('data-sev');
    });
  });
  window.addEventListener('hashchange', apply);
  apply();
})();
"""


def _html_location(finding: dict[str, Any]) -> str:
    where = _where(finding)
    if not where:
        return '<span class="muted">-</span>'
    pointer = (_location(finding) or {}).get("pointer") or ""
    title = f' title="{_attr(pointer)}"' if pointer else ""
    return f'<code class="loc"{title}>{_html.escape(where)}</code>'


def html(data: dict[str, Any]) -> str:
    """One self-contained file: no external CSS, fonts, or scripts.

    Filter state lives in the URL hash (`#sev=ERROR`), so a filtered view is
    something you can paste into a review rather than something you describe.
    """
    findings = _findings(data)
    groups = _by_severity(findings)

    rows = ""
    for sev, items in groups:
        color = SEV_COLORS.get(sev, "#3b82f6")
        for finding in items:
            message = _html.escape(str(finding.get("message", "")))
            hint = finding.get("hint")
            if hint:
                message += f'<br><span class="muted">{_html.escape(str(hint))}</span>'
            rows += (
                f'<tr data-severity="{_attr(sev)}">'
                f"<td><code>{_html.escape(str(finding.get('rule_id', '')))}</code></td>"
                f'<td style="color:{color}"><b>{_html.escape(sev)}</b></td>'
                f"<td>{message}</td>"
                f"<td>{_html_location(finding)}</td></tr>"
            )

    chips = "".join(
        f'<button type="button" data-sev="{_attr(sev)}" aria-pressed="false">'
        f"{_html.escape(sev)} ({len(items)})</button>"
        for sev, items in [("ALL", findings), *groups]
    )
    command = _html.escape(str(data.get("command", "")))
    subject = _html.escape(_subject(data))
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>apiverity report</title>"
        f"<style>{_HTML_STYLE}</style></head><body>"
        "<h1>apiverity report</h1>"
        f"<p>{command}{' - ' + subject if subject else ''}</p>"
        f'<div class="filters" role="group" aria-label="filter by severity">{chips}</div>'
        '<p class="muted" id="shown" role="status"></p>'
        "<table><thead><tr><th>Rule</th><th>Severity</th><th>Message</th>"
        "<th>Location</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
        f"<script>{_HTML_SCRIPT}</script>"
        "</body></html>"
    )


# --- sarif ------------------------------------------------------------------


def _sarif_region(loc: dict[str, Any]) -> dict[str, Any] | None:
    """A SARIF region, or None when there is no real line to point at.

    `startLine` is 1-based and must be positive; SourceLocation uses 0 for
    "unknown". Emitting `startLine: 0` is a schema violation that GitHub
    rejects the whole upload for, so an unknown line means no region rather
    than a wrong one.
    """
    line = loc.get("line") or 0
    if not isinstance(line, int) or line < 1:
        return None
    region: dict[str, Any] = {"startLine": line}
    column = loc.get("column") or 0
    if isinstance(column, int) and column >= 1:
        region["startColumn"] = column
    return region


def _sarif_location(finding: dict[str, Any]) -> dict[str, Any] | None:
    loc = _location(finding)
    if not loc:
        return None
    physical: dict[str, Any] = {"artifactLocation": {"uri": str(loc["file"]).replace("\\", "/")}}
    region = _sarif_region(loc)
    if region:
        physical["region"] = region
    entry: dict[str, Any] = {"physicalLocation": physical}
    pointer = loc.get("pointer")
    if pointer:
        # The JSON pointer is what a reader can act on when the line is
        # unknown, and it survives reformatting of the document.
        entry["logicalLocations"] = [{"fullyQualifiedName": str(pointer), "kind": "member"}]
    return entry


def _fingerprint(finding: dict[str, Any]) -> str:
    """Stable identity for a finding, for alert tracking across runs.

    Deliberately excludes the message: messages embed concrete values ("1 ->
    10"), so keying on them would retire and re-raise the same alert on every
    edit. Rule, operation and JSON pointer identify the same problem in the
    same place.
    """
    loc = _location(finding) or {}
    parts = [
        str(finding.get("rule_id", "")),
        str(finding.get("operation_key") or ""),
        str(loc.get("pointer") or ""),
        str(loc.get("file") or ""),
    ]
    return hashlib.sha256("\x00".join(parts).encode("utf-8")).hexdigest()[:16]


def _sarif_rules(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rule metadata for the ids actually present in this run.

    Descriptions come from the breaking-change catalog when the id is one of
    ours. An unknown id -- a plugin's -- still gets an entry so `ruleIndex`
    stays valid, just without a description invented for it.
    """
    try:
        from apiverity.rules.breaking import CATALOG
    except Exception:  # pragma: no cover - defensive; the catalog always imports
        catalog: dict[str, Any] = {}
    else:
        catalog = dict(CATALOG)

    rules: list[dict[str, Any]] = []
    for rule_id in sorted({str(f.get("rule_id", "")) for f in findings if f.get("rule_id")}):
        rule: dict[str, Any] = {"id": rule_id, "name": rule_id}
        spec = catalog.get(rule_id)
        if spec is not None:
            rule["shortDescription"] = {"text": spec.description}
            rule["defaultConfiguration"] = {
                "level": SARIF_LEVELS.get(str(spec.severity.value).upper(), "note")
            }
        rule["helpUri"] = f"{TOOL_URI}/blob/main/docs/rule-catalog.md"
        rules.append(rule)
    return rules


def sarif(data: dict[str, Any]) -> str:
    findings = _findings(data)
    rules = _sarif_rules(findings)
    index = {str(rule["id"]): i for i, rule in enumerate(rules)}

    results: list[dict[str, Any]] = []
    for finding in findings:
        rule_id = str(finding.get("rule_id", "APIVERITY"))
        result: dict[str, Any] = {
            "ruleId": rule_id,
            "level": SARIF_LEVELS.get(_severity(finding), "note"),
            "message": {"text": str(finding.get("message", ""))},
            "partialFingerprints": {"apiverityFindingV1": _fingerprint(finding)},
        }
        if rule_id in index:
            result["ruleIndex"] = index[rule_id]
        location = _sarif_location(finding)
        if location:
            result["locations"] = [location]
        properties = {
            key: finding[key] for key in ("hint", "change_id", "operation_key") if finding.get(key)
        }
        if properties:
            result["properties"] = properties
        results.append(result)

    driver: dict[str, Any] = {"name": "apiverity", "informationUri": TOOL_URI, "rules": rules}
    version = str(data.get("version") or data.get("tool_version") or "")
    if version:
        driver["version"] = version
    return json.dumps(
        {
            "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
            "version": "2.1.0",
            "runs": [{"tool": {"driver": driver}, "results": results}],
        },
        indent=2,
    )


# --- json / yaml ------------------------------------------------------------


def as_json(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2, default=str)


def as_yaml(data: dict[str, Any]) -> str:
    import yaml

    return str(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))


def _compliance(key: str) -> Callable[[dict[str, Any]], str]:
    """A renderer bound to one published framework.

    Named functions rather than `functools.partial` so a traceback says which
    framework was being rendered.
    """
    from apiverity.reports.compliance import FRAMEWORKS, render_markdown

    def render(data: dict[str, Any]) -> str:
        return render_markdown(FRAMEWORKS[key], data)

    render.__name__ = f"compliance_{key.replace('-', '_')}"
    return render


def _oasdiff_render(data: dict[str, Any]) -> str:
    from apiverity.reports.oasdiff import render

    return render(data)


RENDERERS: dict[str, Callable[[dict[str, Any]], str]] = {
    "terminal": terminal,
    "markdown": markdown,
    "pr-comment": pr_comment,
    "junit": junit,
    "html": html,
    "sarif": sarif,
    "json": as_json,
    "yaml": as_yaml,
    # oasdiff's own changelog shape, so a team already gating on it can point
    # this at their pipeline without rewriting the `jq` in it. Verified
    # against oasdiff v1.31.0; see apiverity/reports/oasdiff.py for what maps
    # and what deliberately does not.
    "oasdiff": _oasdiff_render,
    # Every control of the framework appears in these, including the ones this
    # tool cannot assess. A mapping report that lists only the controls it hit
    # reads as a clean bill of health for the rest.
    "owasp-mcp": _compliance("owasp-mcp"),
    "owasp-asi": _compliance("owasp-asi"),
    "owasp-api": _compliance("owasp-api"),
}
