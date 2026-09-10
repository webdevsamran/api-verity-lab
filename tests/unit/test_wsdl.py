"""SOAP, which is the format nobody demos and everybody still runs.

Three things are being tested here and only one of them is "does it parse".

The first is the **security boundary**. A WSDL arrives from a partner, a
registry, or a URL somebody pasted, and `xml.etree.ElementTree` on this Python
expands internal entities -- the billion-laughs shape -- while refusing
external ones. Both halves of that are asserted by running them rather than
quoted from a changelog, so the day a Python release changes either one, this
file fails instead of the claim in the module docstring quietly becoming false.

The second is **what the model does not carry**. Every XSD construct the
normalized model has no place for emits a finding naming it. That is the
difference between a contract that is partly compared and a contract that is
partly compared *and says so* -- and this project has already found four rules
that were published and unreachable, which is the same failure wearing a
different hat.

The third is the **three SOAP facts no schema rule can see**: SOAPAction, the
binding style, and the SOAP version. Each leaves every message schema byte
for byte identical while breaking every generated stub, so a diff that only
compared schemas would report a clean run.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from apiverity.core.model import OperationKind, Protocol
from apiverity.diff.engine import diff_services
from apiverity.rules.alternatives import alternative_for
from apiverity.rules.breaking import CATALOG, evaluate_breaking
from apiverity.specs.loader import SPEC_FORMATS, detect_and_load
from apiverity.specs.wsdl import WsdlDoctypeError, WsdlSpecPlugin, load_wsdl

_ROOT = Path(__file__).resolve().parents[2]
_FIXTURES = _ROOT / "fixtures" / "wsdl"
_V1 = _FIXTURES / "orders-v1.wsdl"
_V2 = _FIXTURES / "orders-v2.wsdl"

_ENVELOPE = """<?xml version="1.0"?>
<wsdl:definitions name="{name}" targetNamespace="urn:t"
    xmlns:tns="urn:t"
    xmlns:xs="http://www.w3.org/2001/XMLSchema"
    xmlns:wsdl="http://schemas.xmlsoap.org/wsdl/"
    xmlns:soap="http://schemas.xmlsoap.org/wsdl/soap/">
{body}
</wsdl:definitions>
"""


def _write(tmp_path: Path, body: str, name: str = "T") -> str:
    path = tmp_path / "service.wsdl"
    path.write_text(_ENVELOPE.format(name=name, body=body), encoding="utf-8")
    return str(path)


def _ids(findings: object) -> list[str]:
    return [f.rule_id for f in findings]  # type: ignore[union-attr]


# ------------------------------------------------------------------ security


def test_a_document_declaring_a_doctype_is_refused_before_anything_expands(
    tmp_path: Path,
) -> None:
    """The billion-laughs shape, in the format most likely to arrive from a
    third party."""
    laughs = (
        '<?xml version="1.0"?>\n'
        "<!DOCTYPE definitions [\n"
        '  <!ENTITY a "lol">\n'
        '  <!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">\n'
        '  <!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">\n'
        "]>\n"
        '<wsdl:definitions xmlns:wsdl="http://schemas.xmlsoap.org/wsdl/" name="&c;"/>\n'
    )
    path = tmp_path / "laughs.wsdl"
    path.write_text(laughs, encoding="utf-8")
    with pytest.raises(WsdlDoctypeError) as excinfo:
        load_wsdl(str(path))
    assert "DOCTYPE" in str(excinfo.value)


def test_internal_entity_expansion_really_does_happen_in_this_runtime() -> None:
    """The reason the guard above exists, asserted rather than assumed.

    If a future Python stops expanding internal entities, this test fails and
    the module docstring's claim can be corrected -- which is better than the
    guard quietly becoming folklore nobody can justify.
    """
    doc = (
        '<?xml version="1.0"?>\n'
        '<!DOCTYPE r [<!ENTITY a "lol"><!ENTITY b "&a;&a;&a;">]>\n'
        "<r>&b;</r>\n"
    )
    root = ET.fromstring(doc)
    assert root.text == "lollollol"


def test_external_entities_are_refused_by_this_runtime() -> None:
    """The other half. An external entity naming a local file must not be
    read; this is the XXE case, and it is the half that is already safe."""
    doc = (
        '<?xml version="1.0"?>\n'
        '<!DOCTYPE r [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>\n'
        "<r>&xxe;</r>\n"
    )
    with pytest.raises(ET.ParseError) as excinfo:
        ET.fromstring(doc)
    assert "undefined entity" in str(excinfo.value)


# ----------------------------------------------------------------- the shape


def test_the_plugin_is_reachable_by_name_and_by_sniffing() -> None:
    assert "wsdl" in SPEC_FORMATS
    service, _findings, plugin = detect_and_load(str(_V1))
    assert isinstance(plugin, WsdlSpecPlugin)
    assert service.protocol is Protocol.SOAP


def test_detection_keys_on_the_namespace_not_the_file_extension() -> None:
    """A `.wsdl` suffix is a convention; the namespace URI is the fact."""
    plugin = WsdlSpecPlugin()
    assert plugin.detect("anything.xml", _V1.read_bytes())
    assert not plugin.detect("x.xml", b"<html><body>definitions</body></html>")


def test_operations_are_keyed_by_porttype_and_name() -> None:
    """Not by method and path: every operation on a port shares one URL and
    one verb, so keying on those would collapse the service into one entry."""
    service, _findings, _plugin = detect_and_load(str(_V1))
    assert service.operation_keys() == [
        "OrderPort.GetOrder",
        "OrderPort.PlaceOrder",
        "OrderPort.CancelOrder",
    ]
    assert all(op.kind is OperationKind.SOAP_OPERATION for op in service.operations)
    assert all(op.method is None and op.path is None for op in service.operations)


def test_the_endpoint_address_becomes_a_server() -> None:
    service, _findings, _plugin = detect_and_load(str(_V1))
    assert [s.url for s in service.servers] == ["https://orders.example.com/soap"]


def test_the_soap_facts_a_schema_rule_cannot_see_are_carried() -> None:
    service, _findings, _plugin = detect_and_load(str(_V1))
    soap = service.find_operation("OrderPort.GetOrder").bindings["soap"]  # type: ignore[union-attr]
    assert soap["soap_action"] == "urn:verity:orders/GetOrder"
    assert soap["style"] == "document"
    assert soap["soap_version"] == "1.1"
    assert soap["over_http"] is True
    assert soap["fault_http_status"] == 500


def test_a_fault_is_keyed_by_its_name_not_by_http_500() -> None:
    """Every fault on an operation comes back as HTTP 500, so keying responses
    by status would silently merge all of them into one."""
    service, _findings, _plugin = detect_and_load(str(_V1))
    place = service.find_operation("OrderPort.PlaceOrder")
    assert place is not None
    statuses = [r.status for r in place.responses]
    assert statuses == ["200", "fault:OrderRejected", "fault:CustomerUnknown"]


# ----------------------------------------------------------------- XSD subset


def _place_order_body(path: Path = _V1):  # type: ignore[no-untyped-def]
    service, _findings, _plugin = detect_and_load(str(path))
    op = service.find_operation("OrderPort.PlaceOrder")
    assert op is not None and op.request_body is not None
    return op.request_body.content["text/xml"].properties["PlaceOrderRequest"]


def test_a_choice_becomes_a_oneof_rather_than_two_optional_fields() -> None:
    """`xs:choice` is exactly-one-of, which the model already has a word for.
    Carrying the members as plain optional properties would lose the
    exclusivity -- the silent narrowing this parser exists to avoid."""
    body = _place_order_body()
    assert body.oneofs == {"choice": ["shipToAddress", "pickUpLocation"]}
    assert "shipToAddress" not in body.required
    assert "pickUpLocation" not in body.required


def test_complex_content_extension_merges_the_base_type() -> None:
    """A `Customer` extending `Party` has the base's fields too, or every
    inherited field reads as absent."""
    customer = _place_order_body().properties["customer"]
    assert list(customer.properties) == ["name", "customerId", "loyaltyTier"]
    assert customer.required == ["name", "customerId"]


def test_an_unbounded_element_becomes_an_array() -> None:
    items = _place_order_body().properties["items"]
    assert items.type == "array"
    assert items.min_items == 1
    assert items.max_items is None
    assert list(items.items.properties) == ["sku", "quantity", "price", "note"]


def test_attributes_are_carried_under_an_at_prefix() -> None:
    """An XML element name cannot begin with `@`, so the convention cannot
    collide with a child element of the same name."""
    money = _place_order_body().properties["items"].items.properties["price"]
    assert money.properties["@scale"].type == "integer"
    assert "@scale" in money.required


def test_nillable_becomes_nullable_and_min_occurs_zero_becomes_optional() -> None:
    line_item = _place_order_body().properties["items"].items
    assert line_item.properties["note"].nullable is True
    assert "note" not in line_item.required


def test_restriction_facets_and_enumerations_reach_the_model() -> None:
    service, _findings, _plugin = detect_and_load(str(_V1))
    get_order = service.find_operation("OrderPort.GetOrder")
    assert get_order is not None and get_order.request_body is not None
    order_id = (
        get_order.request_body.content["text/xml"]
        .properties["GetOrderRequest"]
        .properties["orderId"]
    )
    assert order_id.type == "string"
    assert (order_id.min_length, order_id.max_length) == (6, 32)
    assert order_id.pattern == "ORD-[0-9]+"
    assert order_id.description == "An order reference, as printed on the invoice."

    order = get_order.responses[0].content["text/xml"]
    status = order.properties["GetOrderResponse"].properties["order"].properties["status"]
    assert status.enum == ["PLACED", "SHIPPED", "DELIVERED", "CANCELLED"]


def test_a_recursive_type_terminates_and_names_where_it_stopped(tmp_path: Path) -> None:
    """A type that references itself is a tree that does not terminate. A
    truncated one that says which type it stopped at is readable; a
    RecursionError is not."""
    body = """
  <wsdl:types>
    <xs:schema targetNamespace="urn:t" xmlns:tns="urn:t">
      <xs:complexType name="Node">
        <xs:sequence>
          <xs:element name="label" type="xs:string"/>
          <xs:element name="child" type="tns:Node" minOccurs="0"/>
        </xs:sequence>
      </xs:complexType>
      <xs:element name="Req"><xs:complexType><xs:sequence>
        <xs:element name="root" type="tns:Node"/>
      </xs:sequence></xs:complexType></xs:element>
    </xs:schema>
  </wsdl:types>
  <wsdl:message name="In"><wsdl:part name="p" element="tns:Req"/></wsdl:message>
  <wsdl:portType name="P">
    <wsdl:operation name="Go"><wsdl:input message="tns:In"/></wsdl:operation>
  </wsdl:portType>
"""
    service, _findings = load_wsdl(_write(tmp_path, body))
    node = (
        service.operations[0]
        .request_body.content["text/xml"]
        .properties["Req"]
        .properties[  # type: ignore[union-attr]
            "root"
        ]
    )
    assert list(node.properties) == ["label", "child"]
    assert "recursive reference to Node" in (node.properties["child"].description or "")


# ------------------------------------------------- what is deliberately absent


def test_an_unmodelled_construct_is_named_rather_than_dropped(tmp_path: Path) -> None:
    """A dropped keyword does not fail, it narrows what the contract says
    without telling anyone. Being told is the whole difference."""
    body = """
  <wsdl:types>
    <xs:schema targetNamespace="urn:t" xmlns:tns="urn:t">
      <xs:simpleType name="Weird">
        <xs:union memberTypes="xs:string xs:int"/>
      </xs:simpleType>
      <xs:element name="Req"><xs:complexType><xs:sequence>
        <xs:element name="odd" type="tns:Weird"/>
      </xs:sequence></xs:complexType></xs:element>
    </xs:schema>
  </wsdl:types>
  <wsdl:message name="In"><wsdl:part name="p" element="tns:Req"/></wsdl:message>
  <wsdl:portType name="P">
    <wsdl:operation name="Go"><wsdl:input message="tns:In"/></wsdl:operation>
  </wsdl:portType>
"""
    _service, findings = load_wsdl(_write(tmp_path, body))
    unmodelled = [f for f in findings if f.rule_id == "SPEC-WSDL-UNMODELLED"]
    assert unmodelled, _ids(findings)
    assert "xs:union" in unmodelled[0].message


def test_a_reference_to_nothing_is_an_error_not_a_silent_absence(tmp_path: Path) -> None:
    """The failure mode `$ref` bundling was built for: an unresolved reference
    leaves the differ comparing two absences and reporting no change."""
    body = """
  <wsdl:message name="In"><wsdl:part name="p" element="tns:Missing"/></wsdl:message>
  <wsdl:portType name="P">
    <wsdl:operation name="Go"><wsdl:input message="tns:In"/></wsdl:operation>
  </wsdl:portType>
"""
    _service, findings = load_wsdl(_write(tmp_path, body))
    assert "SPEC-WSDL-UNRESOLVED" in _ids(findings)


def test_a_porttype_only_document_still_produces_operations(tmp_path: Path) -> None:
    """An abstract interface document, split from its bindings, is a normal
    enterprise shape. Producing nothing for one would read as a parse
    failure."""
    body = """
  <wsdl:message name="In"><wsdl:part name="p" type="xs:string"/></wsdl:message>
  <wsdl:portType name="P">
    <wsdl:operation name="Go"><wsdl:input message="tns:In"/></wsdl:operation>
  </wsdl:portType>
"""
    service, findings = load_wsdl(_write(tmp_path, body))
    assert service.operation_keys() == ["P.Go"]
    assert "SPEC-WSDL-NO-SERVICE" in _ids(findings)


def test_a_porttype_no_port_reaches_is_reported_not_quietly_included(tmp_path: Path) -> None:
    body = """
  <wsdl:message name="In"><wsdl:part name="p" type="xs:string"/></wsdl:message>
  <wsdl:portType name="Live">
    <wsdl:operation name="Go"><wsdl:input message="tns:In"/></wsdl:operation>
  </wsdl:portType>
  <wsdl:portType name="Orphan">
    <wsdl:operation name="Nope"><wsdl:input message="tns:In"/></wsdl:operation>
  </wsdl:portType>
  <wsdl:binding name="B" type="tns:Live">
    <soap:binding style="document" transport="http://schemas.xmlsoap.org/soap/http"/>
    <wsdl:operation name="Go"><soap:operation soapAction="urn:go"/></wsdl:operation>
  </wsdl:binding>
  <wsdl:service name="S">
    <wsdl:port name="Port" binding="tns:B">
      <soap:address location="https://example.test/soap"/>
    </wsdl:port>
  </wsdl:service>
"""
    service, findings = load_wsdl(_write(tmp_path, body))
    assert service.operation_keys() == ["Live.Go"]
    assert "SPEC-WSDL-PORTTYPE-UNBOUND" in _ids(findings)


def test_wsdl_2_is_refused_by_name_rather_than_read_wrong(tmp_path: Path) -> None:
    doc = (
        '<?xml version="1.0"?>\n'
        '<description xmlns="http://www.w3.org/ns/wsdl" targetNamespace="urn:t"/>\n'
    )
    path = tmp_path / "two.wsdl"
    path.write_text(doc, encoding="utf-8")
    with pytest.raises(ValueError, match=r"WSDL 2\.0"):
        load_wsdl(str(path))


def test_findings_carry_a_real_line_number() -> None:
    """`ElementTree` exposes no position at all, so the number comes from a
    second expat pass paired by document order. A wrong line is worse than
    none, which is why this is pinned to the fixture."""
    service, _findings, _plugin = detect_and_load(str(_V1))
    place = service.find_operation("OrderPort.PlaceOrder")
    assert place is not None and place.source_location is not None
    line = place.source_location.line
    source = _V1.read_text(encoding="utf-8").splitlines()
    assert 'name="PlaceOrder"' in source[line - 1]


# ------------------------------------------------------- diff, end to end


def _breaking(old: Path, new: Path) -> list[str]:
    old_service, _f1, _p1 = detect_and_load(str(old))
    new_service, _f2, _p2 = detect_and_load(str(new))
    changes = diff_services(old_service, new_service)
    return _ids(evaluate_breaking(changes))


def test_the_shared_rules_fire_over_a_soap_contract() -> None:
    """The point of a normalized model: the catalogue was not extended to make
    these work, they simply apply."""
    fired = _breaking(_V1, _V2)
    for rule in (
        "BRK-RPC-REMOVED",
        "BRK-CONSTRAINT-TIGHTENED",
        "BRK-RESP-FIELD-REMOVED",
        "BRK-ENUM-NARROWED-RESPONSE",
        "BRK-REQ-FIELD-ADDED-REQUIRED",
        "BRK-RESP-STATUS-REMOVED",
    ):
        assert rule in fired, f"{rule} did not fire; got {sorted(set(fired))}"


def test_a_changed_soap_action_is_caught_though_every_schema_is_identical() -> None:
    """`GetOrder`'s messages are byte for byte the same in both fixtures. Only
    the header a gateway routes on moved."""
    assert "BRK-SOAP-ACTION-CHANGED" in _breaking(_V1, _V2)


@pytest.mark.parametrize(
    "rule_id",
    ["BRK-SOAP-ACTION-CHANGED", "BRK-SOAP-STYLE-CHANGED", "BRK-SOAP-VERSION-CHANGED"],
)
def test_each_soap_rule_is_catalogued_and_says_what_to_ship_instead(rule_id: str) -> None:
    assert rule_id in CATALOG
    assert alternative_for(rule_id)


def test_style_and_version_changes_fire(tmp_path: Path) -> None:
    """Neither is expressible by editing the fixtures without also changing
    every message, so they get a minimal pair of their own."""
    template = """
  <wsdl:message name="In"><wsdl:part name="p" type="xs:string"/></wsdl:message>
  <wsdl:portType name="P">
    <wsdl:operation name="Go"><wsdl:input message="tns:In"/></wsdl:operation>
  </wsdl:portType>
  <wsdl:binding name="B" type="tns:P">
    <{ns}:binding style="{style}" transport="http://schemas.xmlsoap.org/soap/http"/>
    <wsdl:operation name="Go"><{ns}:operation soapAction="urn:go"/></wsdl:operation>
  </wsdl:binding>
  <wsdl:service name="S">
    <wsdl:port name="Port" binding="tns:B">
      <{ns}:address location="https://example.test/soap"/>
    </wsdl:port>
  </wsdl:service>
"""
    envelope = _ENVELOPE.replace(
        'xmlns:soap="http://schemas.xmlsoap.org/wsdl/soap/"',
        'xmlns:soap="http://schemas.xmlsoap.org/wsdl/soap/"\n'
        '    xmlns:soap12="http://schemas.xmlsoap.org/wsdl/soap12/"',
    )
    old_path = tmp_path / "old.wsdl"
    new_path = tmp_path / "new.wsdl"
    old_path.write_text(
        envelope.format(name="T", body=template.format(ns="soap", style="document")),
        encoding="utf-8",
    )
    new_path.write_text(
        envelope.format(name="T", body=template.format(ns="soap12", style="rpc")),
        encoding="utf-8",
    )
    fired = _breaking(old_path, new_path)
    assert "BRK-SOAP-STYLE-CHANGED" in fired
    assert "BRK-SOAP-VERSION-CHANGED" in fired
