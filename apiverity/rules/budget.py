"""Call budgets: how much an agent is allowed to use an interface.

The single most-cited worry about agent traffic is not that an agent calls the
wrong endpoint — it is that it calls the right one ten thousand times. That is
a contract-level fact nobody writes down anywhere: a rate limit lives in a
gateway config, if it exists, and the contract an agent was generated from says
nothing about how often any of it may be called.

A budget file is that missing declaration, and this checks observed traffic
against it.

Sliding windows, not buckets
----------------------------
"No more than 100 calls an hour" means no hour contains 101 calls, not that no
clock hour does. Tumbling buckets miss a burst that straddles a boundary, which
is precisely the shape a runaway agent produces, so the check finds the busiest
window of the declared length by scanning sorted timestamps. That is only
possible because `import_har` now carries `startedDateTime` through; an entry
without a timestamp cannot be placed in any window and is counted and reported
rather than silently folded into a total.

The finding that matters most is the one about the budget
---------------------------------------------------------
`BUDGET-OPERATION-UNKNOWN` fires when a limit names an operation the contract
does not declare — a typo in an operation key, a path that was renamed. Such a
limit can never match anything, so the file looks like protection and is not,
and the run it is supposed to constrain passes cleanly. Same reasoning as
`CONFIG-RULE-UNKNOWN` in the project config: a setting nobody reads is worse
than a setting nobody wrote.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from apiverity.core.model import Finding, Severity

#: `30s`, `15m`, `2h`, `1d`. Deliberately small: a budget window measured in
#: weeks is a quota, and a quota needs storage this command does not have.
_WINDOW = re.compile(r"^\s*(\d+)\s*([smhd])\s*$")
_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}

DEFAULT_WINDOW = "1h"


class BudgetError(ValueError):
    """The budget file could not be used as written."""


def parse_window(text: str) -> timedelta:
    match = _WINDOW.match(text)
    if match is None:
        raise BudgetError(
            f"window {text!r} is not understood; use a number and one of s, m, h, d (e.g. '15m')"
        )
    return timedelta(seconds=int(match.group(1)) * _UNITS[match.group(2)])


@dataclass(frozen=True)
class Limit:
    """One operation's allowance."""

    operation_key: str
    max_calls: int
    window: str

    @property
    def forbidden(self) -> bool:
        return self.max_calls == 0


@dataclass
class Budget:
    version: int = 1
    window: str = DEFAULT_WINDOW
    #: When true, a call to an operation with no limit is an error rather than
    #: a note. Off by default: a first budget covers the dangerous operations
    #: and nothing else, and failing on the rest would get it deleted.
    deny_by_default: bool = False
    limits: list[Limit] = field(default_factory=list)
    source: str = ""

    def for_operation(self, key: str) -> Limit | None:
        return next((limit for limit in self.limits if limit.operation_key == key), None)


def _operation_key(entry: dict[str, Any]) -> str:
    """The key a limit is written against.

    `tool: search_orders` is sugar for the key an MCP manifest produces, so a
    budget reads the way the manifest does and matches the way every other
    report in this project keys an operation.
    """
    if isinstance(entry.get("tool"), str):
        return f"tool {entry['tool']}"
    operation = entry.get("operation")
    if isinstance(operation, str):
        return operation
    raise BudgetError("each limit needs either `operation` or `tool`")


def load_budget(path: str | Path) -> Budget:
    """Parse a budget file (YAML or JSON)."""
    import yaml

    source = Path(path)
    try:
        raw = yaml.safe_load(source.read_text(encoding="utf-8-sig")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise BudgetError(f"{source}: {exc}") from exc
    if not isinstance(raw, dict):
        raise BudgetError(f"{source}: a budget file is a mapping at the top level")

    version = raw.get("version")
    if version != 1:
        raise BudgetError(
            f"{source}: budget version {version!r} is not supported; this build understands 1"
        )

    default_window = str(raw.get("window") or DEFAULT_WINDOW)
    parse_window(default_window)

    entries = raw.get("limits")
    if not isinstance(entries, list):
        raise BudgetError(f"{source}: `limits` must be a list")

    limits: list[Limit] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise BudgetError(f"{source}: each limit is a mapping")
        key = _operation_key(entry)
        raw_max = entry.get("max_calls")
        if not isinstance(raw_max, int) or isinstance(raw_max, bool) or raw_max < 0:
            raise BudgetError(f"{source}: `max_calls` for {key!r} must be a non-negative integer")
        window = str(entry.get("window") or default_window)
        parse_window(window)
        limits.append(Limit(operation_key=key, max_calls=raw_max, window=window))

    return Budget(
        version=1,
        window=default_window,
        deny_by_default=bool(raw.get("deny_by_default", False)),
        limits=limits,
        source=str(source),
    )


def _parse_instant(text: str) -> datetime | None:
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def busiest_window(instants: list[datetime], window: timedelta) -> tuple[int, datetime | None]:
    """The most calls in any window of that length, and where it started.

    Two pointers over a sorted list. A tumbling bucket would miss a burst that
    straddles a boundary, which is exactly the shape a runaway agent makes.
    """
    if not instants:
        return 0, None
    ordered = sorted(instants)
    best, best_at = 0, ordered[0]
    start = 0
    for end, moment in enumerate(ordered):
        while moment - ordered[start] > window:
            start += 1
        size = end - start + 1
        if size > best:
            best, best_at = size, ordered[start]
    return best, best_at


@dataclass
class Observation:
    """Calls seen for one operation."""

    total: int = 0
    instants: list[datetime] = field(default_factory=list)
    undated: int = 0


def observe(calls: list[dict[str, Any]]) -> dict[str, Observation]:
    """Group calls by operation key, keeping their instants."""
    seen: dict[str, Observation] = {}
    for call in calls:
        key = str(call.get("operation_key") or "")
        if not key:
            continue
        record = seen.setdefault(key, Observation())
        record.total += 1
        raw = call.get("at")
        instant = _parse_instant(raw) if isinstance(raw, str) and raw else None
        if instant is None:
            record.undated += 1
        else:
            record.instants.append(instant)
    return seen


def evaluate(
    budget: Budget,
    calls: list[dict[str, Any]],
    *,
    declared_operations: set[str] | None = None,
) -> list[Finding]:
    """Observed calls against a budget."""
    findings: list[Finding] = []
    observations = observe(calls)

    if declared_operations is not None:
        for limit in budget.limits:
            if limit.operation_key not in declared_operations:
                findings.append(
                    Finding(
                        rule_id="BUDGET-OPERATION-UNKNOWN",
                        severity=Severity.ERROR,
                        operation_key=limit.operation_key,
                        message=(
                            f"the budget limits {limit.operation_key!r}, which the contract does "
                            "not declare. This limit can never match anything, so the file looks "
                            "like protection and is not"
                        ),
                    )
                )

    for limit in budget.limits:
        record = observations.get(limit.operation_key)
        if record is None or record.total == 0:
            findings.append(
                Finding(
                    rule_id="BUDGET-UNUSED",
                    severity=Severity.INFO,
                    operation_key=limit.operation_key,
                    message=(
                        f"nothing in this traffic called {limit.operation_key!r}; its limit was "
                        "not exercised, so this run says nothing about whether it holds"
                    ),
                )
            )
            continue

        if limit.forbidden:
            findings.append(
                Finding(
                    rule_id="BUDGET-FORBIDDEN",
                    severity=Severity.ERROR,
                    operation_key=limit.operation_key,
                    message=(
                        f"{limit.operation_key!r} is budgeted at zero calls and was called "
                        f"{record.total} time(s)"
                    ),
                )
            )
            continue

        window = parse_window(limit.window)
        peak, at = busiest_window(record.instants, window)
        if peak > limit.max_calls:
            findings.append(
                Finding(
                    rule_id="BUDGET-EXCEEDED",
                    severity=Severity.ERROR,
                    operation_key=limit.operation_key,
                    message=(
                        f"{limit.operation_key!r} allows {limit.max_calls} call(s) per "
                        f"{limit.window} and reached {peak} in the window beginning "
                        f"{at.isoformat() if at else 'unknown'}"
                    ),
                )
            )
        if record.undated:
            findings.append(
                Finding(
                    rule_id="BUDGET-UNDATED-CALLS",
                    severity=Severity.WARN,
                    operation_key=limit.operation_key,
                    message=(
                        f"{record.undated} of {record.total} call(s) to "
                        f"{limit.operation_key!r} carry no timestamp and could not be placed in "
                        "any window; the peak above is a lower bound"
                    ),
                )
            )

    budgeted = {limit.operation_key for limit in budget.limits}
    for key, record in sorted(observations.items()):
        if key in budgeted:
            continue
        findings.append(
            Finding(
                rule_id="BUDGET-UNBUDGETED",
                severity=Severity.ERROR if budget.deny_by_default else Severity.INFO,
                operation_key=key,
                message=(
                    f"{key!r} was called {record.total} time(s) and no limit covers it"
                    + (
                        "; this budget denies by default"
                        if budget.deny_by_default
                        else ". Add a limit if that traffic is meant to be bounded"
                    )
                ),
            )
        )
    return findings


__all__ = [
    "DEFAULT_WINDOW",
    "Budget",
    "BudgetError",
    "Limit",
    "Observation",
    "busiest_window",
    "evaluate",
    "load_budget",
    "observe",
    "parse_window",
]
