"""Build one concise PR summary from .apiverity-artifacts/*.json."""
from __future__ import annotations

import glob
import json
import pathlib

NL = chr(10)

lines = ["## API Verity — contract review", ""]
for path in sorted(glob.glob(".apiverity-artifacts/*.json")):
    data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    findings = data.get("findings", [])
    breaking = [f for f in findings if f["severity"] == "ERROR"]
    warnings = [f for f in findings if f["severity"] == "WARN"]
    removed = sum(1 for f in findings if f["rule_id"] == "BRK-OP-REMOVED")
    added = sum(1 for f in findings if f["rule_id"] == "BRK-OP-ADDED")
    semver = [f for f in findings if f["rule_id"].startswith("SEMVER-")]
    verdict = ("✅ respected" if not semver
               else "❌ " + "; ".join(f["rule_id"] for f in semver))
    lines.append(f"### `{pathlib.Path(path).stem.replace('_', '/')}`")
    lines.append(f"- Breaking: **{len(breaking)}** · Warnings: **{len(warnings)}**")
    lines.append(f"- Removed endpoints: {removed} · New endpoints: {added}")
    lines.append(f"- Semver ({data.get('old_version', '?')} → "
                 f"{data.get('new_version', '?')}): {verdict}")
    for f in (breaking + warnings)[:10]:
        lines.append(f"  - `{f['rule_id']}` ({f['severity']}) {f['message']}")

lines += ["", "_One comment per PR — updated on each push._"]
pathlib.Path("pr-summary.md").write_text(NL.join(lines), encoding="utf-8")
print(NL.join(lines))