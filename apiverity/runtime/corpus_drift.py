"""Drift detection against a recorded traffic corpus (#21).

`detect_drift` probes a live service with one synthetic request per operation.
That answers "does this endpoint match its contract right now", which is
useful but narrow: one request cannot distinguish a header the service never
sends from one it dropped once, and a synthetic request only ever exercises
the shape the generator happens to produce.

A corpus answers a different question -- "how often does reality disagree with
this contract, across everything real clients actually did" -- and the answer
is only useful if it is aggregated. A thousand HAR entries against a service
missing one declared header produce a thousand identical findings; printed one
per line that is not a report, it is a wall, and the one finding that appeared
twice out of a thousand is invisible in it.

So findings are grouped, counted, and given a frequency, and the frequency is
what separates "this contract is wrong" from "something hiccupped once".
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, Field

from apiverity.core.model import Operation, Response, Service
from apiverity.core.validation import validate_value

__all__ = [
    "AggregatedFinding",
    "CorpusDriftReport",
    "CorpusQuality",
    "analyze_corpus",
    "match_operation",
]

#: At or above this share of observations, a finding is the service's normal
#: behaviour rather than an incident. The exact number is a judgement call, but
#: the distinction is not: "the contract is wrong" and "something failed once"
#: need different responses from whoever reads the report.
SYSTEMATIC_THRESHOLD = 0.9

#: Below this, a finding is rare enough to be worth calling out as such rather
#: than mixed in with the rest.
ONE_OFF_THRESHOLD = 0.1


class AggregatedFinding(BaseModel):
    """One kind of drift, with how often it happened."""

    operation_key: str
    rule_id: str
    severity: str = "WARN"
    message: str
    #: Entries in which this finding occurred.
    occurrences: int = 0
    #: Entries matched to this operation that could have produced it.
    observations: int = 0
    #: Example request URLs, capped -- enough to reproduce, not a second copy
    #: of the corpus.
    examples: list[str] = Field(default_factory=list)

    @property
    def frequency(self) -> float:
        return self.occurrences / self.observations if self.observations else 0.0

    @property
    def systematic(self) -> bool:
        """Whether this is how the service always behaves.

        A declared header missing from every response is a contract that is
        simply wrong. The same header missing from 2% of responses is a
        different bug with a different owner, and conflating them costs
        someone an afternoon.
        """
        return self.observations > 0 and self.frequency >= SYSTEMATIC_THRESHOLD

    @property
    def one_off(self) -> bool:
        return self.observations > 0 and self.frequency <= ONE_OFF_THRESHOLD


class CorpusQuality(BaseModel):
    """What the corpus could not tell us, and why.

    Without this a report is unreadable: "3 findings" from a 5000-entry corpus
    means something very different when 4900 entries were skipped, and a
    reader who is not told cannot tell the two apart. Every count here is a
    reason some part of the corpus did not contribute.
    """

    entries: int = 0
    analysed: int = 0
    skipped_malformed: int = 0
    skipped_unmatched: int = 0
    #: Matched, but the response body was absent -- usually redaction, which
    #: is the default for a corpus that gets committed.
    bodies_unavailable: int = 0
    #: Paths present in the corpus that no operation in the contract matches.
    unmatched_paths: list[str] = Field(default_factory=list)
    #: Reasons bodies were dropped, counted.
    body_drop_reasons: dict[str, int] = Field(default_factory=dict)
    #: Operations in the contract that the corpus never exercised. Not drift,
    #: but the reason a clean report may mean untested rather than correct.
    uncovered_operations: list[str] = Field(default_factory=list)

    @property
    def coverage(self) -> float:
        return self.analysed / self.entries if self.entries else 0.0


class CorpusDriftReport(BaseModel):
    source: str = ""
    findings: list[AggregatedFinding] = Field(default_factory=list)
    quality: CorpusQuality = Field(default_factory=CorpusQuality)

    def systematic(self) -> list[AggregatedFinding]:
        return [f for f in self.findings if f.systematic]

    def one_offs(self) -> list[AggregatedFinding]:
        return [f for f in self.findings if f.one_off]


# --------------------------------------------------------------- route matching


def match_operation(service: Service, method: str, path: str) -> Operation | None:
    """Match a concrete request path to a templated contract path.

    A corpus records `/users/42`; the contract declares `/users/{id}`. Exact
    matches win over templated ones, because a contract with both `/users/me`
    and `/users/{id}` means the literal, and picking the template would report
    drift against the wrong operation.
    """
    if not method:
        return None
    method = method.upper()
    parts = [p for p in path.split("/") if p]

    for op in service.operations:
        if op.method and op.method.upper() == method and op.path == path:
            return op

    best: Operation | None = None
    best_literals = -1
    for op in service.operations:
        if not op.path or not op.method or op.method.upper() != method:
            continue
        template = [p for p in op.path.split("/") if p]
        if len(template) != len(parts):
            continue
        literals = 0
        for expected, actual in zip(template, parts, strict=True):
            if expected.startswith("{") and expected.endswith("}"):
                continue
            if expected != actual:
                break
            literals += 1
        else:
            # More literal segments means a more specific template, so
            # `/users/me/posts` beats `/users/{id}/posts`.
            if literals > best_literals:
                best, best_literals = op, literals
    return best


def _select_response(op: Operation, status: int) -> Response | None:
    """The declared response for a status, honouring wildcard declarations.

    OpenAPI allows `4XX` and `default`; matching only exact strings reported
    every 404 in a corpus as an undeclared status against a contract that
    declared `4XX` perfectly well.
    """
    status_text = str(status)
    for response in op.responses:
        if response.status == status_text:
            return response
    wildcard = f"{status_text[0]}XX"
    for response in op.responses:
        if response.status.upper() == wildcard:
            return response
    for response in op.responses:
        if response.status.lower() == "default":
            return response
    return None


def _select_schema(declared: Response, mime: str) -> tuple[Any, str | None]:
    """Pick the schema for the media type actually returned.

    Content negotiation is the point: a service that declares both
    `application/json` and `text/csv` and returns CSV was previously validated
    against whichever schema `content` happened to yield first, so a correct
    CSV response was reported as a schema violation. The returned type is
    matched first, then its base type (`application/vnd.api+json` falls back
    to a JSON schema), and only then is it reported as undeclared.
    """
    if not declared.content:
        return None, None
    base = (mime or "").split(";")[0].strip().lower()
    if not base:
        return None, "response declared no content type"
    for name, schema in declared.content.items():
        if name.lower() == base:
            return schema, None
    if base.endswith("+json") or base == "application/json":
        for name, schema in declared.content.items():
            if name.lower().endswith("json"):
                return schema, None
    for name, schema in declared.content.items():
        if name.strip().endswith("/*") and base.startswith(name.split("/")[0].lower()):
            return schema, None
    return None, f"content type '{base}' is not declared (declared: {sorted(declared.content)})"


# ------------------------------------------------------------------- analysis


class _Accumulator:
    """Groups identical findings while counting them.

    The key deliberately excludes anything entry-specific -- the URL, the
    concrete value -- so a thousand entries missing the same header become one
    finding with a count of a thousand, not a thousand findings.
    """

    def __init__(self, example_limit: int = 3) -> None:
        self._findings: dict[tuple[str, str, str], AggregatedFinding] = {}
        self._observations: dict[str, int] = {}
        self._example_limit = example_limit

    def observe(self, operation_key: str) -> None:
        self._observations[operation_key] = self._observations.get(operation_key, 0) + 1

    def add(
        self,
        operation_key: str,
        rule_id: str,
        message: str,
        *,
        severity: str = "WARN",
        example: str = "",
    ) -> None:
        key = (operation_key, rule_id, message)
        finding = self._findings.get(key)
        if finding is None:
            finding = AggregatedFinding(
                operation_key=operation_key,
                rule_id=rule_id,
                severity=severity,
                message=message,
            )
            self._findings[key] = finding
        finding.occurrences += 1
        if example and len(finding.examples) < self._example_limit:
            finding.examples.append(example)

    def finish(self) -> list[AggregatedFinding]:
        for finding in self._findings.values():
            finding.observations = self._observations.get(finding.operation_key, 0)
        return sorted(
            self._findings.values(),
            key=lambda f: (-f.occurrences, f.operation_key, f.rule_id, f.message),
        )


def analyze_corpus(
    service: Service,
    entries: list[dict[str, Any]],
    *,
    source: str = "",
    forbid_undeclared_fields: bool = True,
) -> CorpusDriftReport:
    """Compare a sanitized traffic corpus against the declared contract."""
    quality = CorpusQuality(entries=len(entries))
    accumulator = _Accumulator()
    unmatched: dict[str, int] = {}
    exercised: set[str] = set()

    for entry in entries:
        method = str(entry.get("method") or "")
        url = str(entry.get("url") or "")
        status = entry.get("status")
        if not method or not url or not isinstance(status, int):
            quality.skipped_malformed += 1
            continue

        path = urlsplit(url).path or "/"
        op = match_operation(service, method, path)
        if op is None:
            quality.skipped_unmatched += 1
            label = f"{method.upper()} {path}"
            unmatched[label] = unmatched.get(label, 0) + 1
            continue

        quality.analysed += 1
        exercised.add(op.key)
        accumulator.observe(op.key)

        declared = _select_response(op, status)
        if declared is None:
            accumulator.add(
                op.key,
                "DRIFT-STATUS",
                f"returned status {status} which is not declared "
                f"(declared: {[r.status for r in op.responses]})",
                example=url,
            )
            continue

        mime = str(entry.get("response_mime") or "")
        if not mime:
            headers = entry.get("response_headers") or {}
            mime = next(
                (v for k, v in headers.items() if k.lower() == "content-type"),
                "",
            )

        schema, content_problem = _select_schema(declared, mime)
        if content_problem and declared.content:
            accumulator.add(op.key, "DRIFT-CONTENT-TYPE", content_problem, example=url)

        body = entry.get("response_body")
        if body is None:
            quality.bodies_unavailable += 1
            reason = str(entry.get("response_body_dropped") or "no body recorded")
            quality.body_drop_reasons[reason] = quality.body_drop_reasons.get(reason, 0) + 1
        elif schema is not None:
            for problem in validate_value(
                schema, body, forbid_undeclared_fields=forbid_undeclared_fields
            ):
                rule = (
                    "DRIFT-UNDECLARED-FIELD"
                    if "undeclared field" in problem
                    else (
                        "DRIFT-MISSING-FIELD" if "missing required" in problem else "DRIFT-SCHEMA"
                    )
                )
                accumulator.add(op.key, rule, problem, example=url)

        present = {k.lower() for k in (entry.get("response_headers") or {})}
        for header in declared.headers:
            if header.lower() not in present:
                accumulator.add(
                    op.key,
                    "DRIFT-HEADER",
                    f"declared response header '{header}' missing",
                    example=url,
                )

    quality.unmatched_paths = [
        label for label, _ in sorted(unmatched.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    quality.uncovered_operations = sorted(
        op.key for op in service.operations if op.method and op.path and op.key not in exercised
    )
    return CorpusDriftReport(source=source, findings=accumulator.finish(), quality=quality)
