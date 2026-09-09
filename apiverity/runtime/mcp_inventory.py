"""Which MCP servers is this machine actually configured to talk to?

OWASP calls the gap MCP09, *Shadow MCP Servers*: an agent reaching a server
nobody approved. The obvious implementation is a port scan, and it is the wrong
one twice over. `SAFETY_MODEL.md` §1 is "explicit targets only" — a tool that
sweeps a network on request is a tool that sweeps a network — and a scan cannot
find the case that actually happens, which is a developer adding a server to
their own editor's config.

So this reads configuration instead of sending packets. Every MCP client keeps
a list of the servers it will start or connect to, in a JSON file. That list is
the ground truth about what an agent on this machine can reach, and comparing
it to an approved inventory is the whole check. Nothing here opens a socket.

What it will not claim
----------------------
The report names every path it looked at and whether the file was there, and
`servers_found: 0` is never rendered as "you have no MCP servers". A client
this build has not heard of, or one that moved its config, is a gap the reader
can see rather than a silence they cannot. `--config` takes any other path.

Home directories are read only with `--include-home`. A project checkout is
what a CI run is entitled to look at; a developer's home configuration is a
different thing to go reading, and it should take a flag.

Provenance of the paths below is recorded per entry: a first-party URL where
one exists, and "convention" where the location is widely used but was not
verified against a first-party document. Both are useful; pretending the second
is the first is not.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

#: Config keys that hold a server map. `mcpServers` is what Claude Desktop,
#: Claude Code and Cursor all write; `servers` is the other shape in use.
_SERVER_KEYS = ("mcpServers", "servers")


@dataclass(frozen=True)
class Candidate:
    """A place a client is known to keep its MCP configuration."""

    client: str
    #: Path relative to the project root, or to the home directory when `home`.
    path: str
    home: bool = False
    #: Where this location came from. A URL, or "convention".
    source: str = "convention"
    #: Only meaningful on `home` entries: the platform this path applies to.
    platforms: tuple[str, ...] = ()


#: Project-relative first: these live in the checkout, so a CI run can read
#: them without going anywhere near a developer's machine.
PROJECT_CANDIDATES: tuple[Candidate, ...] = (
    Candidate("Claude Code", ".mcp.json", source="convention"),
    Candidate(
        "Cursor",
        ".cursor/mcp.json",
        source="https://docs.cursor.com/ (project-scoped servers)",
    ),
    Candidate("VS Code", ".vscode/mcp.json", source="convention"),
)

HOME_CANDIDATES: tuple[Candidate, ...] = (
    Candidate(
        "Claude Desktop",
        "Library/Application Support/Claude/claude_desktop_config.json",
        home=True,
        source="https://modelcontextprotocol.io/docs/develop/connect-local-servers",
        platforms=("darwin",),
    ),
    Candidate(
        "Claude Desktop",
        "AppData/Roaming/Claude/claude_desktop_config.json",
        home=True,
        source="https://modelcontextprotocol.io/docs/develop/connect-local-servers",
        platforms=("win32",),
    ),
    Candidate(
        "Cursor",
        ".cursor/mcp.json",
        home=True,
        source="https://docs.cursor.com/ (global servers)",
    ),
    Candidate("Windsurf", ".codeium/windsurf/mcp_config.json", home=True),
    Candidate("Continue", ".continue/config.json", home=True),
)

#: Launchers that fetch the package at start time. What runs tomorrow is
#: whatever the registry serves tomorrow.
_FETCHING_LAUNCHERS = ("npx", "uvx", "pipx", "bunx", "pnpx", "dlx")

#: An env value that looks like a literal credential rather than a reference to
#: one. `${VAR}` and `$VAR` are references; a forty-character opaque string is
#: not. Deliberately conservative: the finding names the key, never the value.
_REFERENCE = re.compile(r"^\$\{?[A-Za-z_][A-Za-z0-9_]*\}?$")
_SECRETISH_KEY = re.compile(r"(?i)(token|secret|key|password|passwd|credential|auth)")


class ServerRecord(BaseModel):
    """One configured MCP server, as a client declared it."""

    name: str
    client: str
    config_path: str
    transport: str = "unknown"
    url: str | None = None
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    #: Names only. A value never reaches this record.
    env_keys: list[str] = Field(default_factory=list)


class InventoryFinding(BaseModel):
    rule_id: str
    severity: str = "WARN"
    message: str
    server: str | None = None
    config_path: str | None = None


class InventoryReport(BaseModel):
    root: str
    #: Every path considered, present or not. `servers_found: 0` must never be
    #: readable as "there are none".
    paths_examined: list[dict[str, Any]] = Field(default_factory=list)
    servers: list[ServerRecord] = Field(default_factory=list)
    approved: list[str] = Field(default_factory=list)
    findings: list[InventoryFinding] = Field(default_factory=list)
    home_included: bool = False


def _read_json(path: Path) -> tuple[dict[str, Any] | None, str]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        return None, f"unreadable: {exc.strerror or exc}"
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, f"not valid JSON ({exc.msg} at line {exc.lineno})"
    if not isinstance(parsed, dict):
        return None, "top level is not an object"
    return parsed, "read"


def _transport(entry: dict[str, Any]) -> str:
    if entry.get("url"):
        return "http"
    if entry.get("command"):
        return "stdio"
    declared = entry.get("type")
    return str(declared) if isinstance(declared, str) else "unknown"


def _records(document: dict[str, Any], client: str, path: str) -> list[ServerRecord]:
    records: list[ServerRecord] = []
    for key in _SERVER_KEYS:
        section = document.get(key)
        if not isinstance(section, dict):
            continue
        for name, entry in section.items():
            if not isinstance(entry, dict):
                continue
            args = entry.get("args")
            env = entry.get("env")
            records.append(
                ServerRecord(
                    name=str(name),
                    client=client,
                    config_path=path,
                    transport=_transport(entry),
                    url=str(entry["url"]) if isinstance(entry.get("url"), str) else None,
                    command=(
                        str(entry["command"]) if isinstance(entry.get("command"), str) else None
                    ),
                    args=[str(a) for a in args] if isinstance(args, list) else [],
                    # Keys only. The values are credentials often enough that
                    # reading them into a model that gets serialised into an
                    # artifact is not a risk worth taking for a nicer report.
                    env_keys=sorted(str(k) for k in env) if isinstance(env, dict) else [],
                )
            )
    return records


def load_approved(path: str | Path) -> tuple[list[str], list[InventoryFinding]]:
    """Approved server names from an inventory file (YAML or JSON)."""
    import yaml

    source = Path(path)
    try:
        raw = yaml.safe_load(source.read_text(encoding="utf-8-sig")) or {}
    except (OSError, yaml.YAMLError) as exc:
        return [], [
            InventoryFinding(
                rule_id="MCP-INVENTORY-UNREADABLE",
                severity="ERROR",
                message=f"{source}: could not be read ({exc})",
                config_path=str(source),
            )
        ]
    servers = raw.get("servers") if isinstance(raw, dict) else None
    if not isinstance(servers, list):
        return [], [
            InventoryFinding(
                rule_id="MCP-INVENTORY-UNREADABLE",
                severity="ERROR",
                message=f"{source}: an inventory is a mapping with a `servers` list",
                config_path=str(source),
            )
        ]
    names: list[str] = []
    for entry in servers:
        if isinstance(entry, str):
            names.append(entry)
        elif isinstance(entry, dict) and isinstance(entry.get("name"), str):
            names.append(entry["name"])
    return sorted(set(names)), []


def _hygiene(record: ServerRecord) -> list[InventoryFinding]:
    findings: list[InventoryFinding] = []

    launcher = (record.command or "").rsplit("/", 1)[-1].rsplit("\\", 1)[-1].removesuffix(".exe")
    if launcher in _FETCHING_LAUNCHERS:
        package = next((a for a in record.args if not a.startswith("-")), "<unnamed>")
        findings.append(
            InventoryFinding(
                rule_id="MCP-SHADOW-FETCHED-AT-LAUNCH",
                severity="WARN",
                server=record.name,
                config_path=record.config_path,
                message=(
                    f"{record.name!r} runs `{launcher} {package}`, so the code that starts is "
                    "whatever the registry serves at launch. Pin a version, or vendor it: this "
                    "is a dependency with no lockfile in front of it"
                ),
            )
        )

    if record.url and record.url.startswith("http://"):
        host = record.url.split("//", 1)[-1].split("/", 1)[0].split(":", 1)[0]
        if host not in {"localhost", "127.0.0.1", "::1"} and not host.endswith(".local"):
            findings.append(
                InventoryFinding(
                    rule_id="MCP-SHADOW-PLAINTEXT-URL",
                    severity="WARN",
                    server=record.name,
                    config_path=record.config_path,
                    message=(
                        f"{record.name!r} is configured over plain HTTP to {host}; every tool "
                        "schema and every credential sent to it crosses the network in the clear"
                    ),
                )
            )
    return findings


def _inline_secrets(entry: dict[str, Any], record: ServerRecord) -> list[InventoryFinding]:
    """Env values that are the credential rather than a pointer to one."""
    env = entry.get("env")
    if not isinstance(env, dict):
        return []
    literal = sorted(
        str(key)
        for key, value in env.items()
        if _SECRETISH_KEY.search(str(key))
        and isinstance(value, str)
        and value
        and not _REFERENCE.match(value)
    )
    if not literal:
        return []
    return [
        InventoryFinding(
            rule_id="MCP-SHADOW-INLINE-CREDENTIAL",
            severity="ERROR",
            server=record.name,
            config_path=record.config_path,
            message=(
                f"{record.name!r} carries a literal value for {', '.join(literal)} in its client "
                "configuration. That file is on disk, is often committed, and is read by every "
                "process running as this user. Use an environment reference such as ${NAME}"
            ),
        )
    ]


@dataclass
class _Scan:
    records: list[ServerRecord] = field(default_factory=list)
    findings: list[InventoryFinding] = field(default_factory=list)
    examined: list[dict[str, Any]] = field(default_factory=list)


def _examine(candidate: Candidate, path: Path, scan: _Scan) -> None:
    entry: dict[str, Any] = {
        "client": candidate.client,
        "path": str(path),
        "source": candidate.source,
        "status": "absent",
        "servers": 0,
    }
    if not path.is_file():
        scan.examined.append(entry)
        return

    document, status = _read_json(path)
    entry["status"] = status
    if document is None:
        scan.findings.append(
            InventoryFinding(
                rule_id="MCP-INVENTORY-CONFIG-UNREADABLE",
                severity="WARN",
                config_path=str(path),
                message=(
                    f"{path} exists and {status}; the servers it configures were not read, so "
                    "this report does not cover them"
                ),
            )
        )
        scan.examined.append(entry)
        return

    records = _records(document, candidate.client, str(path))
    entry["servers"] = len(records)
    scan.examined.append(entry)

    sections = [document.get(key) for key in _SERVER_KEYS]
    raw_entries: dict[str, Any] = {}
    for section in sections:
        if isinstance(section, dict):
            raw_entries.update(section)

    for record in records:
        scan.records.append(record)
        scan.findings.extend(_hygiene(record))
        raw = raw_entries.get(record.name)
        if isinstance(raw, dict):
            scan.findings.extend(_inline_secrets(raw, record))


def take_inventory(
    root: str | Path = ".",
    *,
    extra_configs: list[str] | None = None,
    approved_path: str | None = None,
    include_home: bool = False,
    home: Path | None = None,
    platform: str | None = None,
) -> InventoryReport:
    """Read client configurations and compare them to an approved inventory."""
    base = Path(root).resolve()
    scan = _Scan()

    for candidate in PROJECT_CANDIDATES:
        _examine(candidate, base / candidate.path, scan)

    if include_home:
        home_dir = home or Path.home()
        current = platform or sys.platform
        for candidate in HOME_CANDIDATES:
            if candidate.platforms and current not in candidate.platforms:
                continue
            _examine(candidate, home_dir / candidate.path, scan)

    for extra in extra_configs or []:
        _examine(
            Candidate("--config", extra, source="named on the command line"), Path(extra), scan
        )

    approved: list[str] = []
    if approved_path:
        approved, problems = load_approved(approved_path)
        scan.findings.extend(problems)

        configured = {record.name for record in scan.records}
        for record in scan.records:
            if record.name not in approved:
                scan.findings.append(
                    InventoryFinding(
                        rule_id="MCP-SHADOW-SERVER",
                        severity="ERROR",
                        server=record.name,
                        config_path=record.config_path,
                        message=(
                            f"{record.name!r} is configured in {record.client} but is not in the "
                            f"approved inventory. An agent on this machine can reach it and "
                            "nobody signed off on what it can do"
                        ),
                    )
                )
        for name in approved:
            if name not in configured:
                scan.findings.append(
                    InventoryFinding(
                        rule_id="MCP-INVENTORY-UNCONFIGURED",
                        severity="INFO",
                        server=name,
                        message=(
                            f"{name!r} is approved and was not found in any configuration this "
                            "run read. That may mean it is unused, or that its client keeps its "
                            "config somewhere this build does not know about"
                        ),
                    )
                )

    return InventoryReport(
        root=str(base),
        paths_examined=scan.examined,
        servers=sorted(scan.records, key=lambda r: (r.name, r.config_path)),
        approved=approved,
        findings=scan.findings,
        home_included=include_home,
    )


def coverage_note(report: InventoryReport) -> str:
    """One sentence a reader needs before believing a count of zero."""
    present = sum(1 for entry in report.paths_examined if entry["status"] == "read")
    total = len(report.paths_examined)
    scope = "project and home" if report.home_included else "project only"
    return (
        f"{len(report.servers)} server(s) across {present} of {total} known configuration "
        f"locations ({scope}). A client that keeps its configuration elsewhere was not read; "
        "pass --config to name it."
    )


__all__ = [
    "HOME_CANDIDATES",
    "PROJECT_CANDIDATES",
    "Candidate",
    "InventoryFinding",
    "InventoryReport",
    "ServerRecord",
    "coverage_note",
    "load_approved",
    "take_inventory",
]
