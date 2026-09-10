"""Contract linting -- structural quality rules over a normalized Service.

Distinct from compatibility (breaking-change) analysis: lint findings describe
problems *within* a single contract revision, not between two.

## Two rules were removed rather than wired up

`LINT-DUP-OPID` said what `SPEC-OPID-DUPLICATE` says, and `LINT-NO-RESPONSES`
said what `SPEC-RESPONSE-MISSING` says. Both of those come from the OpenAPI
loader and reach every command that reads a contract.

While nothing executed this engine the duplication cost nothing. Running it
made one duplicated `operationId` produce two findings for one fact, which is
the wall of near-identical warnings people learn to filter -- so the engine
keeps the four rules with no live equivalent and drops the two that had one.
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
        for op in service.operations:
            self._operation_rules(service, op, findings)
        return findings

    # -- rules -------------------------------------------------------------------

    def _operation_rules(self, service: Service, op: Operation, out: list[Finding]) -> None:
        # A 2xx that describes nothing a consumer can validate against.
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
        # Examples that do not satisfy their own schema.
        #
        # Two places, because they are two different things. `op.examples` is
        # filled from an operation-level `examples` key that no version of
        # OpenAPI defines, so on a standard document it is always empty -- this
        # rule was reachable in principle and not in practice. A media type's
        # own `example` is where an example actually lives, and it is the part
        # people copy into their client.
        for pointer, schema in _iter_schemas(op):
            if schema.example is None:
                continue
            errs = validate_value(schema, schema.example)
            if errs:
                out.append(
                    Finding(
                        rule_id="LINT-INVALID-EXAMPLE",
                        severity=Severity.WARN,
                        message=(
                            f"the example at '{pointer}' on '{op.key}' violates its own "
                            f"schema: {'; '.join(errs[:3])}"
                        ),
                        operation_key=op.key,
                        location=schema.source_location,
                    )
                )
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
