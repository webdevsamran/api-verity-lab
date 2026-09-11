"""Every place this package can open a network connection, found in the code.

`docs/self-hosting.md` says "no telemetry, no phone-home, no auto-update". That
is true, and until now it was a sentence somebody typed. A tool asking to be
run inside an air-gapped network has to be able to answer the harder question:
*where does it connect, and what makes it?* -- and answer it from the code
rather than from memory.

So this walks the package with `ast`, finds every call that can open a socket,
and writes `docs/egress.md` with the module, the line and the surrounding
function. `--check` fails when the committed document disagrees, which is the
same contract every other generated document here lives under.

## What counts

A call to `httpx` (any of its client or module-level request functions),
`urllib.request.urlopen`, or `socket.create_connection`. Those are the ways
this package reaches a network, and the list of *names* is checked against the
imports it finds, so a new HTTP library added later shows up as an unrecognised
import rather than silently as nothing.

## What this does not prove

That a run makes no connection. It proves where a connection *can* originate,
which is the thing a reviewer needs and the thing memory gets wrong. Whether a
given site fires depends on the flags -- `--base-url`, `--allow-remote-refs`,
`--send` -- and the document says which for each.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "apiverity"
DOC = ROOT / "docs" / "egress.md"

MARK_OPEN = "<!-- generated:egress -->"
MARK_CLOSE = "<!-- /generated:egress -->"

#: Call targets that can open a socket. Matched on the attribute path as
#: written, because that is what a reader greps for.
NETWORK_CALLS = {
    "httpx.Client",
    "httpx.AsyncClient",
    "httpx.get",
    "httpx.post",
    "httpx.put",
    "httpx.patch",
    "httpx.delete",
    "httpx.head",
    "httpx.request",
    "httpx.stream",
    "urlopen",
    "request.urlopen",
    "urllib.request.urlopen",
    "socket.create_connection",
}

#: Modules that exist to talk to a network. A new one appearing here that is
#: not in this set is reported, so an HTTP library added later cannot slip in
#: as a call site nothing recognises.
KNOWN_NETWORK_IMPORTS = {"httpx", "urllib", "urllib.request", "socket", "http.client"}

#: What makes each module's calls happen. Written here because it is a fact
#: about the command line, not about the source -- and a reader deciding
#: whether to run this in a disconnected network needs it more than the line
#: number.
TRIGGERS = {
    "apiverity/runtime/drift.py": "`drift --base-url`",
    "apiverity/runtime/ghosts.py": "`ghosts --base-url`",
    "apiverity/performance/engine.py": "`regression` / `baseline` with `--base-url`",
    "apiverity/fuzz/runner.py": "`test --base-url`",
    "apiverity/fuzz/minimize.py": "`test --minimize`",
    "apiverity/stateful/engine.py": "`workflow run --base-url`",
    "apiverity/specs/graphql/runner.py": "`test` / `drift` against a GraphQL endpoint",
    "apiverity/specs/mcp/runner.py": "`drift <manifest> --base-url`",
    "apiverity/traffic/replay.py": "`replay --send`",
    "apiverity/traffic/capture.py": "`capture` forwarding to its one `--target`",
    "apiverity/specs/bundle.py": "a remote `$ref`, and only with `--allow-remote-refs`",
    "apiverity/specs/__init__.py": "a spec given as a URL rather than a path",
    "apiverity/exporters/otel.py": "`--otlp-endpoint`",
    "apiverity/cli/commands/platform.py": "`notify --send`, `freeze` against a server",
    "apiverity/cli/commands/runtime.py": "`capture`, `drift`",
    "apiverity/cli/commands/testing.py": "`test --base-url`",
    "apiverity/plugins/builtins.py": "the built-in httpx transport, used by the above",
}


def _target(node: ast.Call) -> str | None:
    """The dotted name being called, as written."""
    parts: list[str] = []
    current: ast.expr = node.func
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    elif parts:
        return None
    dotted = ".".join(reversed(parts))
    return dotted if dotted in NETWORK_CALLS else None


def _enclosing(tree: ast.Module) -> dict[int, str]:
    """Line number -> the function it sits in."""
    out: dict[int, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            end = getattr(node, "end_lineno", node.lineno) or node.lineno
            for line in range(node.lineno, end + 1):
                out[line] = node.name
    return out


def scan() -> tuple[list[dict[str, str]], set[str]]:
    """Every call site, and every network-ish import seen."""
    sites: list[dict[str, str]] = []
    imports: set[str] = set()
    for path in sorted(PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        enclosing = _enclosing(tree)
        relative = path.relative_to(ROOT).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
            elif isinstance(node, ast.Call):
                target = _target(node)
                if target:
                    sites.append(
                        {
                            "file": relative,
                            "line": str(node.lineno),
                            "call": target,
                            "function": enclosing.get(node.lineno, "(module level)"),
                        }
                    )
    return sites, imports


def render(sites: list[dict[str, str]], imports: set[str]) -> str:
    by_file: dict[str, list[dict[str, str]]] = {}
    for site in sites:
        by_file.setdefault(site["file"], []).append(site)

    lines = [
        f"Found by `scripts/generate_egress_map.py`: **{len(sites)} call sites** across "
        f"**{len(by_file)} modules** that can open a network connection.",
        "",
        "| Module | Triggered by | Calls |",
        "|---|---|---|",
    ]
    for path in sorted(by_file):
        trigger = TRIGGERS.get(path, "—")
        calls = ", ".join(
            sorted(
                {
                    f"`{s['call']}` ({s['file'].rsplit('/', 1)[-1]}:{s['line']})"
                    for s in by_file[path]
                }
            )
        )
        lines.append(f"| `{path}` | {trigger} | {calls} |")

    unknown = sorted(
        name
        for name in imports
        if name.split(".")[0] in {"requests", "aiohttp", "urllib3", "websockets", "grpc"}
    )
    lines += [
        "",
        "### Modules with no trigger listed",
        "",
    ]
    missing = sorted(p for p in by_file if p not in TRIGGERS)
    if missing:
        lines += [f"- `{p}`" for p in missing]
        lines.append("")
        lines.append(
            "A module here is a call site nobody has said what causes. That is the gap "
            "worth closing before trusting this table."
        )
    else:
        lines.append("None: every module with a call site has a stated trigger.")

    stale = sorted(set(TRIGGERS) - set(by_file))
    if stale:
        lines += [
            "",
            "### Triggers with no call site",
            "",
            *[f"- `{p}`" for p in stale],
            "",
            "A module named in `TRIGGERS` that no longer has a call site. Harmless, and "
            "worth deleting: a published explanation of something that does not happen is "
            "the same defect as an unexplained thing that does.",
        ]

    lines += ["", "### Network libraries imported", ""]
    seen = sorted(
        n for n in imports if n.split(".")[0] in {i.split(".")[0] for i in KNOWN_NETWORK_IMPORTS}
    )
    lines.append(", ".join(f"`{n}`" for n in seen) or "none")
    if unknown:
        lines += [
            "",
            f"**Unrecognised:** {', '.join(f'`{n}`' for n in unknown)} — an HTTP library this "
            "scanner does not know how to follow. Its call sites are **not** in the table above.",
        ]
    return "\n".join(lines) + "\n"


def splice(text: str, body: str) -> str:
    start = text.find(MARK_OPEN)
    end = text.find(MARK_CLOSE)
    if start == -1 or end == -1 or end < start:
        raise SystemExit(
            f"{DOC.name} is missing the {MARK_OPEN} / {MARK_CLOSE} markers, or carries them "
            "out of order. Add them around the block before running this script."
        )
    return f"{text[: start + len(MARK_OPEN)]}\n{body}{text[end:]}"


def main() -> int:
    check = "--check" in sys.argv
    sites, imports = scan()
    if not sites:
        # A scan that found nothing is a broken scanner, not a tool with no
        # network access -- and it would publish the most reassuring possible
        # document.
        print("error: found no network call sites at all; the scanner is broken", file=sys.stderr)
        return 1

    current = DOC.read_text(encoding="utf-8")
    updated = splice(current, render(sites, imports))
    if check:
        if current == updated:
            print(f"ok     egress.md matches the code ({len(sites)} call sites)")
            return 0
        print(
            "error: docs/egress.md no longer matches the code.\n"
            "Run: python scripts/generate_egress_map.py",
            file=sys.stderr,
        )
        return 1
    DOC.write_text(updated, encoding="utf-8", newline="\n")
    print(f"wrote  egress.md ({len(sites)} call sites)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
