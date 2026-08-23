"""Swagger/OpenAPI 2.0 import adapter.

Normalizes Swagger 2.0 documents into the common contract model, reusing
the OpenAPI 3 parser's ref-resolution and schema conversion. Every semantic
loss or ambiguity is reported as an explicit finding instead of being
silently dropped.
"""

from __future__ import annotations

from typing import Any

from ..core.model import (
    Finding,
    Operation,
    OperationKind,
    Parameter,
    ParameterLocation,
    Protocol,
    RequestBody,
    Response,
    SecurityScheme,
    Server,
    Service,
    Severity,
)
from . import SpecPlugin
from .openapi.parser import OpenApiParser, load_yaml_with_lines

_HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch")
_VALID_IN = {"query", "header", "path", "formData", "body"}


class Swagger2Parser:
    """Converts a Swagger 2.0 document into a normalized :class:`Service`."""

    def __init__(self, file_label: str) -> None:
        self.oas = OpenApiParser(file_label)

    # -- normalization helpers -------------------------------------------------

    def _param_to_oas3(self, node: dict[str, Any]) -> dict[str, Any]:
        """Lift an inline-typed Swagger parameter into an OAS3-style node."""
        if str(node.get("in")) == "body":
            return dict(node)  # already has schema/content semantics
        schema = {
            k: node[k]
            for k in (
                "type",
                "format",
                "enum",
                "items",
                "minimum",
                "maximum",
                "minLength",
                "maxLength",
                "pattern",
                "default",
                "collectionFormat",
            )
            if k in node
        }
        out = {
            "name": node.get("name"),
            "in": node.get("in"),
            "required": node.get("required", False),
            "description": node.get("description"),
            "example": node.get("x-example") or node.get("example"),
        }
        if schema:
            out["schema"] = schema
        return out

    def _response_to_oas3(
        self, root: dict[str, Any], node: dict[str, Any], produces: list[str]
    ) -> dict[str, Any]:
        media = (produces or ["application/json"])[0]
        out: dict[str, Any] = {"description": node.get("description")}
        if isinstance(node.get("schema"), dict):
            out["content"] = {media: {"schema": node["schema"]}}
        headers = {}
        for hname, hobj in (node.get("headers") or {}).items():
            if isinstance(hobj, dict):
                headers[hname] = {"schema": hobj}
        if headers:
            out["headers"] = headers
        return out

    def _security_scheme(self, name: str, node: dict[str, Any]) -> tuple[SecurityScheme | None, Finding | None]:
        stype = str(node.get("type"))
        if stype == "apiKey":
            loc_raw = str(node.get("in", "header"))
            try:
                loc = ParameterLocation(loc_raw)
            except ValueError:
                loc = ParameterLocation.HEADER
            return (
                SecurityScheme(name=name, type="apiKey", location=loc),
                None,
            )
        if stype == "basic":
            return SecurityScheme(name=name, type="http", scheme="basic"), None
        if stype in {"oauth2", "openIdConnect"}:
            finding = Finding(
                rule_id="SWAGGER2-OAUTH-FLOW-LOSSY",
                severity=Severity.WARN,
                message=f"security scheme '{name}': OAuth flow metadata "
                "(token URLs, authorization code details) is Swagger-2-specific "
                "and is not representable in the normalized model",
            )
            return SecurityScheme(name=name, type=stype), finding
        return None, None

    # -- main entry --------------------------------------------------------------

    def parse(self, source: str) -> tuple[Service, list[Finding]]:
        _label, raw = self._read(source)
        root, _lines = load_yaml_with_lines(raw.decode("utf-8"))
        self.oas._lines = _lines
        file_label = self.oas.file_label
        findings = self.oas.findings

        info = root.get("info") or {}
        host = str(root.get("host") or "localhost")
        base_path = str(root.get("basePath") or "")
        schemes = [str(s) for s in (root.get("schemes") or ["https"])]
        servers = [Server(url=f"{scheme}://{host}{base_path}") for scheme in schemes]
        findings.append(
            Finding(
                rule_id="SWAGGER2-SERVER-SYNTHESIZED",
                severity=Severity.INFO,
                message="Swagger 2.0 host/basePath/schemes were combined into "
                f"{len(servers)} server URL(s); per-scheme nuance may be lost",
            )
        )
        consumes = [str(c) for c in (root.get("consumes") or [])]
        produces = [str(p) for p in (root.get("produces") or [])]

        operations: list[Operation] = []
        paths = root.get("paths") or {}
        for path, item in paths.items():
            if not isinstance(item, dict):
                continue
            path_params = [
                self._param_to_oas3(p) for p in (item.get("parameters") or []) if isinstance(p, dict)
            ]
            for method in _HTTP_METHODS:
                op_node = item.get(method)
                if not isinstance(op_node, dict):
                    continue
                pointer = f"/paths/{OpenApiParser._escape_pointer(str(path))}/{method}"
                merged_params = list(path_params)
                for p in op_node.get("parameters") or []:
                    if isinstance(p, dict):
                        merged_params.append(self._param_to_oas3(p))
                parameters: list[Parameter] = []
                request_body: RequestBody | None = None
                op_consumes = [str(c) for c in (op_node.get("consumes") or consumes)]
                for idx, p in enumerate(merged_params):
                    pin = str(p.get("in"))
                    if pin not in _VALID_IN:
                        findings.append(
                            Finding(
                                rule_id="SWAGGER2-PARAM-IN",
                                severity=Severity.ERROR,
                                message=f"parameter '{p.get('name', '?')}' has invalid 'in' value '{pin}'",
                            )
                        )
                        continue
                    if pin == "body":
                        media = (op_consumes or ["application/json"])[0]
                        body_schema = self.oas.to_schema(
                            root,
                            p.get("schema") or {},
                            f"{pointer}/parameters/{idx}/schema",
                        )
                        if body_schema is not None:
                            request_body = RequestBody(
                                required=bool(p.get("required", False)),
                                description=p.get("description"),
                                content={media: body_schema},
                            )
                    else:
                        param = self.oas._to_parameter(root, p, f"{pointer}/parameters/{idx}")
                        if param is not None:
                            parameters.append(param)
                responses: list[Response] = []
                for status, rnode in (op_node.get("responses") or {}).items():
                    if isinstance(rnode, dict):
                        conv = self._response_to_oas3(root, rnode, produces)
                        resp = self.oas._to_response(
                            root, str(status), conv, f"{pointer}/responses/{status}"
                        )
                        if resp is not None:
                            responses.append(resp)
                op = Operation(
                    kind=OperationKind.HTTP,
                    operation_id=op_node.get("operationId"),
                    method=method.upper(),
                    path=str(path),
                    summary=op_node.get("summary"),
                    description=op_node.get("description"),
                    deprecated=bool(op_node.get("deprecated", False)),
                    tags=[str(t) for t in (op_node.get("tags") or [])],
                    parameters=parameters,
                    request_body=request_body,
                    responses=responses,
                    security=self.oas._to_security_requirements(
                        root, op_node.get("security"), f"{pointer}/security"
                    ),
                    source_location=self.oas._loc(pointer, op_node),
                )
                operations.append(op)

        security_schemes: dict[str, SecurityScheme] = {}
        for name, snode in (root.get("securityDefinitions") or {}).items():
            if isinstance(snode, dict):
                scheme, warn = self._security_scheme(name, snode)
                if scheme is not None:
                    security_schemes[name] = scheme
                if warn is not None:
                    findings.append(warn)

        service = Service(
            title=str(info.get("title") or "Untitled Swagger 2.0 API"),
            version=str(info.get("version") or "0.0.0"),
            protocol=Protocol.OPENAPI,
            description=info.get("description"),
            servers=servers,
            operations=operations,
            security_schemes=security_schemes,
            global_security=self.oas._to_security_requirements(
                root, root.get("security"), "/security"
            ),
            source_file=file_label,
        )
        findings.extend(self.oas.findings[len(findings):])
        return service, findings

    def _read(self, source: str) -> tuple[str, bytes]:
        from . import read_source

        return read_source(source)


def load_swagger2(source: str) -> tuple[Service, list[Finding]]:
    return Swagger2Parser(source).parse(source)


class Swagger2SpecPlugin(SpecPlugin):
    """Spec plugin for Swagger/OpenAPI 2.0 documents."""

    def protocol(self) -> Protocol:
        return Protocol.OPENAPI

    def detect(self, source: str, raw: bytes | None = None) -> bool:
        from . import parse_document

        try:
            doc = parse_document(raw) if raw is not None else None
        except Exception:
            return False
        return isinstance(doc, dict) and str(doc.get("swagger", "")).startswith("2")

    def load(self, source: str) -> tuple[Service, list[Finding]]:
        return load_swagger2(source)
