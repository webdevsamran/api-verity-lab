"""OpenAPI 3.0/3.1/3.2 → normalized contract model.

Handles JSON/YAML files and URLs, ``$ref`` resolution (with cycle
detection), source-location preservation (line numbers for YAML,
JSON-pointer provenance for JSON) and structural validation that emits
explicit findings for unresolved references, duplicate operation IDs and
conflicting operations.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar

import yaml

from apiverity.core.model import (
    Example,
    Finding,
    Link,
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
    Severity,
    SourceLocation,
)
from apiverity.specs import parse_document, read_source

#: Versions this adapter understands. A 3.3 document is refused rather than
#: parsed on the assumption it resembles 3.2: guessing at a format nobody has
#: published produces a contract that looks parsed and is wrong.
SUPPORTED_OPENAPI_VERSIONS = ("3.0", "3.1", "3.2")

#: OAuth2 flows any supported OpenAPI version defines. `deviceAuthorization`
#: is new in 3.2, for inputs a browser cannot reach -- TVs, kiosks, CLIs on
#: headless machines.
_KNOWN_OAUTH_FLOWS = frozenset(
    {"implicit", "password", "clientCredentials", "authorizationCode", "deviceAuthorization"}
)

#: OpenAPI 3.2 adds `query` as a first-class method -- a payload-carrying read,
#: formalised because APIs were already tunnelling large filters through POST.
#: It sits in this set rather than in `additionalOperations` because the
#: specification names it directly.
HTTP_METHODS = {"get", "put", "post", "delete", "options", "head", "patch", "trace", "query"}

_VALID_PARAM_LOCATIONS = {loc.value for loc in ParameterLocation}


class _LineTrackingLoader(yaml.SafeLoader):
    """SafeLoader that records (line, column) per constructed mapping/list."""

    line_index: ClassVar[dict[int, tuple[int, int]]] = {}

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
_LineTrackingLoader.add_constructor("tag:yaml.org,2002:map", _LineTrackingLoader.construct_yaml_map)
_LineTrackingLoader.add_constructor("tag:yaml.org,2002:seq", _LineTrackingLoader.construct_yaml_seq)


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

    def __init__(self, file_label: str, *, allow_remote_refs: bool = False) -> None:
        self.file_label = file_label
        self.findings: list[Finding] = []
        self._lines: dict[int, tuple[int, int]] = {}
        #: `id(node)` -> the file it came from. Populated by the bundler, so a
        #: finding about a schema that lives in `schemas/user.yaml` is reported
        #: against that file rather than against the entry document, where the
        #: reader would go looking for a line that is not there.
        self._origins: dict[int, str] = {}
        self.allow_remote_refs = allow_remote_refs
        #: Sources the bundler read, entry document first. Recorded so a run
        #: can say what it actually opened.
        self.sources: list[str] = []

    # -- location helpers ---------------------------------------------------

    def _loc(self, pointer: str, obj: Any = None) -> SourceLocation:
        line, column = 0, 0
        file = self.file_label
        if obj is not None:
            hit = self._lines.get(id(obj))
            if hit:
                line, column = hit
            file = self._origins.get(id(obj), file)
        return SourceLocation(file=file, line=line, column=column, pointer=pointer)

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
            # Anything still external here is one the bundler declined to
            # rewrite -- a refused absolute path, an unfetched URL, a file it
            # could not read -- and it has already said why, naming the ref.
            # Repeating that as a second finding would double-count it.
            return None
        node: Any = root
        for raw_part in ref[2:].split("/"):
            part = raw_part.replace("~1", "/").replace("~0", "~")
            if isinstance(node, dict):
                if part not in node:
                    self.findings.append(
                        Finding(
                            rule_id="SPEC-REF-UNRESOLVED",
                            severity=Severity.ERROR,
                            message=f"unresolved reference '{ref}' (missing segment '{part}')",
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
                            severity=Severity.ERROR,
                            message=f"unresolved reference '{ref}'",
                            location=self._loc(pointer),
                        )
                    )
                    return None
            else:
                self.findings.append(
                    Finding(
                        rule_id="SPEC-REF-UNRESOLVED",
                        severity=Severity.ERROR,
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
                        severity=Severity.ERROR,
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
                        severity=Severity.ERROR,
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
                    severity=Severity.ERROR,
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
                converted = self.to_schema(
                    root, sub, f"{pointer}/properties/{self._escape_pointer(name)}"
                )
                if converted is not None:
                    out.properties[name] = converted
        required = node.get("required")
        if isinstance(required, list):
            out.required = [str(r) for r in required]

        addl = node.get("additionalProperties")
        if isinstance(addl, bool):
            out.additional_properties = addl
        elif isinstance(addl, dict):
            out.additional_properties = self.to_schema(
                root, addl, f"{pointer}/additionalProperties"
            )

        if isinstance(node.get("items"), (dict, bool)):
            out.items = self.to_schema(root, node["items"], f"{pointer}/items")

        disc = node.get("discriminator")
        if isinstance(disc, dict):
            out.discriminator = {
                "propertyName": disc.get("propertyName"),
                "mapping": dict(disc.get("mapping") or {}),
            }

        for key, attr in (("oneOf", "one_of"), ("anyOf", "any_of"), ("allOf", "all_of")):
            variants = node.get(key)
            if isinstance(variants, list):
                variant_schemas = [
                    s
                    for s in (
                        self.to_schema(root, v, f"{pointer}/{key}/{i}")
                        for i, v in enumerate(variants)
                    )
                    if s is not None
                ]
                setattr(out, attr, variant_schemas)

        self._read_2020_12(root, node, pointer, out)
        return out

    def _read_2020_12(
        self, root: dict[str, Any], node: dict[str, Any], pointer: str, out: SchemaNode
    ) -> None:
        """The 2020-12 keywords that used to be parsed away and dropped.

        Every one of these is a rule the document states. Dropping them meant
        the differ could not see a change to one and `validate_value` accepted
        data the schema forbids -- the two worst outcomes a contract tool has,
        from one silent omission.
        """
        prefix = node.get("prefixItems")
        if isinstance(prefix, list):
            out.prefix_items = [
                schema
                for schema in (
                    self.to_schema(root, item, f"{pointer}/prefixItems/{index}")
                    for index, item in enumerate(prefix)
                )
                if schema is not None
            ]

        if isinstance(node.get("contains"), (dict, bool)):
            out.contains = self.to_schema(root, node["contains"], f"{pointer}/contains")
        for key, attr in (("minContains", "min_contains"), ("maxContains", "max_contains")):
            if isinstance(node.get(key), int) and not isinstance(node.get(key), bool):
                setattr(out, attr, node[key])

        patterns = node.get("patternProperties")
        if isinstance(patterns, dict):
            for expression, sub in patterns.items():
                converted = self.to_schema(
                    root, sub, f"{pointer}/patternProperties/{self._escape_pointer(expression)}"
                )
                if converted is not None:
                    out.pattern_properties[str(expression)] = converted

        if isinstance(node.get("propertyNames"), dict):
            out.property_names = self.to_schema(
                root, node["propertyNames"], f"{pointer}/propertyNames"
            )

        dependent = node.get("dependentRequired")
        if isinstance(dependent, dict):
            for name, names in dependent.items():
                if isinstance(names, list):
                    out.dependent_required[str(name)] = sorted(str(n) for n in names)

        schemas = node.get("dependentSchemas")
        if isinstance(schemas, dict):
            for name, sub in schemas.items():
                converted = self.to_schema(
                    root, sub, f"{pointer}/dependentSchemas/{self._escape_pointer(name)}"
                )
                if converted is not None:
                    out.dependent_schemas[str(name)] = converted

        for key, attr in (("if", "if_schema"), ("then", "then_schema"), ("else", "else_schema")):
            if isinstance(node.get(key), dict):
                setattr(out, attr, self.to_schema(root, node[key], f"{pointer}/{key}"))

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
                    severity=Severity.ERROR,
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
                        root,
                        media_obj["schema"],
                        f"{pointer}/content/{self._escape_pointer(str(media))}/schema",
                    )
                    if converted is not None:
                        content[str(media)] = converted
        return RequestBody(
            required=bool(node.get("required", False)),
            description=node.get("description"),
            content=content,
            source_location=self._loc(pointer, node),
        )

    def _to_response(
        self, root: dict[str, Any], status: str, node: Any, pointer: str
    ) -> Response | None:
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
                        converted = self.to_schema(
                            root, hobj["schema"], f"{pointer}/headers/{hname}/schema"
                        )
                        if converted is not None:
                            headers[str(hname)] = converted
        content: dict[str, SchemaNode] = {}
        raw_content = node.get("content") or {}
        if isinstance(raw_content, dict):
            for media, media_obj in raw_content.items():
                if isinstance(media_obj, dict) and isinstance(media_obj.get("schema"), dict):
                    converted = self.to_schema(
                        root,
                        media_obj["schema"],
                        f"{pointer}/content/{self._escape_pointer(str(media))}/schema",
                    )
                    if converted is not None:
                        content[str(media)] = converted
        return Response(
            status=status,
            description=node.get("description"),
            headers=headers,
            content=content,
            links=self._to_links(node),
            source_location=self._loc(pointer, node),
        )

    def _to_links(self, node: Any) -> list[Link]:
        """Parse a response's `links` object.

        Kept tolerant: a malformed link is skipped rather than failing the
        parse. A spec is not invalid because one link entry is wrong, and the
        rest of the document is still worth reading.
        """
        raw = node.get("links") if isinstance(node, dict) else None
        if not isinstance(raw, dict):
            return []
        links: list[Link] = []
        for name, entry in raw.items():
            if not isinstance(entry, dict):
                continue
            parameters = {
                str(k): str(v)
                for k, v in (entry.get("parameters") or {}).items()
                if isinstance(entry.get("parameters"), dict)
            }
            links.append(
                Link(
                    name=str(name),
                    operation_id=entry.get("operationId"),
                    operation_ref=entry.get("operationRef"),
                    description=entry.get("description"),
                    parameters=parameters,
                    request_body=entry.get("requestBody"),
                )
            )
        return links

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

    def _to_security_requirements(
        self, root: dict[str, Any], node: Any, pointer: str
    ) -> list[SecurityRequirement]:
        reqs: list[SecurityRequirement] = []
        if isinstance(node, list):
            for entry in node:
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

    def _bundle(self, doc: dict[str, Any], source: str) -> dict[str, Any]:
        """Fold external references into this document, or say why not."""
        from apiverity.specs.bundle import bundle

        result = bundle(
            doc,
            base=source,
            allow_remote=self.allow_remote_refs,
            read_lines=load_yaml_with_lines,
        )
        self.findings.extend(result.findings)
        self._lines.update(result.lines)
        self._origins.update(result.origins)
        self.sources = list(result.files)
        return result.document

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

        # Before anything reads the document: a multi-file spec is the normal
        # shape of a real one, and until this ran, every external `$ref`
        # resolved to nothing -- so the schema behind it was *absent from the
        # model*, and the differ compared two absences and reported no change.
        doc = self._bundle(doc, source)

        openapi_version = str(doc.get("openapi", ""))
        if not openapi_version.startswith(SUPPORTED_OPENAPI_VERSIONS):
            self.findings.append(
                Finding(
                    rule_id="SPEC-VERSION-UNSUPPORTED",
                    severity=Severity.ERROR,
                    message=f"unsupported OpenAPI version '{openapi_version or '(missing)'}'; "
                    f"expected one of {', '.join(v + '.x' for v in SUPPORTED_OPENAPI_VERSIONS)}",
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

        # OpenAPI 3.2 tag objects. Before 3.2 structured navigation could only
        # be expressed through the `x-tagGroups` vendor extension, so a contract
        # that declares `parent` or `kind` is stating something a diff should be
        # able to see. Only the fields the specification defines are captured;
        # unknown keys are left in the document rather than invented into the
        # model.
        raw_tags = doc.get("tags")
        if isinstance(raw_tags, list):
            for tag in raw_tags:
                if not isinstance(tag, dict) or not tag.get("name"):
                    continue
                captured = {
                    key: tag[key]
                    for key in ("name", "summary", "description", "parent", "kind")
                    if key in tag
                }
                service.tags.append(captured)
            _report_orphan_tag_parents(service, self)

        servers = doc.get("servers")
        if isinstance(servers, list):
            for srv in servers:
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
                # Flows were never read, so `SecurityScheme.scopes` -- a field
                # the model has always declared -- was empty for every contract.
                # Scope coverage reporting cannot work without it.
                flows: dict[str, dict[str, str]] = {}
                raw_flows = sch.get("flows")
                if isinstance(raw_flows, dict):
                    for flow_name, flow in raw_flows.items():
                        if not isinstance(flow, dict):
                            continue
                        declared = flow.get("scopes")
                        flows[str(flow_name)] = (
                            {str(k): str(v) for k, v in declared.items()}
                            if isinstance(declared, dict)
                            else {}
                        )
                        if str(flow_name) not in _KNOWN_OAUTH_FLOWS:
                            self.findings.append(
                                Finding(
                                    rule_id="SPEC-OAUTH-FLOW-UNKNOWN",
                                    severity=Severity.WARN,
                                    message=(
                                        f"security scheme '{name}' declares OAuth flow "
                                        f"'{flow_name}', which no OpenAPI version defines"
                                    ),
                                    location=self._loc(
                                        f"/components/securitySchemes/{name}/flows/{flow_name}"
                                    ),
                                )
                            )
                union: dict[str, str] = {}
                for granted in flows.values():
                    union.update(granted)
                service.security_schemes[str(name)] = SecurityScheme(
                    name=str(name),
                    type=str(sch.get("type", "")),
                    location=ParameterLocation(loc_raw)
                    if loc_raw in _VALID_PARAM_LOCATIONS
                    else None,
                    scheme=sch.get("scheme"),
                    bearer_format=sch.get("bearerFormat"),
                    scopes=union,
                    oauth_flows=flows,
                    metadata_url=(
                        str(sch["oauth2MetadataUrl"])
                        if isinstance(sch.get("oauth2MetadataUrl"), str)
                        else None
                    ),
                    deprecated=bool(sch.get("deprecated", False)),
                    source_location=self._loc(f"/components/securitySchemes/{name}", sch),
                )

        global_security = self._to_security_requirements(doc, doc.get("security"), "/security")
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

            # OpenAPI 3.2 `additionalOperations` carries verbs the specification
            # does not name -- WebDAV's PROPFIND, a bespoke PURGE. They are real
            # operations with real request and response shapes, so removing one
            # has to be a breaking change like any other; the only difference is
            # where the document keeps them.
            extra_ops = path_item.get("additionalOperations")
            operation_nodes: list[tuple[str, Any, str]] = [
                (method, path_item.get(method), f"{path_pointer}/{method}")
                for method in sorted(HTTP_METHODS)
                if path_item.get(method) is not None
            ]
            if isinstance(extra_ops, dict):
                operation_nodes.extend(
                    (
                        str(verb).lower(),
                        node,
                        f"{path_pointer}/additionalOperations/{self._escape_pointer(str(verb))}",
                    )
                    for verb, node in sorted(extra_ops.items())
                )

            for method, op_node, op_pointer in operation_nodes:
                if op_node is None:
                    continue
                op_node = self.deref(doc, op_node, op_pointer)
                if not isinstance(op_node, dict):
                    continue

                key = f"{method.upper()} {path_str}"
                if key in seen_keys:
                    self.findings.append(
                        Finding(
                            rule_id="SPEC-OP-DUPLICATE",
                            severity=Severity.ERROR,
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
                            severity=Severity.WARN,
                            message=f"operation '{key}' declares no responses",
                            location=self._loc(op_pointer, op_node),
                        )
                    )
                if isinstance(raw_responses, dict):
                    for status, resp in raw_responses.items():
                        resp_conv = self._to_response(
                            doc, str(status), resp, f"{op_pointer}/responses/{status}"
                        )
                        if resp_conv is not None:
                            responses.append(resp_conv)

                op_id = op_node.get("operationId")
                if op_id is not None:
                    op_id = str(op_id)
                    if op_id in seen_operation_ids:
                        self.findings.append(
                            Finding(
                                rule_id="SPEC-OPID-DUPLICATE",
                                severity=Severity.ERROR,
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


def _report_orphan_tag_parents(service: Service, parser: OpenApiParser) -> None:
    """A tag whose `parent` names no declared tag.

    3.2 makes the hierarchy part of the contract, so a dangling parent is a
    navigation tree that cannot be built -- a rendering tool would drop the
    branch silently. Reported rather than repaired: guessing which tag was
    meant would be inventing structure the document does not have.
    """
    declared = {str(tag["name"]) for tag in service.tags}
    for tag in service.tags:
        parent = tag.get("parent")
        if parent is not None and str(parent) not in declared:
            parser.findings.append(
                Finding(
                    rule_id="SPEC-TAG-PARENT-UNKNOWN",
                    severity=Severity.WARN,
                    message=(
                        f"tag '{tag['name']}' declares parent '{parent}', which is not a "
                        "declared tag; the navigation branch cannot be built"
                    ),
                    location=parser._loc("/tags"),
                )
            )


def load_openapi(source: str, *, allow_remote_refs: bool = False) -> tuple[Service, list[Finding]]:
    from pathlib import Path as _Path

    label = source if source.startswith("http") else _Path(source).name
    return OpenApiParser(label, allow_remote_refs=allow_remote_refs).parse(source)
