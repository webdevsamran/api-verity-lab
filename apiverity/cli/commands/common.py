"""Shared CLI plumbing: stable exit codes, spec loading, result emission."""

from __future__ import annotations

import argparse
import json
import sys
from typing import TYPE_CHECKING, Any

NL = chr(10)

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_USAGE = 2
EXIT_UNREACHABLE = 3
EXIT_INTERNAL = 4

if TYPE_CHECKING:
    from apiverity.core.model import Finding, Service
    from apiverity.specs import SpecPlugin

_LAST_SPEC: str | None = None
_LAST_TARGET: str | None = None
_LAST_SEED: int | None = None


def set_last_target(target: str | None) -> None:
    """Record the most recent base URL for artifact enrichment."""
    global _LAST_TARGET
    _LAST_TARGET = target


def set_last_seed(seed: int | None) -> None:
    """Record the most recent generation seed for artifact enrichment."""
    global _LAST_SEED
    _LAST_SEED = seed


def _load(path: str) -> tuple[Service, list[Finding], SpecPlugin]:
    from apiverity.specs.loader import detect_and_load

    global _LAST_SPEC
    _LAST_SPEC = path
    try:
        return detect_and_load(path)
    except FileNotFoundError:
        print(f"error: file not found: {path}", file=sys.stderr)
        sys.exit(EXIT_USAGE)
    except Exception as exc:
        print(f"error: failed to load spec: {exc}", file=sys.stderr)
        sys.exit(EXIT_USAGE)


def _pair(args: argparse.Namespace) -> tuple[Service, Service]:
    old_service, _, _ = _load(args.old)
    new_service, _, _ = _load(args.new)
    return old_service, new_service


def _emit(data: dict[str, Any], as_json: bool) -> None:
    from apiverity.core.artifact import enrich

    data = enrich(data, spec_path=_LAST_SPEC, target=_LAST_TARGET, seed=_LAST_SEED)
    if as_json:
        print(json.dumps(data, indent=2, default=str))
    else:
        for key, value in data.items():
            if isinstance(value, list) and value and hasattr(value[0], "model_dump"):
                print(f"{key}:")
                for item in value:
                    d = item.model_dump()
                    print(
                        f"  [{d.get('severity', d.get('status', ''))}] "
                        f"{d.get('rule_id', d.get('case_id', d.get('step', '')))} "
                        f"{d.get('message', d.get('description', ''))}"
                    )
            else:
                print(f"{key}: {value}")
