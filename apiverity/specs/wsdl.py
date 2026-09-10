"""WSDL 1.1 adapter: SOAP contracts, in the same model as everything else.

SOAP is the format nobody puts in a launch post and everybody still runs. It is
also the one format in this list where a *tool* is usually the only reader --
generated stubs, an ESB, a mainframe gateway -- so a change nobody noticed does
not produce a confused developer, it produces a deserialization failure in
production. That is exactly the thing this project exists to catch, and it was
the last major interface description language the engine could not read.

Three decisions worth stating outright, because each of them is a limit:

**Parsing untrusted XML.** `xml.etree.ElementTree` on this Python refuses
external entities -- a `&xxe;` naming `file:///etc/passwd` raises
`ParseError: undefined entity` rather than reading the file -- but it *does*
expand internal ones, which is the billion-laughs shape. Verified by running it
rather than by reading the changelog. So a document that declares a `DOCTYPE`
at all is refused before a single entity is expanded, by an expat handler that
fires on the declaration itself. A WSDL has no legitimate use for a DTD: the
schema language here is XSD.

**What is modelled.** The XSD subset a WSDL actually uses -- elements,
`complexType`/`sequence`/`all`/`choice`, `simpleType`/`restriction` with its
facets, attributes, `complexContent`/`extension`, occurrence and `nillable`.
Everything else emits `SPEC-WSDL-UNMODELLED` naming the construct and the
element it was on. A dropped keyword does not fail, it narrows what the
contract says without telling anyone, and then the differ reports a tightened
contract as unchanged. Being told is the whole difference.

**What a fault is.** A SOAP 1.1 fault comes back as HTTP 500, and so does every
other fault on the same operation, so keying responses by HTTP status would
collapse them all into one. The identity of a fault is its name, so the status
carried here is `fault:<name>`; the HTTP status they share is in
`bindings["soap"]`.
"""

from __future__ import annotations

import io
import xml.etree.ElementTree as ET
import xml.parsers.expat
from dataclasses import dataclass, field
from typing import Any

from ..core.model import (
    Finding,
    Operation,
    OperationKind,
    Protocol,
    RequestBody,
    Response,
    SchemaNode,
    Server,
    Service,
    Severity,
    SourceLocation,
)
from . import SpecPlugin, read_source

NS_WSDL = "http://schemas.xmlsoap.org/wsdl/"
NS_SOAP11 = "http://schemas.xmlsoap.org/wsdl/soap/"
NS_SOAP12 = "http://schemas.xmlsoap.org/wsdl/soap12/"
NS_XSD = "http://www.w3.org/2001/XMLSchema"
NS_WSDL20 = "http://www.w3.org/ns/wsdl"

#: The one transport `soap:binding` names in practice. Recorded rather than
#: required: a JMS-transported SOAP service is a real thing and its contract is
#: no less diffable, it just is not reachable over HTTP.
HTTP_TRANSPORT = "http://schemas.xmlsoap.org/soap/http"

#: The media type each SOAP version puts on the wire. SOAP 1.2 changed it, and
#: a client sending the 1.1 type to a 1.2 endpoint gets a 415.
SOAP_MEDIA_TYPE = {"1.1": "text/xml", "1.2": "application/soap+xml"}

#: Every fault on an operation shares this HTTP status, which is why it cannot
#: be the response key.
FAULT_HTTP_STATUS = 500

#: A depth cap on schema resolution. XSD types may reference each other
#: cyclically and a person writes one without noticing.
MAX_DEPTH = 24

#: XSD builtins -> (model type, format). Not a complete list of the 44 builtin
#: types; the ones a WSDL uses, with the rest falling through to an untyped
#: node and a finding, because guessing at `xs:NOTATION` would be inventing.
XSD_PRIMITIVES: dict[str, tuple[str | None, str | None]] = {
    "string": ("string", None),
    "normalizedString": ("string", None),
    "token": ("string", None),
    "language": ("string", None),
    "Name": ("string", None),
    "NCName": ("string", None),
    "NMTOKEN": ("string", None),
    "ID": ("string", None),
    "IDREF": ("string", None),
    "QName": ("string", None),
    "anyURI": ("string", "uri"),
    "date": ("string", "date"),
    "dateTime": ("string", "date-time"),
    "time": ("string", "time"),
    "duration": ("string", "duration"),
    "gYear": ("string", None),
    "gYearMonth": ("string", None),
    "gMonthDay": ("string", None),
    "gDay": ("string", None),
    "gMonth": ("string", None),
    "base64Binary": ("string", "byte"),
    "hexBinary": ("string", None),
    "boolean": ("boolean", None),
    "decimal": ("number", None),
    "float": ("number", "float"),
    "double": ("number", "double"),
    "integer": ("integer", None),
    "int": ("integer", "int32"),
    "long": ("integer", "int64"),
    "short": ("integer", None),
    "byte": ("integer", None),
    "nonNegativeInteger": ("integer", None),
    "positiveInteger": ("integer", None),
    "negativeInteger": ("integer", None),
    "nonPositiveInteger": ("integer", None),
    "unsignedInt": ("integer", "int32"),
    "unsignedLong": ("integer", "int64"),
    "unsignedShort": ("integer", None),
    "unsignedByte": ("integer", None),
    # `anyType` and `anySimpleType` are the absence of a type, and the model
    # says that with `type=None` rather than with a word.
    "anyType": (None, None),
    "anySimpleType": (None, None),
}

QName = tuple[str, str]

#: The XSD elements that carry content particles. Anything else directly under
#: a `complexType` is an attribute declaration or an annotation.
_PARTICLE_TAGS = frozenset({"sequence", "all", "choice", "group"})


def _local(tag: str) -> str:
    """The local name of a `{namespace}name` tag."""
    return tag.rsplit("}", 1)[-1]


class WsdlDoctypeError(ValueError):
    """The document declares a DTD, and this parser will not expand one.

    Its own class because the answer is not "fix your WSDL" -- a DTD in a WSDL
    is either a mistake or an attack, and the caller needs to be able to tell
    this apart from a syntax error when deciding which of those it was.
    """

    def __init__(self, source: str) -> None:
        self.source = source
        super().__init__(
            f"{source!r} declares a DOCTYPE. Internal entity expansion is a denial-of-service "
            "vector (a few hundred bytes expand to gigabytes) and a WSDL has no legitimate use "
            "for a DTD -- its schema language is XSD. The document was refused before any "
            "entity was expanded."
        )


def _scan(raw: bytes, source: str) -> list[int]:
    """Refuse a DTD, and record the line every element starts on.

    Two jobs in one pass because they need the same parser. `ElementTree`
    exposes no position information at all, so the only way to put a real line
    number on a finding is to run expat alongside it and pair the two by
    document order -- both visit elements depth-first, pre-order, so element
    *i* of `root.iter()` is start-tag *i* here. Guessing a line by searching
    the text for a name would point at the wrong one of five identical
    `name="id"` attributes, which is worse than saying nothing.
    """
    lines: list[int] = []
    parser = xml.parsers.expat.ParserCreate()

    def _doctype(*_args: object) -> None:
        raise WsdlDoctypeError(source)

    def _start(_name: str, _attrs: dict[str, str]) -> None:
        lines.append(parser.CurrentLineNumber)

    parser.StartDoctypeDeclHandler = _doctype
    parser.StartElementHandler = _start
    try:
        parser.Parse(raw, True)
    except xml.parsers.expat.ExpatError:
        # A malformed document. Reported by ElementTree's own parse, which
        # produces the better message; this pass only exists for the two
        # things above.
        return []
    return lines


def _namespaces(raw: bytes) -> tuple[dict[str, str], list[str]]:
    """Prefix -> URI, plus the prefixes that were bound twice.

    `ElementTree` throws prefixes away, and WSDL is the one format in this
    repository whose *attribute values* are QNames: `message="tns:GetOrder"` is
    unresolvable without the mapping. Collected in a separate pass because
    there is no other way to get it.

    The map is flat, so a prefix rebound to a different URI further down the
    document cannot be represented. That is legal XML and vanishingly rare in a
    WSDL, so it is reported rather than modelled -- an inherited mapping that
    is silently wrong resolves references to the wrong schema.
    """
    mapping: dict[str, str] = {}
    rebound: list[str] = []
    for _event, payload in ET.iterparse(io.BytesIO(raw), events=("start-ns",)):
        prefix, uri = payload
        if prefix in mapping and mapping[prefix] != uri:
            if prefix not in rebound:
                rebound.append(prefix)
            continue
        mapping[prefix] = uri
    return mapping, rebound


@dataclass
class _PortTypeOperation:
    name: str
    documentation: str | None
    input_message: QName | None
    output_message: QName | None
    faults: list[tuple[str, QName]] = field(default_factory=list)
    line: int = 0


@dataclass
class _Binding:
    name: str
    port_type: QName | None
    style: str
    transport: str
    soap_version: str
    #: operation name -> {soapAction, style, input_use, output_use}
    operations: dict[str, dict[str, str]] = field(default_factory=dict)


class WsdlParser:
    """Converts a WSDL 1.1 document into a normalized `Service`."""

    def __init__(self, file_label: str) -> None:
        self.file_label = file_label
        self.findings: list[Finding] = []
        self.nsmap: dict[str, str] = {}
        self.lines: dict[int, int] = {}
        self.elements: dict[QName, ET.Element] = {}
        self.types: dict[QName, ET.Element] = {}
        self.messages: dict[QName, list[tuple[str, QName | None, QName | None]]] = {}
        self.port_types: dict[QName, list[_PortTypeOperation]] = {}
        self.bindings: dict[QName, _Binding] = {}

    # ------------------------------------------------------------- plumbing

    def _finding(
        self,
        rule_id: str,
        severity: Severity,
        message: str,
        *,
        line: int = 0,
        hint: str | None = None,
    ) -> None:
        self.findings.append(
            Finding(
                rule_id=rule_id,
                severity=severity,
                message=message,
                location=SourceLocation(file=self.file_label, line=line),
                hint=hint,
            )
        )

    def _unmodelled(self, construct: str, where: str, element: ET.Element | None = None) -> None:
        self._finding(
            "SPEC-WSDL-UNMODELLED",
            Severity.WARN,
            f"`{construct}` on {where} is not carried into the model",
            line=self._line(element),
            hint=(
                "The rest of the contract is compared normally; changes expressed only through "
                "this construct will not be reported. See docs/spec-support.md for the full list."
            ),
        )

    def _line(self, element: ET.Element | None) -> int:
        return self.lines.get(id(element), 0) if element is not None else 0

    def _qname(self, raw: str | None) -> QName | None:
        if not raw:
            return None
        if ":" in raw:
            prefix, local = raw.split(":", 1)
            return (self.nsmap.get(prefix, ""), local)
        return (self.nsmap.get("", ""), raw)

    @staticmethod
    def _text(element: ET.Element | None) -> str | None:
        if element is None or element.text is None:
            return None
        collapsed = " ".join(element.text.split())
        return collapsed or None

    def _documentation(self, element: ET.Element) -> str | None:
        return self._text(element.find(f"{{{NS_WSDL}}}documentation"))

    # ------------------------------------------------------------- the parse

    def parse(self, source: str) -> tuple[Service, list[Finding]]:
        label, raw = read_source(source)
        self.file_label = label

        # Order matters: the DTD refusal happens here, before ElementTree is
        # handed the bytes.
        start_lines = _scan(raw, label)
        self.nsmap, rebound = _namespaces(raw)
        for prefix in rebound:
            self._finding(
                "SPEC-WSDL-PREFIX-REBOUND",
                Severity.WARN,
                f"namespace prefix {prefix or '(default)'!r} is bound to more than one URI",
                hint=(
                    "References resolved with the first binding. Rename one of the prefixes to "
                    "make every QName in the document unambiguous."
                ),
            )

        # Safe here and only here: the DTD refusal above already ran, and
        # external entities are refused by this parser outright.
        root = ET.fromstring(raw.decode("utf-8-sig"))
        if root.tag == f"{{{NS_WSDL20}}}description":
            raise ValueError(
                f"{label!r} is a WSDL 2.0 document. This parser reads WSDL 1.1, which is what "
                "SOAP toolchains emit; 2.0 has a different element vocabulary and would be "
                "read wrong rather than read partially."
            )
        if root.tag != f"{{{NS_WSDL}}}definitions":
            raise ValueError(f"{label!r} has root element {root.tag!r}, expected wsdl:definitions")

        walked = list(root.iter())
        if len(walked) == len(start_lines):
            self.lines = {id(el): line for el, line in zip(walked, start_lines, strict=True)}

        target_ns = root.get("targetNamespace", "")
        self._index_schemas(root)
        self._index_messages(root, target_ns)
        self._index_port_types(root, target_ns)
        self._index_bindings(root, target_ns)

        servers, operations = self._assemble(root, target_ns)

        service = Service(
            title=root.get("name") or self._service_title(root) or "Untitled WSDL document",
            # WSDL 1.1 has no version field. Reporting one would mean inventing
            # it out of the target namespace, and a version this tool made up
            # is a version the semver policy would then rule on.
            version="0",
            protocol=Protocol.SOAP,
            description=self._documentation(root),
            servers=servers,
            operations=operations,
            source_file=label,
            source_location=SourceLocation(file=label, line=self._line(root)),
            bindings={"wsdl": {"target_namespace": target_ns}},
        )
        return service, self.findings

    @staticmethod
    def _service_title(root: ET.Element) -> str | None:
        first = root.find(f"{{{NS_WSDL}}}service")
        return first.get("name") if first is not None else None

    # ------------------------------------------------------------- indexing

    def _index_schemas(self, root: ET.Element) -> None:
        for types_node in root.findall(f"{{{NS_WSDL}}}types"):
            for schema in types_node.findall(f"{{{NS_XSD}}}schema"):
                schema_ns = schema.get("targetNamespace", "")
                for child in schema:
                    name = child.get("name")
                    if child.tag == f"{{{NS_XSD}}}element" and name:
                        self.elements[(schema_ns, name)] = child
                        if child.get("substitutionGroup"):
                            self._unmodelled("substitutionGroup", f"element '{name}'", child)
                    elif child.tag in (f"{{{NS_XSD}}}complexType", f"{{{NS_XSD}}}simpleType"):
                        if name:
                            self.types[(schema_ns, name)] = child
                    elif child.tag in (f"{{{NS_XSD}}}import", f"{{{NS_XSD}}}include"):
                        location = child.get("schemaLocation") or child.get("namespace") or "?"
                        self._finding(
                            "SPEC-WSDL-EXTERNAL-SCHEMA",
                            Severity.WARN,
                            f"schema {child.tag.rsplit('}', 1)[1]} of {location!r} is not followed",
                            line=self._line(child),
                            hint=(
                                "Types defined in that document resolve to nothing here, so the "
                                "differ compares two absences. Inline the schema, or diff the "
                                "documents that carry it separately."
                            ),
                        )
                    elif child.tag in (f"{{{NS_XSD}}}group", f"{{{NS_XSD}}}attributeGroup"):
                        self._unmodelled(
                            child.tag.rsplit("}", 1)[1], f"schema '{schema_ns or '(no target)'}'"
                        )

    def _index_messages(self, root: ET.Element, target_ns: str) -> None:
        for message in root.findall(f"{{{NS_WSDL}}}message"):
            name = message.get("name")
            if not name:
                continue
            parts: list[tuple[str, QName | None, QName | None]] = []
            for part in message.findall(f"{{{NS_WSDL}}}part"):
                part_name = part.get("name") or ""
                parts.append(
                    (part_name, self._qname(part.get("element")), self._qname(part.get("type")))
                )
            self.messages[(target_ns, name)] = parts

    def _index_port_types(self, root: ET.Element, target_ns: str) -> None:
        for port_type in root.findall(f"{{{NS_WSDL}}}portType"):
            name = port_type.get("name")
            if not name:
                continue
            operations: list[_PortTypeOperation] = []
            for op in port_type.findall(f"{{{NS_WSDL}}}operation"):
                op_name = op.get("name")
                if not op_name:
                    continue
                input_node = op.find(f"{{{NS_WSDL}}}input")
                output_node = op.find(f"{{{NS_WSDL}}}output")
                faults: list[tuple[str, QName]] = []
                for fault in op.findall(f"{{{NS_WSDL}}}fault"):
                    fault_message = self._qname(fault.get("message"))
                    if fault_message is not None:
                        faults.append((fault.get("name") or fault_message[1], fault_message))
                operations.append(
                    _PortTypeOperation(
                        name=op_name,
                        documentation=self._documentation(op),
                        input_message=(
                            self._qname(input_node.get("message"))
                            if input_node is not None
                            else None
                        ),
                        output_message=(
                            self._qname(output_node.get("message"))
                            if output_node is not None
                            else None
                        ),
                        faults=faults,
                        line=self._line(op),
                    )
                )
            self.port_types[(target_ns, name)] = operations

    def _index_bindings(self, root: ET.Element, target_ns: str) -> None:
        for binding in root.findall(f"{{{NS_WSDL}}}binding"):
            name = binding.get("name")
            if not name:
                continue
            soap_version = ""
            style = "document"
            transport = ""
            for candidate, version in ((NS_SOAP11, "1.1"), (NS_SOAP12, "1.2")):
                node = binding.find(f"{{{candidate}}}binding")
                if node is not None:
                    soap_version = version
                    style = node.get("style") or "document"
                    transport = node.get("transport") or ""
                    break

            operations: dict[str, dict[str, str]] = {}
            for op in binding.findall(f"{{{NS_WSDL}}}operation"):
                op_name = op.get("name")
                if not op_name:
                    continue
                detail: dict[str, str] = {}
                for candidate in (NS_SOAP11, NS_SOAP12):
                    soap_op = op.find(f"{{{candidate}}}operation")
                    if soap_op is not None:
                        detail["soap_action"] = soap_op.get("soapAction") or ""
                        if soap_op.get("style"):
                            detail["style"] = soap_op.get("style") or ""
                        break
                for direction in ("input", "output"):
                    node = op.find(f"{{{NS_WSDL}}}{direction}")
                    if node is None:
                        continue
                    for candidate in (NS_SOAP11, NS_SOAP12):
                        body = node.find(f"{{{candidate}}}body")
                        if body is not None:
                            detail[f"{direction}_use"] = body.get("use") or "literal"
                            break
                operations[op_name] = detail

            self.bindings[(target_ns, name)] = _Binding(
                name=name,
                port_type=self._qname(binding.get("type")),
                style=style,
                transport=transport,
                soap_version=soap_version,
                operations=operations,
            )

    # ------------------------------------------------------------- assembly

    def _assemble(self, root: ET.Element, target_ns: str) -> tuple[list[Server], list[Operation]]:
        servers: list[Server] = []
        operations: list[Operation] = []
        reached: set[QName] = set()

        ports = list(root.findall(f"{{{NS_WSDL}}}service/{{{NS_WSDL}}}port"))
        for port in ports:
            port_name = port.get("name") or ""
            binding_key = self._qname(port.get("binding"))
            binding = self.bindings.get(binding_key) if binding_key else None
            if binding is None:
                self._finding(
                    "SPEC-WSDL-UNRESOLVED",
                    Severity.ERROR,
                    f"port '{port_name}' names binding {port.get('binding')!r}, "
                    "which this document does not define",
                    line=self._line(port),
                    hint="Its operations are absent from the model, so a diff cannot see them.",
                )
                continue
            if not binding.soap_version:
                self._finding(
                    "SPEC-WSDL-NO-SOAP-BINDING",
                    Severity.WARN,
                    f"port '{port_name}' uses binding '{binding.name}', which declares no "
                    "soap:binding",
                    line=self._line(port),
                    hint=(
                        "HTTP GET/POST and MIME bindings are not modelled; only SOAP ports are "
                        "compiled into operations."
                    ),
                )
                continue

            address = ""
            for candidate in (NS_SOAP11, NS_SOAP12):
                node = port.find(f"{{{candidate}}}address")
                if node is not None:
                    address = node.get("location") or ""
                    break
            if address:
                servers.append(
                    Server(url=address, description=f"{port_name} (SOAP {binding.soap_version})")
                )

            if binding.port_type is None or binding.port_type not in self.port_types:
                self._finding(
                    "SPEC-WSDL-UNRESOLVED",
                    Severity.ERROR,
                    f"binding '{binding.name}' names portType "
                    f"{binding.port_type[1] if binding.port_type else '?'!r}, "
                    "which this document does not define",
                    line=self._line(port),
                )
                continue
            reached.add(binding.port_type)
            operations.extend(
                self._operations_for(binding.port_type, binding, port_name, address, target_ns)
            )

        if not ports:
            # A portType-only WSDL -- an "abstract" interface document, split
            # from its bindings. Common enough in enterprise repositories that
            # producing nothing at all for one would read as a parse failure.
            self._finding(
                "SPEC-WSDL-NO-SERVICE",
                Severity.WARN,
                "the document declares no wsdl:service, so no endpoint address is known",
                line=self._line(root),
                hint=(
                    "Operations were compiled from the portTypes directly, assuming "
                    "document/literal. Diff and breaking rules work; anything needing an "
                    "address does not."
                ),
            )
            for port_type_key in self.port_types:
                reached.add(port_type_key)
                operations.extend(self._operations_for(port_type_key, None, "", "", target_ns))

        for port_type_key in self.port_types:
            if port_type_key not in reached:
                self._finding(
                    "SPEC-WSDL-PORTTYPE-UNBOUND",
                    Severity.WARN,
                    f"portType '{port_type_key[1]}' is reachable from no service port",
                    hint=(
                        "Nothing can call it, so its operations are not in the model. Add a "
                        "binding and a port, or delete the portType."
                    ),
                )
        return servers, operations

    def _operations_for(
        self,
        port_type_key: QName,
        binding: _Binding | None,
        port_name: str,
        address: str,
        target_ns: str,
    ) -> list[Operation]:
        out: list[Operation] = []
        soap_version = binding.soap_version if binding else "1.1"
        media_type = SOAP_MEDIA_TYPE.get(soap_version, "text/xml")
        style = binding.style if binding else "document"

        for op in self.port_types[port_type_key]:
            detail = binding.operations.get(op.name, {}) if binding else {}
            op_style = detail.get("style") or style
            for direction in ("input", "output"):
                if detail.get(f"{direction}_use") == "encoded":
                    self._finding(
                        "SPEC-WSDL-ENCODED",
                        Severity.WARN,
                        f"operation '{op.name}' declares use=\"encoded\" on its {direction}",
                        line=op.line,
                        hint=(
                            "SOAP section-5 encoding puts a graph on the wire that the schema "
                            "does not describe, so the modelled shape is the declared one, not "
                            "the transmitted one. Move to document/literal."
                        ),
                    )

            request = None
            if op.input_message is not None:
                schema = self._message_schema(op.input_message, op_style, op.name, "input")
                if schema is not None:
                    request = RequestBody(required=True, content={media_type: schema})

            responses: list[Response] = []
            if op.output_message is not None:
                schema = self._message_schema(op.output_message, op_style, op.name, "output")
                if schema is not None:
                    responses.append(
                        Response(
                            status="200", description="SOAP response", content={media_type: schema}
                        )
                    )
            for fault_name, fault_message in op.faults:
                schema = self._message_schema(
                    fault_message, op_style, op.name, f"fault {fault_name}"
                )
                responses.append(
                    Response(
                        status=f"fault:{fault_name}",
                        description=f"SOAP fault '{fault_name}' (HTTP {FAULT_HTTP_STATUS})",
                        content={media_type: schema} if schema is not None else {},
                    )
                )

            soap_binding: dict[str, Any] = {
                "style": op_style,
                "soap_version": soap_version,
                "fault_http_status": FAULT_HTTP_STATUS,
            }
            if binding is not None:
                soap_binding["binding"] = binding.name
                soap_binding["transport"] = binding.transport
                soap_binding["over_http"] = binding.transport == HTTP_TRANSPORT
            if "soap_action" in detail:
                # The header a router dispatches on. Changing it is invisible
                # to every schema rule and breaks every caller.
                soap_binding["soap_action"] = detail["soap_action"]
            if port_name:
                soap_binding["port"] = port_name
            if address:
                soap_binding["address"] = address

            out.append(
                Operation(
                    kind=OperationKind.SOAP_OPERATION,
                    operation_id=f"{port_type_key[1]}.{op.name}",
                    rpc_name=op.name,
                    service_name=port_type_key[1],
                    description=op.documentation,
                    request_body=request,
                    responses=responses,
                    bindings={"soap": soap_binding},
                    source_location=SourceLocation(file=self.file_label, line=op.line),
                )
            )
        _ = target_ns
        return out

    # --------------------------------------------------------------- schemas

    def _message_schema(
        self, message_key: QName, style: str, op_name: str, where: str
    ) -> SchemaNode | None:
        parts = self.messages.get(message_key)
        if parts is None:
            self._finding(
                "SPEC-WSDL-UNRESOLVED",
                Severity.ERROR,
                f"operation '{op_name}' names message '{message_key[1]}' for its {where}, "
                "which this document does not define",
                hint="The body shape is absent from the model, so the differ compares nothing.",
            )
            return None
        if not parts:
            return SchemaNode(type="object")

        body = SchemaNode(type="object")
        for part_name, element_key, type_key in parts:
            if element_key is not None:
                element = self.elements.get(element_key)
                if element is None:
                    self._finding(
                        "SPEC-WSDL-UNRESOLVED",
                        Severity.ERROR,
                        f"message '{message_key[1]}' part '{part_name}' names element "
                        f"'{element_key[1]}', which no schema in this document declares",
                    )
                    continue
                name, node, _required = self._element(element, set(), 0)
                # document/literal: the body *is* the element, so the element's
                # own name is the key. rpc/literal wraps parts in an element
                # named for the operation, and the part name is the key.
                key = name if style != "rpc" else part_name
                body.properties[key] = node
                body.required.append(key)
            elif type_key is not None:
                body.properties[part_name] = self._resolve_type(type_key, set(), 0)
                body.required.append(part_name)
            else:
                self._finding(
                    "SPEC-WSDL-UNRESOLVED",
                    Severity.ERROR,
                    f"message '{message_key[1]}' part '{part_name}' names neither an element "
                    "nor a type",
                )
        return body

    def _element(
        self, element: ET.Element, seen: set[QName], depth: int
    ) -> tuple[str, SchemaNode, bool]:
        """One `xs:element` -> (name, schema, required)."""
        ref = self._qname(element.get("ref"))
        if ref is not None:
            target = self.elements.get(ref)
            if target is None:
                self._finding(
                    "SPEC-WSDL-UNRESOLVED",
                    Severity.ERROR,
                    f"element ref '{ref[1]}' names no global element",
                    line=self._line(element),
                )
                return ref[1], SchemaNode(), False
            name, node, _required = self._element(target, seen, depth + 1)
        else:
            name = element.get("name") or ""
            node = self._element_type(element, seen, depth)

        if element.get("nillable") == "true":
            node.nullable = True
        documentation = self._annotation(element)
        if documentation and not node.description:
            node.description = documentation
        if element.get("default") is not None:
            node.default = element.get("default")
        if element.get("fixed") is not None:
            node.const = element.get("fixed")

        min_occurs = _as_int(element.get("minOccurs"), 1)
        if min_occurs is None:  # unreachable with a non-None default; mypy cannot see that
            min_occurs = 1
        raw_max = element.get("maxOccurs", "1")
        if raw_max != "1":
            max_items = None if raw_max == "unbounded" else _as_int(raw_max, None)
            node = SchemaNode(
                type="array", items=node, min_items=min_occurs or None, max_items=max_items
            )
        return name, node, min_occurs > 0

    def _annotation(self, element: ET.Element) -> str | None:
        annotation = element.find(f"{{{NS_XSD}}}annotation/{{{NS_XSD}}}documentation")
        return self._text(annotation)

    def _element_type(self, element: ET.Element, seen: set[QName], depth: int) -> SchemaNode:
        inline_complex = element.find(f"{{{NS_XSD}}}complexType")
        if inline_complex is not None:
            return self._complex_type(inline_complex, seen, depth + 1)
        inline_simple = element.find(f"{{{NS_XSD}}}simpleType")
        if inline_simple is not None:
            return self._simple_type(inline_simple, seen, depth + 1)
        type_key = self._qname(element.get("type"))
        if type_key is None:
            return SchemaNode()
        return self._resolve_type(type_key, seen, depth + 1)

    def _resolve_type(self, type_key: QName, seen: set[QName], depth: int) -> SchemaNode:
        if type_key[0] == NS_XSD:
            builtin = XSD_PRIMITIVES.get(type_key[1])
            if builtin is None:
                self._unmodelled(f"xs:{type_key[1]}", "a type reference")
                return SchemaNode()
            return SchemaNode(type=builtin[0], format=builtin[1])
        if depth > MAX_DEPTH or type_key in seen:
            # A recursive type. Named rather than expanded: the alternative is
            # a tree that does not terminate, and a truncated tree that says
            # which type it stopped at is readable.
            return SchemaNode(
                title=type_key[1], description=f"recursive reference to {type_key[1]}"
            )
        definition = self.types.get(type_key)
        if definition is None:
            self._finding(
                "SPEC-WSDL-UNRESOLVED",
                Severity.ERROR,
                f"type '{type_key[1]}' is referenced and defined nowhere in this document",
                hint=(
                    "Everything at that position is absent from the model, so the differ "
                    "compares two absences and reports no change."
                ),
            )
            return SchemaNode()
        nested = seen | {type_key}
        if definition.tag == f"{{{NS_XSD}}}simpleType":
            node = self._simple_type(definition, nested, depth + 1)
        else:
            node = self._complex_type(definition, nested, depth + 1)
        if not node.title:
            node.title = type_key[1]
        return node

    def _complex_type(self, node: ET.Element, seen: set[QName], depth: int) -> SchemaNode:
        schema = SchemaNode(type="object")
        documentation = self._annotation(node)
        if documentation:
            schema.description = documentation
        if node.get("abstract") == "true":
            self._unmodelled("abstract", f"complexType '{node.get('name') or '(inline)'}'", node)

        complex_content = node.find(f"{{{NS_XSD}}}complexContent")
        simple_content = node.find(f"{{{NS_XSD}}}simpleContent")
        if complex_content is not None:
            extension = complex_content.find(f"{{{NS_XSD}}}extension")
            if extension is None:
                self._unmodelled(
                    "complexContent/restriction",
                    f"complexType '{node.get('name') or '(inline)'}'",
                    node,
                )
                return schema
            base = self._qname(extension.get("base"))
            if base is not None:
                inherited = self._resolve_type(base, seen, depth + 1)
                schema.properties.update(inherited.properties)
                schema.required.extend(inherited.required)
                schema.oneofs.update(inherited.oneofs)
            self._content(extension, schema, seen, depth)
            self._attributes(extension, schema, seen, depth)
            return schema
        if simple_content is not None:
            extension = simple_content.find(f"{{{NS_XSD}}}extension")
            if extension is None:
                self._unmodelled(
                    "simpleContent/restriction",
                    f"complexType '{node.get('name') or '(inline)'}'",
                    node,
                )
                return schema
            base = self._qname(extension.get("base"))
            if base is not None:
                value = self._resolve_type(base, seen, depth + 1)
                # An element with attributes *and* text content. The text is
                # the value; the attributes hang off it. Modelled as an object
                # with a `#text` member, which is the convention every
                # XML-to-JSON mapping in this space uses.
                schema.properties["#text"] = value
                schema.required.append("#text")
            self._attributes(extension, schema, seen, depth)
            return schema

        self._content(node, schema, seen, depth)
        self._attributes(node, schema, seen, depth)
        return schema

    def _content(
        self, parent: ET.Element, schema: SchemaNode, seen: set[QName], depth: int
    ) -> None:
        """Every content particle directly under a complexType or extension."""
        for child in parent:
            if _local(child.tag) in _PARTICLE_TAGS:
                self._particle(child, schema, seen, depth + 1, exclusive=None)

    def _particle(
        self,
        node: ET.Element,
        schema: SchemaNode,
        seen: set[QName],
        depth: int,
        *,
        exclusive: str | None,
    ) -> None:
        """One content particle, flattened into `schema`.

        XSD nests particles arbitrarily and the model is flat, so a
        `sequence` inside a `sequence` contributes its members to the same
        object. The one thing that is not flattened away is exclusivity.
        """
        if depth > MAX_DEPTH:
            return
        tag = _local(node.tag)
        if tag in ("sequence", "all"):
            for child in node:
                self._particle(child, schema, seen, depth + 1, exclusive=exclusive)
        elif tag == "choice":
            # `xs:choice` is exactly-one-of, which the model already has a name
            # for: `oneofs`, put there for protobuf. The members are carried as
            # optional properties and the exclusivity is carried alongside, so
            # a field moving into or out of the choice is a change the rules
            # can see rather than a rename they cannot.
            label = "choice" if not schema.oneofs else f"choice{len(schema.oneofs) + 1}"
            before = set(schema.properties)
            for child in node:
                self._particle(child, schema, seen, depth + 1, exclusive=label)
            added = [name for name in schema.properties if name not in before]
            if added:
                schema.oneofs[label] = added
        elif tag == "element":
            name, member, required = self._element(node, seen, depth + 1)
            if not name:
                return
            schema.properties[name] = member
            if required and exclusive is None:
                schema.required.append(name)
        elif tag == "any":
            # `xs:any` is "anything else may appear here", which is what
            # `additionalProperties: true` says.
            schema.additional_properties = True
        elif tag == "group":
            self._unmodelled("xs:group", "a model group", node)

    def _attributes(
        self, parent: ET.Element, schema: SchemaNode, seen: set[QName], depth: int
    ) -> None:
        for attribute in parent.findall(f"{{{NS_XSD}}}attribute"):
            name = attribute.get("name") or (self._qname(attribute.get("ref")) or ("", ""))[1]
            if not name:
                continue
            # `@` prefixed, because an XML element name cannot start with one:
            # the convention is unambiguous, and it keeps an attribute and a
            # child element of the same name from colliding in one dict.
            key = f"@{name}"
            inline = attribute.find(f"{{{NS_XSD}}}simpleType")
            if inline is not None:
                node = self._simple_type(inline, seen, depth + 1)
            else:
                type_key = self._qname(attribute.get("type"))
                node = self._resolve_type(type_key, seen, depth + 1) if type_key else SchemaNode()
            if attribute.get("fixed") is not None:
                node.const = attribute.get("fixed")
            if attribute.get("default") is not None:
                node.default = attribute.get("default")
            schema.properties[key] = node
            if attribute.get("use") == "required":
                schema.required.append(key)
        if parent.find(f"{{{NS_XSD}}}anyAttribute") is not None:
            schema.additional_properties = True
        for group in parent.findall(f"{{{NS_XSD}}}attributeGroup"):
            self._unmodelled("xs:attributeGroup", "a complexType", group)

    def _simple_type(self, node: ET.Element, seen: set[QName], depth: int) -> SchemaNode:
        union = node.find(f"{{{NS_XSD}}}union")
        if union is not None:
            self._unmodelled("xs:union", f"simpleType '{node.get('name') or '(inline)'}'", node)
            return SchemaNode()
        listed = node.find(f"{{{NS_XSD}}}list")
        if listed is not None:
            self._unmodelled("xs:list", f"simpleType '{node.get('name') or '(inline)'}'", node)
            return SchemaNode()

        restriction = node.find(f"{{{NS_XSD}}}restriction")
        if restriction is None:
            return SchemaNode()
        base = self._qname(restriction.get("base"))
        schema = self._resolve_type(base, seen, depth + 1) if base else SchemaNode()
        documentation = self._annotation(node)
        if documentation:
            schema.description = documentation

        enum = [child.get("value") for child in restriction.findall(f"{{{NS_XSD}}}enumeration")]
        if enum:
            schema.enum = [value for value in enum if value is not None]
        for facet in restriction:
            local = facet.tag.rsplit("}", 1)[1]
            value = facet.get("value")
            if value is None:
                continue
            _apply_facet(schema, local, value)
        return schema


def _as_int(raw: str | None, default: int | None) -> int | None:
    try:
        return int(raw) if raw is not None else default
    except ValueError:
        return default


def _apply_facet(schema: SchemaNode, facet: str, value: str) -> None:
    """One XSD facet onto the model, where the model has a place for it."""
    if facet == "length":
        schema.min_length = schema.max_length = _as_int(value, None)
    elif facet == "minLength":
        schema.min_length = _as_int(value, None)
    elif facet == "maxLength":
        schema.max_length = _as_int(value, None)
    elif facet == "pattern":
        schema.pattern = value
    elif facet in ("minInclusive", "maxInclusive", "minExclusive", "maxExclusive"):
        try:
            number = float(value)
        except ValueError:
            return
        setattr(
            schema,
            {
                "minInclusive": "minimum",
                "maxInclusive": "maximum",
                "minExclusive": "exclusive_minimum",
                "maxExclusive": "exclusive_maximum",
            }[facet],
            number,
        )
    # `whiteSpace`, `totalDigits` and `fractionDigits` have no model field. The
    # first is a normalization directive rather than a constraint on the value
    # set; the other two are recorded in docs/spec-support.md as unmodelled
    # rather than approximated by a `pattern` this parser invented.


def load_wsdl(source: str) -> tuple[Service, list[Finding]]:
    return WsdlParser(source).parse(source)


class WsdlSpecPlugin(SpecPlugin):
    """WSDL 1.1 / SOAP."""

    spec_format = "wsdl"

    def protocol(self) -> Protocol:
        return Protocol.SOAP

    def detect(self, source: str, raw: bytes | None = None) -> bool:
        if raw is None:
            return source.endswith(".wsdl")
        text = raw.decode("utf-8-sig", errors="replace")
        # The namespace URI, not the file extension and not the word "wsdl":
        # a document that declares it *is* a WSDL 1.1 definitions document, and
        # one that does not is not, whatever it is called.
        return NS_WSDL in text and "definitions" in text

    def load(self, source: str) -> tuple[Service, list[Finding]]:
        return load_wsdl(source)


__all__ = [
    "WsdlDoctypeError",
    "WsdlParser",
    "WsdlSpecPlugin",
    "load_wsdl",
]
