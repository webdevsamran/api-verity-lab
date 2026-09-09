"""Project setup: `init` and `config validate`.

`init` exists because the distance between cloning a repo and having a passing
contract check was: read the README, learn the command names, learn the
directory conventions, write a workflow. Every step of that is a place to stop.

It is deliberately not interactive. A wizard that asks questions cannot run in
CI, cannot be scripted, and cannot be re-run to check its own output. This
detects what is actually in the repository, writes a config describing what it
found, and prints what it did — so the same command works on a laptop and in a
container, and running it twice is safe.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import yaml

from apiverity.cli.commands.common import EXIT_FINDINGS, EXIT_OK, EXIT_USAGE, _emit
from apiverity.core.config import (
    CONFIG_SCHEMA_VERSION,
    DEFAULT_CONFIG_NAME,
    Config,
    ConfigError,
    find_config,
    load_config,
)

#: Where contracts usually live. Ordered, because the first match names the
#: project's convention and the rest would only add noise.
_CANDIDATE_DIRS = ("api", "apis", "openapi", "specs", "contracts", "schemas", "fixtures/apis")

_SPEC_SUFFIXES = (".yaml", ".yml", ".json")

#: Directories never worth walking. A node_modules scan on a large repo takes
#: long enough that `init` would look hung.
_SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    "dist",
    "build",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "site-packages",
}


#: A spec declares its version as the *value* of a top-level key.
#:
#: Matching the bare word instead was a false positive with teeth: run against
#: this repository, `init` proposed `schemas/**` because
#: `schemas/result-v1.schema.json` contains the string "openapi" inside an enum
#: of protocol names. A JSON Schema that mentions OpenAPI is not an OpenAPI
#: document, and a config listing the wrong files is worse than one listing
#: none -- it looks configured.
_VERSION_DECLARATION = re.compile(
    r"""^\s*['"]?(openapi|swagger|asyncapi)['"]?\s*:\s*['"]?\d""",
    re.MULTILINE,
)


def _looks_like_contract(path: Path) -> bool:
    """Cheap sniff, without loading. `init` must not be slow on a big repo."""
    try:
        head = path.read_text(encoding="utf-8-sig", errors="replace")[:4096]
    except OSError:
        return False
    return _VERSION_DECLARATION.search(head) is not None


def discover_contracts(root: Path, *, limit: int = 200) -> list[str]:
    """Contract-looking files under `root`, as repo-relative posix paths."""
    found: list[str] = []
    for directory in _CANDIDATE_DIRS:
        base = root / directory
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if len(found) >= limit:
                return found
            if not path.is_file() or path.suffix.lower() not in _SPEC_SUFFIXES:
                continue
            if _SKIP_DIRS & set(path.parts):
                continue
            if _looks_like_contract(path):
                found.append(path.relative_to(root).as_posix())
        if found:
            # The first directory that yielded anything is the project's
            # convention; walking the rest would add files nobody groups
            # together.
            break
    return found


def _globs_for(paths: list[str]) -> list[str]:
    """Collapse discovered files into the patterns a human would have written."""
    directories = sorted({str(Path(p).parent).replace("\\", "/") for p in paths})
    return [f"{d}/**/*.{{yaml,yml,json}}" if d != "." else "*.{yaml,yml,json}" for d in directories]


def cmd_init(args: argparse.Namespace) -> int:
    """Detect contracts, write a config, and say what happens next."""
    root = Path(getattr(args, "directory", ".")).resolve()
    if not root.is_dir():
        print(f"error: not a directory: {root}", file=sys.stderr)
        return EXIT_USAGE

    target = root / DEFAULT_CONFIG_NAME
    if target.exists() and not getattr(args, "force", False):
        print(
            f"error: {DEFAULT_CONFIG_NAME} already exists; pass --force to overwrite",
            file=sys.stderr,
        )
        return EXIT_USAGE

    contracts = discover_contracts(root)
    config = Config(
        version=CONFIG_SCHEMA_VERSION,
        contracts=_globs_for(contracts) if contracts else [],
        # `never` on a fresh project, deliberately. A gate that starts failing
        # on the first run against an API with history gets removed rather than
        # adopted; this reports everything and blocks nothing until someone
        # decides otherwise.
        fail_on="never",
        check_semver=True,
    )

    body = yaml.safe_dump(config.as_dict(), sort_keys=False)
    header = (
        "# apiverity project configuration.\n"
        "#\n"
        "# Schema: schemas/config-v1.schema.json (run `apiverity config validate`).\n"
        "# Written by `apiverity init`; safe to edit by hand.\n"
        "#\n"
        "# fail_on starts at 'never' on purpose: a gate that fails on its first\n"
        "# run against an API that already has history gets removed rather than\n"
        "# adopted. Read a few reports, then switch it to 'error'.\n"
    )
    if not getattr(args, "dry_run", False):
        target.write_text(header + body, encoding="utf-8")

    next_steps = [
        f"apiverity validate {contracts[0]}" if contracts else "apiverity validate <your-spec>",
        "apiverity breaking <old> <new> --check-semver --suggest-version",
        "add webdevsamran/api-verity-lab@v1 to a workflow (see docs/ci.md)",
    ]
    _emit(
        {
            "tool": "apiverity",
            "command": "init",
            "config_path": str(target),
            "written": not getattr(args, "dry_run", False),
            "contracts_found": len(contracts),
            "contracts": contracts[:20],
            "patterns": config.contracts,
            "next_steps": next_steps,
        },
        getattr(args, "json", False),
    )
    if not getattr(args, "json", False):
        print()
        if contracts:
            print(f"Found {len(contracts)} contract(s). Next:")
        else:
            print("No contracts found in the usual places. Once you have one:")
        for step in next_steps:
            print(f"  {step}")
    return EXIT_OK


def cmd_config(args: argparse.Namespace) -> int:
    """Validate a project config, or print the resolved one."""
    action = getattr(args, "action", "validate")

    path = Path(args.path) if getattr(args, "path", None) else find_config()
    if path is None:
        print(
            f"error: no {DEFAULT_CONFIG_NAME} found here or in any parent; "
            "run `apiverity init` to create one",
            file=sys.stderr,
        )
        return EXIT_USAGE

    try:
        config, findings = load_config(path)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    payload: dict[str, Any] = {
        "tool": "apiverity",
        "command": "config",
        "action": action,
        "path": str(path),
        "findings": [f.model_dump(mode="json") for f in findings],
    }
    if action == "show":
        payload["config"] = config.as_dict()

    _emit(payload, getattr(args, "json", False))
    errors = [f for f in findings if f.severity.value == "ERROR"]
    return EXIT_FINDINGS if errors else EXIT_OK


__all__ = ["cmd_config", "cmd_init", "discover_contracts"]
