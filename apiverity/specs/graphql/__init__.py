"""GraphQL SDL spec plugin (foundation).

Loads SDL schemas into the normalized model: fields on Query/Mutation/
Subscription become operations; arguments become parameters. Structural
diffing (removed fields, nullability, enum changes, new required
arguments) is supported by the shared diff engine via this model.
"""

from __future__ import annotations

from typing import Any

from apiverity.core.model import (
    Finding,
    Operation,
    OperationKind,
    Parameter,
    ParameterLocation,
    Protocol,
    SchemaNode,
    Service,
    SourceLocation,
)
from apiverity.specs import SpecPlugin

try:
    from graphql import build_schema, parse, visit  # type: ignore[import-untyped]

    _HAS_GRAPHQL = True
except ImportError:  # pragma: no cover - optional extra
    _HAS_GRAPHQL = False


def _type_to_schema(type_node: Any) -> SchemaNode:
    """Convert a GraphQL type node into a SchemaNode."""
    name = str(type_node)
    nullable = not name.startswith("[") or not name.endswith("!")
    base = name.strip("[]!")
    inner_nullable = "!" not in name.removeprefix("[").removesuffix("]")
    mapping = {
        "Int": ("integer", "int32"),
        "Float": ("number", None),
        "String": ("string", None),
        "Boolean": ("boolean", None),
        "ID": ("string", "uuid"),
    }
    t, fmt = mapping.get(base, (None, None))
    return SchemaNode(
        type=t or "object",
        format=fmt,
        nullable=nullable and inner_nullable,
        title=base if t is None else None,
    )


class GraphQlSpecPlugin(SpecPlugin):
    """Normalizes GraphQL SDL into the core model."""

    def protocol(self) -> Protocol:
        return Protocol.GRAPHQL

    def detect(self, source: str, raw: bytes | None = None) -> bool:
        if raw is None:
            try:
                from apiverity.specs import read_source

                _, raw = read_source(source)
            except Exception:
                return False
        text = raw.decode("utf-8-sig", errors="replace")
        return ("type Query" in text or "schema {" in text) and "openapi" not in text

    def load(self, source: str) -> tuple[Service, list[Finding]]:
        findings: list[Finding] = []
        if not _HAS_GRAPHQL:
            raise NotImplementedError(
                "GraphQL support requires the 'graphql' extra: "
                "pip install api-verity-lab[graphql]"
            )
        from apiverity.specs import read_source

        _, raw = read_source(source)
        sdl = raw.decode("utf-8-sig")
        from pathlib import Path as _Path
        label = _Path(source).name

        try:
            doc = parse(sdl)
        except Exception as exc:  # noqa: BLE001 - surfaced as finding
            return (
                Service(title="Invalid GraphQL schema", version="0", protocol=Protocol.GRAPHQL),
                [
                    Finding(
                        rule_id="SPEC-SDL-INVALID",
                        severity="ERROR",
                        message=f"failed to parse GraphQL SDL: {exc}",
                        location=SourceLocation(file=label),
                    )
                ],
            )

        service = Service(
            title=label.rsplit(".", 1)[0],
            version="0",
            protocol=Protocol.GRAPHQL,
            source_file=label,
        )

        # Walk object type definitions for root operation types.
        try:
            schema_obj = build_schema(sdl)
        except Exception as exc:  # noqa: BLE001
            findings.append(
                Finding(
                    rule_id="SPEC-SDL-BUILD",
                    severity="WARN",
                    message=f"SDL parsed but schema build failed: {exc}",
                    location=SourceLocation(file=label),
                )
            )
            schema_obj = None

        root_names = {}
        if schema_obj is not None:
            for op_type in ("query", "mutation", "subscription"):
                t = getattr(schema_obj, f"{op_type}_type", None)
                if t is not None:
                    root_names[t.name] = op_type.capitalize()

        for definition in doc.definitions:
            kind = getattr(definition, "kind", "")
            if str(kind) != "ObjectTypeDefinition" and str(kind) != "ObjectTypeExtension":
                continue
            type_name = getattr(definition.name, "value", None)
            if type_name is None:
                continue
            role = root_names.get(type_name)
            if role is None:
                continue
            for field in definition.fields or []:
                params: list[Parameter] = []
                for arg in field.arguments or []:
                    params.append(
                        Parameter(
                            name=arg.name.value,
                            location=ParameterLocation.QUERY,
                            required=str(arg.type).endswith("!"),
                            schema=_type_to_schema(arg.type),
                            source_location=SourceLocation(
                                file=label, line=getattr(arg.loc, "start_token", None).line
                                if getattr(arg, "loc", None) else 0
                            ),
                        )
                    )
                deprecated = bool(field.directives) and any(
                    d.name.value == "deprecated" for d in field.directives
                )
                service.operations.append(
                    Operation(
                        kind=OperationKind.GRAPHQL_FIELD,
                        rpc_name=field.name.value,
                        service_name=role,
                        summary=f"{role}.{field.name.value}",
                        deprecated=deprecated,
                        parameters=params,
                        responses=[],
                        source_location=SourceLocation(
                            file=label,
                            line=field.loc.start_token.line if field.loc else 0,
                        ),
                    )
                )

        service.operations.sort(key=lambda o: o.key)
        return service, findings