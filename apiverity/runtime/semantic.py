"""Behaviour that changed while the contract did not.

Every other check in this project asks whether reality matches the document.
This one asks whether reality matches *itself* -- whether the service is still
doing what it was doing last month. The cases it exists for are all
contract-valid, which is exactly why nothing else catches them:

- An optional field that used to be populated in every response and now appears
  in none. The schema says optional, so the contract is satisfied, the drift
  check is silent, and every consumer that read it gets nothing.
- An enum value that stops appearing. `status` still declares
  `[pending, active, archived]`, and `archived` has not been returned since the
  migration. A consumer with a branch for it has dead code and does not know.
- A field whose null rate jumps from 2% to 80%. Nullable is nullable, and the
  meaning of the response changed anyway.

None of these is a defect on its own. A field that stops being populated may be
a feature nobody uses any more, and a missing enum value may just mean nobody
hit that state this week. So every finding here states its sample sizes and
declines to speak when they are too small: the whole value of this check is
that it distinguishes a change from a coincidence, and one that reported both
would be worse than none.

What a profile is
-----------------
Per operation, per response field: how many responses were seen, in how many
the field was present, in how many it was null, and which scalar values
appeared (up to a cap). That is enough to answer all three questions above and
small enough to commit next to a contract as a baseline.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, Field

from apiverity.core.model import Service
from apiverity.runtime.corpus_drift import match_operation

__all__ = [
    "DISTINCT_VALUE_CAP",
    "MIN_SAMPLES",
    "FieldProfile",
    "SemanticFinding",
    "SemanticReport",
    "compare_profiles",
    "profile_corpus",
]

#: Below this many observations on either side, a comparison says nothing.
#:
#: Three responses out of three, then zero out of two, is not evidence that a
#: field was abandoned -- it is two requests. The number is a judgement call;
#: the refusal to speak without it is not.
MIN_SAMPLES = 20

#: Distinct scalar values recorded per field before the field is treated as
#: unbounded and its values stop being tracked.
#:
#: An id field has one value per response, so recording them would turn a
#: profile into a copy of the corpus -- and a corpus is the thing this exists
#: to avoid having to keep.
DISTINCT_VALUE_CAP = 24

#: A presence or null rate must move by at least this much before it is
#: reported. Real traffic wobbles.
RATE_SHIFT = 0.25


class FieldProfile(BaseModel):
    """What one response field did, across a corpus."""

    #: `$.data.items[].status` -- array positions collapsed, because index 0
    #: and index 4 are the same field.
    path: str
    #: Responses in which the enclosing object was seen at all.
    observations: int = 0
    #: ...of which the field was present.
    present: int = 0
    #: ...of which its value was null.
    nulls: int = 0
    #: Distinct scalar values seen, sorted. Empty once the cap is exceeded,
    #: with `unbounded` set -- an empty list and "too many to track" are
    #: different facts and must not look alike.
    values: list[str] = Field(default_factory=list)
    unbounded: bool = False

    @property
    def presence_rate(self) -> float:
        return self.present / self.observations if self.observations else 0.0

    @property
    def null_rate(self) -> float:
        return self.nulls / self.present if self.present else 0.0


class OperationProfile(BaseModel):
    operation_key: str
    responses: int = 0
    fields: dict[str, FieldProfile] = Field(default_factory=dict)


class CorpusProfile(BaseModel):
    """A behavioural fingerprint of one corpus. Small enough to commit."""

    source: str = ""
    entries: int = 0
    matched: int = 0
    operations: dict[str, OperationProfile] = Field(default_factory=dict)


class SemanticFinding(BaseModel):
    operation_key: str
    rule_id: str
    severity: str = "WARN"
    message: str
    field_path: str = ""
    #: The evidence, so a reader can judge the claim rather than trust it.
    before: dict[str, Any] = Field(default_factory=dict)
    after: dict[str, Any] = Field(default_factory=dict)


class SemanticReport(BaseModel):
    before: str = ""
    after: str = ""
    findings: list[SemanticFinding] = Field(default_factory=list)
    #: Fields compared, and fields skipped for want of samples. Both reported:
    #: "nothing changed" and "we could not tell" are different answers.
    compared: int = 0
    skipped_for_samples: int = 0


# ------------------------------------------------------------------ profiling


def _walk(value: Any, path: str, out: dict[str, list[Any]]) -> None:
    """Collect every leaf, keyed by a path with array indices collapsed."""
    if isinstance(value, dict):
        for key, child in value.items():
            out.setdefault(f"{path}.{key}", []).append(child)
            _walk(child, f"{path}.{key}", out)
    elif isinstance(value, list):
        for child in value:
            _walk(child, f"{path}[]", out)


def _scalar(value: Any) -> str | None:
    """A short, stable rendering of a scalar. None for anything else."""
    if value is None or isinstance(value, (dict, list)):
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value)
    return text if len(text) <= 64 else None


def profile_corpus(
    service: Service,
    entries: list[dict[str, Any]],
    *,
    source: str = "",
) -> CorpusProfile:
    """Summarise what the responses in a corpus actually contained."""
    profile = CorpusProfile(source=source, entries=len(entries))

    for entry in entries:
        method = str(entry.get("method") or "")
        url = str(entry.get("url") or "")
        if not method or not url:
            continue
        op = match_operation(service, method, urlsplit(url).path or "/")
        if op is None:
            continue
        body = entry.get("response_body")
        if not isinstance(body, (dict, list)):
            # A body that is absent or scalar carries no fields to profile.
            # Counted as matched anyway: it is a response this operation
            # served, and excluding it would inflate every presence rate.
            profile.matched += 1
            op_profile = profile.operations.setdefault(
                op.key, OperationProfile(operation_key=op.key)
            )
            op_profile.responses += 1
            continue

        profile.matched += 1
        op_profile = profile.operations.setdefault(op.key, OperationProfile(operation_key=op.key))
        op_profile.responses += 1

        seen: dict[str, list[Any]] = {}
        _walk(body, "$", seen)
        for path, values in seen.items():
            field = op_profile.fields.get(path)
            if field is None:
                field = FieldProfile(path=path)
                op_profile.fields[path] = field
            # One response counts once for presence, however many array
            # elements carried the field: otherwise a list of fifty makes one
            # response look like fifty observations.
            field.present += 1
            if all(v is None for v in values):
                field.nulls += 1
            if not field.unbounded:
                for value in values:
                    rendered = _scalar(value)
                    if rendered is None:
                        continue
                    if rendered not in field.values:
                        field.values.append(rendered)
                    if len(field.values) > DISTINCT_VALUE_CAP:
                        field.unbounded = True
                        field.values = []
                        break

    for op_profile in profile.operations.values():
        for field in op_profile.fields.values():
            field.observations = op_profile.responses
            field.values.sort()
    return profile


# ----------------------------------------------------------------- comparison


def _evidence(field: FieldProfile | None) -> dict[str, Any]:
    if field is None:
        return {"observations": 0, "present": 0}
    return {
        "observations": field.observations,
        "present": field.present,
        "presence_rate": round(field.presence_rate, 3),
        "nulls": field.nulls,
        "distinct_values": "unbounded" if field.unbounded else len(field.values),
    }


def compare_profiles(
    before: CorpusProfile,
    after: CorpusProfile,
    *,
    min_samples: int = MIN_SAMPLES,
) -> SemanticReport:
    """What the service stopped doing, or started doing, between two corpora."""
    report = SemanticReport(before=before.source, after=after.source)

    for key, new_op in sorted(after.operations.items()):
        old_op = before.operations.get(key)
        if old_op is None:
            continue
        if old_op.responses < min_samples or new_op.responses < min_samples:
            report.skipped_for_samples += len(set(old_op.fields) | set(new_op.fields))
            continue

        for path in sorted(set(old_op.fields) | set(new_op.fields)):
            old = old_op.fields.get(path)
            new = new_op.fields.get(path)
            report.compared += 1
            report.findings.extend(_compare_field(key, path, old, new))

    report.findings.sort(key=lambda f: (f.operation_key, f.field_path, f.rule_id))
    return report


def _compare_field(
    operation_key: str,
    path: str,
    old: FieldProfile | None,
    new: FieldProfile | None,
) -> list[SemanticFinding]:
    findings: list[SemanticFinding] = []

    def finding(*, rule_id: str, severity: str, message: str) -> SemanticFinding:
        return SemanticFinding(
            operation_key=operation_key,
            rule_id=rule_id,
            severity=severity,
            message=message,
            field_path=path,
            before=_evidence(old),
            after=_evidence(new),
        )

    old_rate = old.presence_rate if old else 0.0
    new_rate = new.presence_rate if new else 0.0

    if old_rate >= 0.9 and new_rate == 0.0:
        findings.append(
            finding(
                rule_id="SEMANTIC-FIELD-ABANDONED",
                severity="ERROR",
                message=f"`{path}` was present in {old_rate:.0%} of responses and is now present in "
                "none. The schema still declares it, so nothing else reports this -- and "
                "every consumer reading it now gets nothing",
            )
        )
    elif old_rate >= 0.9 and new_rate < 0.9 - RATE_SHIFT:
        findings.append(
            finding(
                rule_id="SEMANTIC-FIELD-INTERMITTENT",
                severity="WARN",
                message=f"`{path}` was present in {old_rate:.0%} of responses and is now present in "
                f"{new_rate:.0%}. A consumer that treated it as always-there is now reading "
                "it sometimes",
            )
        )
    elif old_rate == 0.0 and new_rate >= 0.9:
        findings.append(
            finding(
                rule_id="SEMANTIC-FIELD-APPEARED",
                severity="INFO",
                message=f"`{path}` was never present and is now present in {new_rate:.0%} of "
                "responses. Additive, and worth knowing: the contract may not declare it",
            )
        )

    if old is not None and new is not None and old.present and new.present:
        shift = new.null_rate - old.null_rate
        if shift >= RATE_SHIFT:
            findings.append(
                finding(
                    rule_id="SEMANTIC-NULL-RATE-ROSE",
                    severity="WARN",
                    message=f"`{path}` was null in {old.null_rate:.0%} of the responses that carried "
                    f"it and is now null in {new.null_rate:.0%}. Nullable is nullable, and "
                    "the meaning of the response changed anyway",
                )
            )

    if (
        old is not None
        and new is not None
        and not old.unbounded
        and not new.unbounded
        and old.values
        and new.values
    ):
        gone = [v for v in old.values if v not in new.values]
        added = [v for v in new.values if v not in old.values]
        if gone:
            findings.append(
                finding(
                    rule_id="SEMANTIC-VALUE-GONE",
                    severity="WARN",
                    message=f"`{path}` no longer returns {gone[:5]}. The schema still permits them, "
                    "so a consumer with a branch for one has dead code and no way to find out",
                )
            )
        if added:
            findings.append(
                finding(
                    rule_id="SEMANTIC-VALUE-NEW",
                    severity="WARN",
                    message=f"`{path}` started returning {added[:5]}, which it never returned before. "
                    "A consumer that switched exhaustively on the old set now falls through",
                )
            )

    return findings
