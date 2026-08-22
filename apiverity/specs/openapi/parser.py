"""OpenAPI 3.0/3.1 → normalized contract model.

Handles JSON/YAML files and URLs, ``$ref`` resolution (with cycle
detection), source-location preservation (line numbers for YAML,
JSON-pointer provenance for JSON) and structural validation that emits
explicit findings for unresolved references, duplicate operation IDs and
conflicting operations.
"""

from __future__ import annotations

import json
from typing import Any

import yaml

from apiverity.core.model import (
    Example,
    Finding,
    Operation,
    OperationKind,
    Parameter,
    ParameterLocation,
    Protocol,
    RequestBody,
    Response,
    SchemaNode,
    SecurityRequirement,
    SecurityScheme,
    Server,
    Service,
    SourceLocation,
)
from apiverity.specs import parse_document, read_source

HTTP_METHODS = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}

_VALID_PARAM_LOCATIONS = {loc.value for loc in ParameterLocation}


class _LineTrackingLoader(yaml.SafeLoader):
    """SafeLoader that records (line, column) per constructed mapping/list."""

    line_index: dict[int, tuple[int, int]] = {}

    def construct_yaml_map(self, node: yaml.MappingNode) -> Any:
        data: dict[Any, Any] = {}
        self.line_index[id(data)] = (node.start_mark.line + 1, node.start_mark.column + 1)
        yield data
        value = self.construct_mapping(node)
        data.update(value)

    def construct_yaml_seq(self, node: yaml.SequenceNode) -> Any:
        data: list[Any] = []
        self.line_index[id(data)] = (node.start_mark.line + 1, node.start_mark.column + 1)
        yield data
        data.extend(self.construct_sequence(node))

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
        mapping = super().construct_mapping(node, deep=deep)
        self.line_index.setdefault(
            id(mapping), (node.start_mark.line + 1, node.start_mark.column + 1)
        )
        return mapping


# PyYAML registers constructor functions against the *base* class at import
# time, so overrides must be re-registered to take effect.
_LineTrackingLoader.add_constructor(
    "tag:yaml.org,2002:map", _LineTrackingLoader.construct_yaml_map
)
_LineTrackingLoader.add_constructor(
    "tag:yaml.org,2002:seq", _LineTrackingLoader.construct_yaml_seq
)


def load_yaml_with_lines(text: str) -> tuple[dict[str, Any], dict[int, tuple[int, int]]]:
    loader = _LineTrackingLoader(text)
    _LineTrackingLoader.line_index = {}
    try:
        doc = loader.get_single_data()
    finally:
        loader.dispose()
    return doc if isinstance(doc, dict) else {}, dict(_LineTrackingLoader.line_index)


class OpenApiParser:
    """Parses one OpenAPI document into a :class:`Service`."""

    def __init__(self, file_label: str) -> None:
        self.file_label = file_label
        self.findings: list[Finding] = []
        self._lines: dict[int, tuple[int, int]] = {}

    # -- location helpers ---------------------------------------------------

    def _loc(self, pointer: str, obj: Any = None) -> SourceLocation:
        line, column = 0, 0
        if obj is not None:
            hit = self._lines.get(id(obj))
            if hit:
                line, column = hit
        return SourceLocation(file=self.file_label, line=line, column=column, pointer=pointer)

    @staticmethod
    def _escape_pointer(part: str) -> str:
        return part.replace("~", "~0").replace("/", "~1")

    # -- ref resolution -----------------------------------------------------

    def resolve_ref(self, root: dict[str, Any], ref: str, pointer: str) -> Any:
        """Resolve a local or remote-style ``$ref`` against the root document.

        Only local refs (``#/...``) are resolved in-process; anything else is
        reported as an explicit finding rather than silently ignored.
        """
        if not ref.startswith("#/"):
            self.findings.append(
                Finding(
                    rule_id="SPEC-REF-EXTERNAL",
                    severity="WARN",
                    message=f"external reference '{ref}' cannot be resolved by the "
                    "built-in loader; bundle external docs or inline the schema",
                    location=self._loc(pointer),
                )
            )
            return None
        node: Any = root
        for raw_part in ref[2:].split("/"):
            part = raw_part.replace("~1", "/").replace("~0", "~")
            if isinstance(node, dict):
                if part not in node:
                    self.findings.append(
                        Finding(
                            rule_id="SPEC-REF-UNRESOLVED",
                            severity="ERROR",
                            message=f"unresolved reference '{ref}' "
                            f"(missing segment '{part}')",
                            location=self._loc(pointer),
                        )
                    )
                    return None
                node = node[part]
            elif isinstance(node, list):
                try:
                    node = node[int(part)]
                except (ValueError, IndexError):
                    self.findings.append(
                        Finding(
                            rule_id="SPEC-REF-UNRESOLVED",
                            severity="ERROR",
                            message=f"unresolved reference '{ref}'",
                            location=self._loc(pointer),
                        )
                    )
                    return None
            else:
                self.findings.append(
                    Finding(
                        rule_id="SPEC-REF-UNRESOLVED",
                        severity="ERROR",
                        message=f"unresolved reference '{ref}': traversal dead-end",
                        location=self._loc(pointer),
                    )
                )
                return None
        return node

    def deref(
        self, root: dict[str, Any], node: Any, pointer: str, seen: set[str] | None = None
    ) -> Any:
        """Follow ``$ref`` chains with cycle protection.

        ``seen`` is scoped to a single deref chain: the same schema may be
        referenced many times across the document without triggering the
        cycle detector, while genuine A→B→A cycles are still caught.
        """
        if seen is None:
            seen = set()
        hops = 0
        while isinstance(node, dict) and "$ref" in node:
            ref = str(node["$ref"])
            if ref in seen:
                self.findings.append(
                    Finding(
                        rule_id="SPEC-REF-CYCLE",
                        severity="ERROR",
                        message=f"circular reference detected at '{ref}'",
                        location=self._loc(pointer, node),
                    )
                )
                return None
            seen.add(ref)
            target = self.resolve_ref(root, ref, pointer)
            if target is None:
                return None
            node = target
            hops += 1
            if hops > 64:
                self.findings.append(
                    Finding(
                        rule_id="SPEC-REF-DEEP",
                        severity="ERROR",
                        message=f"reference chain too deep at '{ref}'",
                        location=self._loc(pointer),
                    )
                )
                return None
        return node

    # -- schema conversion ----------------------------------------------------

    def to_schema(self, root: dict[str, Any], node: Any, pointer: str) -> SchemaNode | None:
        node = self.deref(root, node, pointer)
        if node is None:
            return None
        if not isinstance(node, dict):
            self.findings.append(
                Finding(
                    rule_id="SPEC-SCHEMA-INVALID",
                    severity="ERROR",
                    message=f"schema at '{pointer}' is not an object",
                    location=self._loc(pointer, node),
                )
            )
            return None

        out = SchemaNode(
            type=node.get("type"),
            format=node.get("format"),
            title=node.get("title"),
            description=node.get("description"),
            deprecated=bool(node.get("deprecated", False)),
            default=node.get("default"),
            example=node.get("example"),
            source_location=self._loc(pointer, node),
        )

        if "enum" in node and isinstance(node["enum"], list):
            out.enum = node["enum"]
        if "const" in node:
            out.const = node["const"]

        # nullable: 3.0 uses x-nullable style boolean; 3.1 may use type arrays
        if node.get("nullable") is True:
            out.nullable = True
        t = node.get("type")
        if isinstance(t, list):
            types = [str(x) for x in t]
            if "null" in types:
                out.nullable = True
                types = [x for x in types if x != "null"]
            out.type = types[0] if len(types) == 1 else "|".join(types)

        for key, attr in (
            ("minProperties", "min_properties"),
            ("maxProperties", "max_properties"),
            ("minItems", "min_items"),
            ("maxItems", "max_items"),
            ("uniqueItems", "unique_items"),
            ("minLength", "min_length"),
            ("maxLength", "max_length"),
            ("pattern", "pattern"),
            ("minimum", "minimum"),
            ("maximum", "maximum"),
            ("exclusiveMinimum", "exclusive_minimum"),
            ("exclusiveMaximum", "exclusive_maximum"),
            ("multipleOf", "multiple_of"),
        ):
            if key in node:
                setattr(out, attr, node[key])

        props = node.get("properties")
        if isinstance(props, dict):
            for name, sub in props.items():
                converted = self.to_schema(root, sub, f"{pointer}/properties/{self._escape_pointer(name)}")
                if converted is not None:
                    out.properties[name] = converted
        required = node.get("required")
        if isinstance(required, list):
            out.required = [str(r) for r in required]

        addl = node.get("additionalProperties")
        if isinstance(addl, bool):
            out.additional_properties = addl
        elif isinstance(addl, dict):
            out.additional_properties = self.to_schema(root, addl, f"{pointer}/additionalProperties")

        if isinstance(node.get("items"), (dict, bool)):
            out.items = self.to_schema(root, node["items"], f"{pointer}/items")

        for key, attr in (("oneOf", "one_of"), ("anyOf", "any_of"), ("allOf", "all_of")):
            variants = node.get(key)
            if isinstance(variants, list):
                converted = [
                    s
                    for s in (
                        self.to_schema(root, v, f"{pointer}/{key}/{i}")
                        for i, v in enumerate(variants)
                    )
                    if s is not None
                ]
                setattr(out, attr, converted)

        return out

    # -- operations -------------------------------------------------------------

    def _to_parameter(self, root: dict[str, Any], node: Any, pointer: str) -> Parameter | None:
        node = self.deref(root, node, pointer)
        if not isinstance(node, dict):
            return None
        loc_raw = str(node.get("in", ""))
        if loc_raw not in _VALID_PARAM_LOCATIONS:
            self.findings.append(
                Finding(
                    rule_id="SPEC-PARAM-LOCATION",
                    severity="ERROR",
                    message=f"parameter '{node.get('name', '?')}' has invalid 'in' value "
                    f"'{loc_raw}'",
                    location=self._loc(pointer, node),
                )
            )
            loc_raw = "query"
        schema = None
        if isinstance(node.get("schema"), dict):
            schema = self.to_schema(root, node["schema"], f"{pointer}/schema")
        elif "content" in node:
            content = node["content"]
            if isinstance(content, dict):
                first = next(iter(content.values()), None)
                if isinstance(first, dict) and isinstance(first.get("schema"), dict):
                    schema = self.to_schema(root, first["schema"], f"{pointer}/content")
        return Parameter(
            name=str(node.get("name", "")),
            location=ParameterLocation(loc_raw),
            required=bool(node.get("required", False)),
            deprecated=bool(node.get("deprecated", False)),
            description=node.get("description"),
            schema_node=schema,
            example=node.get("example"),
            source_location=self._loc(pointer, node),
        )

    def _to_request_body(self, root: dict[str, Any], node: Any, pointer: str) -> RequestBody | None:
        node = self.deref(root, node, pointer)
        if not isinstance(node, dict):
            return None
        content: dict[str, SchemaNode] = {}
        raw_content = node.get("content") or {}
        if isinstance(raw_content, dict):
            for media, media_obj in raw_content.items():
                if isinstance(media_obj, dict) and isinstance(media_obj.get("schema"), dict):
                    converted = self.to_schema(
                        root, media_obj["schema"], f"{pointer}/content/{self._escape_pointer(str(media))}/schema"
                    )
                    if converted is not None:
                        content[str(media)] = converted
        return RequestBody(
            required=bool(node.get("required", False)),
            description=node.get("description"),
            content=content,
            source_location=self._loc(pointer, node),
        )

    def _to_response(self, root: dict[str, Any], status: str, node: Any, pointer: str) -> Response | None:
        node = self.deref(root, node, pointer)
        if not isinstance(node, dict):
            return None
        headers: dict[str, SchemaNode] = {}
        raw_headers = node.get("headers") or {}
        if isinstance(raw_headers, dict):
            for hname, hobj in raw_headers.items():
                if isinstance(hobj, dict):
                    hobj = self.deref(root, hobj, f"{pointer}/headers/{hname}")
                    if isinstance(hobj, dict) and isinstance(hobj.get("schema"), dict):
                        converted = self.to_schema(root, hobj["schema"], f"{pointer}/headers/{hname}/schema")
                        if converted is not None:
                            headers[str(hname)] = converted
        content: dict[str, SchemaNode] = {}
        raw_content = node.get("content") or {}
        if isinstance(raw_content, dict):
            for media, media_obj in raw_content.items():
                if isinstance(media_obj, dict) and isinstance(media_obj.get("schema"), dict):
                    converted = self.to_schema(
                        root, media_obj["schema"], f"{pointer}/content/{self._escape_pointer(str(media))}/schema"
                    )
                    if converted is not None:
                        content[str(media)] = converted
        return Response(
            status=status,
            description=node.get("description"),
            headers=headers,
            content=content,
            source_location=self._loc(pointer, node),
        )

    def _to_examples(self, root: dict[str, Any], node: Any, pointer: str) -> list[Example]:
        examples: list[Example] = []
        raw = node.get("examples") if isinstance(node, dict) else None
        if isinstance(raw, dict):
            for name, ex in raw.items():
                ex = self.deref(root, ex, f"{pointer}/examples/{name}")
                if isinstance(ex, dict):
                    examples.append(
                        Example(
                            name=str(name),
                            value=ex.get("value"),
                            summary=ex.get("summary"),
                            source_location=self._loc(f"{pointer}/examples/{name}", ex),
                        )
                    )
        return examples

    def _to_security_requirements(self, root: dict[str, Any], node: Any, pointer: str) -> list[SecurityRequirement]:
        reqs: list[SecurityRequirement] = []
        if isinstance(node, list):
            for i, entry in enumerate(node):
                if isinstance(entry, dict):
                    for scheme_name, scopes in entry.items():
                        reqs.append(
                            SecurityRequirement(
                                scheme_name=str(scheme_name),
                                scopes=[str(s) for s in scopes] if isinstance(scopes, list) else [],
                            )
                        )
        return reqs

    # -- top level ----------------------------------------------------------------

    def parse(self, source: str) -> tuple[Service, list[Finding]]:
        _, raw = read_source(source)
        text = raw.decode("utf-8-sig")

        # JSON gets pointer-only provenance; YAML gets real line numbers.
        is_json = False
        try:
            json.loads(text)
            is_json = True
        except ValueError:
            pass

        if is_json:
            doc = parse_document(raw)
        else:
            doc, self._lines = load_yaml_with_lines(text)
            if not doc:
                doc = parse_document(raw)

        openapi_version = str(doc.get("openapi", ""))
        if not openapi_version.startswith(("3.0", "3.1")):
            self.findings.append(
                Finding(
                    rule_id="SPEC-VERSION-UNSUPPORTED",
                    severity="ERROR",
                    message=f"unsupported OpenAPI version '{openapi_version or '(missing)'}'; "
                    "expected 3.0.x or 3.1.x",
                    location=self._loc(""),
                )
            )

        info = doc.get("info") or {}
        service = Service(
            title=str(info.get("title", "Untitled API")),
            version=str(info.get("version", "0.0.0")),
            protocol=Protocol.OPENAPI,
            description=info.get("description"),
            source_file=self.file_label,
            source_location=self._loc("/info"),
        )

        servers = doc.get("servers")
        if isinstance(servers, list):
            for i, srv in enumerate(servers):
                if isinstance(srv, dict) and "url" in srv:
                    service.servers.append(
                        Server(url=str(srv["url"]), description=srv.get("description"))
                    )

        # security schemes
        schemes = doc.get("components", {}).get("securitySchemes") or {}
        if isinstance(schemes, dict):
            for name, sch in schemes.items():
                sch = self.deref(doc, sch, f"/components/securitySchemes/{name}")
                if not isinstance(sch, dict):
                    continue
                loc_raw = sch.get("in")
                service.security_schemes[str(name)] = SecurityScheme(
                    name=str(name),
                    type=str(sch.get("type", "")),
                    location=ParameterLocation(loc_raw) if loc_raw in _VALID_PARAM_LOCATIONS else None,
                    scheme=sch.get("scheme"),
                    bearer_format=sch.get("bearerFormat"),
                    deprecated=bool(sch.get("deprecated", False)),
                    source_location=self._loc(f"/components/securitySchemes/{name}", sch),
                )

        global_security = self._to_security_requirements(
            doc, doc.get("security"), "/security"
        )
        service.global_security = global_security

        paths = doc.get("paths") or {}
        if not isinstance(paths, dict):
            paths = {}
        seen_operation_ids: dict[str, str] = {}
        seen_keys: dict[str, str] = {}

        for path_str, path_item in paths.items():
            path_pointer = f"/paths/{self._escape_pointer(str(path_str))}"
            if not isinstance(path_item, dict):
                continue
            path_item = self.deref(doc, path_item, path_pointer)
            if not isinstance(path_item, dict):
                continue

            # path-level parameters apply to all operations on this path
            path_params_raw = path_item.get("parameters") or []

            for method in HTTP_METHODS:
                op_node = path_item.get(method)
                if op_node is None:
                    continue
                op_pointer = f"{path_pointer}/{method}"
                op_node = self.deref(doc, op_node, op_pointer)
                if not isinstance(op_node, dict):
                    continue

                key = f"{method.upper()} {path_str}"
                if key in seen_keys:
                    self.findings.append(
                        Finding(
                            rule_id="SPEC-OP-DUPLICATE",
                            severity="ERROR",
                            message=f"duplicate/conflicting operation '{key}'",
                            location=self._loc(op_pointer, op_node),
                        )
                    )
                seen_keys[key] = op_pointer

                parameters: list[Parameter] = []
                for i, p in enumerate(path_params_raw):
                    conv = self._to_parameter(doc, p, f"{path_pointer}/parameters/{i}")
                    if conv is not None:
                        parameters.append(conv)
                for i, p in enumerate(op_node.get("parameters") or []):
                    conv = self._to_parameter(doc, p, f"{op_pointer}/parameters/{i}")
                    if conv is not None:
                        parameters.append(conv)

                request_body = None
                if isinstance(op_node.get("requestBody"), dict):
                    request_body = self._to_request_body(
                        doc, op_node["requestBody"], f"{op_pointer}/requestBody"
                    )

                responses: list[Response] = []
                raw_responses = op_node.get("responses") or {}
                if not raw_responses:
                    self.findings.append(
                        Finding(
                            rule_id="SPEC-RESPONSE-MISSING",
                            severity="WARN",
                            message=f"operation '{key}' declares no responses",
                            location=self._loc(op_pointer, op_node),
                        )
                    )
                if isinstance(raw_responses, dict):
                    for status, resp in raw_responses.items():
                        conv = self._to_response(
                            doc, str(status), resp, f"{op_pointer}/responses/{status}"
                        )
                        if conv is not None:
                            responses.append(conv)

                op_id = op_node.get("operationId")
                if op_id is not None:
                    op_id = str(op_id)
                    if op_id in seen_operation_ids:
                        self.findings.append(
                            Finding(
                                rule_id="SPEC-OPID-DUPLICATE",
                                severity="ERROR",
                                message=f"duplicate operationId '{op_id}' "
                                f"(also used by {seen_operation_ids[op_id]})",
                                location=self._loc(op_pointer, op_node),
                            )
                        )
                    else:
                        seen_operation_ids[op_id] = key

                op_security = None
                if "security" in op_node:
                    op_security = self._to_security_requirements(
                        doc, op_node.get("security"), f"{op_pointer}/security"
                    )

                service.operations.append(
                    Operation(
                        kind=OperationKind.HTTP,
                        operation_id=op_id,
                        method=method.upper(),
                        path=str(path_str),
                        summary=op_node.get("summary"),
                        description=op_node.get("description"),
                        deprecated=bool(op_node.get("deprecated", False)),
                        tags=[str(t) for t in op_node.get("tags") or []],
                        parameters=parameters,
                        request_body=request_body,
                        responses=responses,
                        security=op_security,
                        examples=self._to_examples(doc, op_node, op_pointer),
                        source_location=self._loc(op_pointer, op_node),
                    )
                )

        service.operations.sort(key=lambda o: o.key)
        return service, self.findings


def load_openapi(source: str) -> tuple[Service, list[Finding]]:
    from pathlib import Path as _Path

    label = source if source.startswith("http") else _Path(source).name
    return OpenApiParser(label).parse(source)