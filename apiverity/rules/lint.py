"""Contract linting — structural quality rules over a normalized Service.

Distinct from compatibility (breaking-change) analysis: lint findings
describe problems *within* a single contract revision, not between two.
"""

from __future__ import annotations

from collections.abc import Iterator

from apiverity.core.model import Finding, Operation, Protocol, SchemaNode, Service, Severity
from apiverity.core.validation import validate_value


def _iter_schemas(op: Operation) -> Iterator[tuple[str, SchemaNode]]:
    """Yield (pointer, schema) for every schema attached to an operation."""
    for p in op.parameters:
        if p.schema_node is not None:
            yield f"parameters/{p.name}", p.schema_node
    if op.request_body is not None:
        for media, schema in op.request_body.content.items():
            yield f"requestBody/{media}", schema
    for resp in op.responses:
        for media, schema in resp.content.items():
            yield f"responses/{resp.status}/{media}", schema


class LintEngine:
    """Runs structural lint rules over a single contract revision."""

    def lint(self, service: Service) -> list[Finding]:
        findings: list[Finding] = []
        self._duplicate_operation_ids(service, findings)
        for op in service.operations:
            self._operation_rules(service, op, findings)
        return findings

    # -- rules -------------------------------------------------------------------

    def _duplicate_operation_ids(self, service: Service, out: list[Finding]) -> None:
        seen: dict[str, str] = {}
        for op in service.operations:
            if not op.operation_id:
                continue
            first = seen.setdefault(op.operation_id, op.key)
            if first != op.key:
                out.append(
                    Finding(
                        rule_id="LINT-DUP-OPID",
                        severity=Severity.ERROR,
                        message=(
                            f"duplicate operationId '{op.operation_id}' used by "
                            f"'{first}' and '{op.key}'"
                        ),
                        operation_key=op.key,
                        location=op.source_location,
                        hint="operationId values must be unique; code generators "
                        "produce colliding symbols otherwise",
                    )
                )

    def _operation_rules(self, service: Service, op: Operation, out: list[Finding]) -> None:
        # No documented responses at all
        if not op.responses and op.kind == "http":
            out.append(
                Finding(
                    rule_id="LINT-NO-RESPONSES",
                    severity=Severity.WARN,
                    message=f"operation '{op.key}' documents no responses",
                    operation_key=op.key,
                    location=op.source_location,
                    hint="declare at least one expected response status",
                )
            )
        # 2xx response without any content/schema
        for resp in op.responses:
            if resp.status.startswith("2") and not resp.content and not resp.headers:
                out.append(
                    Finding(
                        rule_id="LINT-EMPTY-RESPONSE",
                        severity=Severity.INFO,
                        message=(
                            f"operation '{op.key}' declares {resp.status} with no "
                            "schema or headers; consumers cannot validate payloads"
                        ),
                        operation_key=op.key,
                        location=resp.source_location,
                    )
                )
        # Contradictory requiredness / invalid examples inside schemas
        for pointer, schema in _iter_schemas(op):
            self._schema_rules(op, pointer, schema, out)
        # Examples that do not satisfy their own schema
        if op.request_body is not None:
            for media, schema in op.request_body.content.items():
                for ex in op.examples:
                    errs = validate_value(schema, ex.value)
                    if errs:
                        out.append(
                            Finding(
                                rule_id="LINT-INVALID-EXAMPLE",
                                severity=Severity.WARN,
                                message=(
                                    f"example '{ex.name}' on '{op.key}' violates the "
                                    f"{media} schema: {'; '.join(errs[:3])}"
                                ),
                                operation_key=op.key,
                                location=ex.source_location,
                            )
                        )

    def _schema_rules(
        self, op: Operation, pointer: str, schema: SchemaNode | None, out: list[Finding]
    ) -> None:
        if not isinstance(schema, SchemaNode):
            return
        props = set(schema.properties.keys())
        for req in schema.required:
            if req not in props:
                out.append(
                    Finding(
                        rule_id="LINT-CONTRADICTORY-REQUIRED",
                        severity=Severity.ERROR,
                        message=(
                            f"'{pointer}' on '{op.key}' marks '{req}' required but it "
                            "is not declared in properties"
                        ),
                        operation_key=op.key,
                        location=schema.source_location,
                    )
                )
        # Ambiguous composition: oneOf/anyOf with no discriminator and no titles
        for comp_name in ("one_of", "any_of"):
            comp = getattr(schema, comp_name, None)
            if isinstance(comp, list) and len(comp) > 1:
                titled = [b for b in comp if b.title]
                if not titled and not schema.properties:
                    out.append(
                        Finding(
                            rule_id="LINT-AMBIGUOUS-COMPOSITION",
                            severity=Severity.WARN,
                            message=(
                                f"'{pointer}' on '{op.key}' uses {comp_name} with "
                                "untitled branches and no discriminator; generated "
                                "cases will be ambiguous"
                            ),
                            operation_key=op.key,
                            location=schema.source_location,
                            hint="add title fields or a discriminator mapping",
                        )
                    )
            for branch in comp or []:
                self._schema_rules(op, f"{pointer}/{comp_name}", branch, out)
        for name, child in schema.properties.items():
            self._schema_rules(op, f"{pointer}/properties/{name}", child, out)
        if schema.items is not None:
            self._schema_rules(op, f"{pointer}/items", schema.items, out)


def lint_service(service: Service) -> list[Finding]:
    return LintEngine().lint(service)


#: Protocols the lint engine currently understands structurally.
SUPPORTED_PROTOCOLS = {Protocol.OPENAPI}
