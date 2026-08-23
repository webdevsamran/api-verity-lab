"""Fetch live GitHub metadata for competitor repos via the authenticated gh CLI.

Writes data/competitor-meta.json and prints a compact TSV summary.
Access date is recorded for evidence purposes. Temp-free: writes only the
final artifact.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

REPOS = [
    "oasdiff/oasdiff",
    "schemathesis/schemathesis",
    "stoplightio/spectral",
    "pact-foundation/pact-js",
    "useoptic/optic",
    "apiaryio/dredd",
    "stoplightio/prism",
    "wiremock/wiremock",
    "SpectoLabs/hoverfly",
    "karatelabs/karate",
    "grafana/k6",
    "postmanlabs/newman",
    "graphql-hive/graphql-inspector",
    "bufbuild/buf",
]


def gh_json(endpoint: str) -> dict[str, object] | None:
    try:
        raw = subprocess.run(
            ["gh", "api", endpoint],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=True,
        ).stdout
        return json.loads(raw)  # type: ignore[no-any-return]
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return None


def main() -> None:
    results: dict[str, dict[str, object]] = {}
    for repo in REPOS:
        meta = gh_json(f"repos/{repo}")
        rel = gh_json(f"repos/{repo}/releases/latest")
        entry: dict[str, object] = {"repo": repo}
        if meta is None:
            entry["error"] = "repo-not-found-or-error"
        else:
            lic = meta.get("license") or {}
            entry.update(
                {
                    "license_spdx": lic.get("spdx_id"),
                    "stars": meta.get("stargazers_count"),
                    "pushed_at": meta.get("pushed_at"),
                    "archived": meta.get("archived"),
                    "description": meta.get("description"),
                }
            )
        if rel is None:
            entry["latest_release"] = None
        else:
            entry["latest_release"] = {
                "tag": rel.get("tag_name"),
                "published_at": rel.get("published_at"),
            }
        results[repo] = entry

    payload = {
        "fetched_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tool": "gh api (authenticated)",
        "repos": results,
    }
    out = Path("data/competitor-meta.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    for repo, entry in results.items():
        print(
            f"{repo} | {entry.get('license_spdx')} | {entry.get('stars')}"
            f" | {entry.get('pushed_at')} | {entry.get('latest_release')}"
        )


if __name__ == "__main__":
    main()