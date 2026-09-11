"""Personal data, found by shape, and never reported by value.

`leakage.py` finds credentials in what a service returns. This is the other
category, and it needs a different rule for what counts, because the failure
modes are opposite: a leaked credential is always wrong, and a returned email
address is usually the entire point of the endpoint.

## What is a finding, and what is not

**Not a finding:** an API returning personal data. `GET /users/{id}` returning
an email is the endpoint working. A check that fired on that would produce
hundreds of findings per contract, and `security/hardening.py` already records
why that is fatal — the check gets switched off, taking the useful ones with
it.

**A finding:** personal data the *contract does not say is there*. The document
declares `nickname: string`; the service returns an email address. Either the
contract is wrong about what it returns, or the service is returning something
it should not. Both are worth a person's attention, and neither is visible
without comparing the two.

**Always redacted:** personal data on its way into a file. A corpus is
something people commit. `docs/privacy.md` says response bodies do not reach an
artifact unasked; this is what makes that true for the fields no credential
pattern matches.

## Shapes, not guesses

Every detector here either verifies a checksum or matches a structure with no
plausible alternative reading:

* **Credit card** — Luhn. A sixteen-digit number that fails Luhn is an order
  reference.
* **IBAN** — mod-97. Same reason.
* **Email** — a structure nothing else uses.
* **IPv4 / IPv6** — parsed, not pattern-matched, so `999.1.1.1` is not an
  address.

## What is deliberately not detected

Names, street addresses, dates of birth, free-text notes.

They have no shape. "Paris" is a city and a person; `1990-03-14` is a birthday
and a release date; any string at all can be a name. A detector for them is a
detector that is wrong most of the time, and a check that is wrong most of the
time trains people to ignore the times it is right — which is the one thing a
privacy check cannot afford.

That absence is stated rather than left to be discovered, and it is the reason
the field-name rules in `traffic/redact.py` still matter: a field *called*
`date_of_birth` is redactable by name even though its value is not
recognisable.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from typing import Any

#: The value this replaces personal data with. Distinct from the credential
#: replacement, so a reader of a redacted corpus can tell which rule fired.
REPLACEMENT = "[PII]"

_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_IPV6 = re.compile(r"\b(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4}\b")
#: Thirteen to nineteen digits, optionally grouped. Checked with Luhn before
#: it counts, so an order reference of the same length is not a card.
_CARD = re.compile(r"\b(?:\d[ -]?){12,18}\d\b")
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b")

#: The longest thing this will look at. A megabyte of base64 is not personal
#: data and scanning it is the check becoming the slow part of the run.
MAX_SCAN = 64 * 1024


def luhn(digits: str) -> bool:
    """The checksum every card number carries, and an order id does not."""
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = int(char)
        if index % 2:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0 and len(digits) >= 13


def iban_valid(candidate: str) -> bool:
    """ISO 13616 mod-97. Without it `GB00` anything is an account number."""
    rearranged = candidate[4:] + candidate[:4]
    converted = "".join(str(ord(c) - 55) if c.isalpha() else c for c in rearranged.upper())
    if not converted.isdigit():
        return False
    return int(converted) % 97 == 1


@dataclass(frozen=True)
class Hit:
    """One piece of personal data, described without being quoted."""

    kind: str
    #: Where it was, as a dotted path. Empty at the root.
    pointer: str
    #: How long the value was. Enough to confirm a report, useless as a leak.
    length: int

    def describe(self) -> str:
        return f"{self.kind} at {self.pointer or '(root)'}"


def scan_text(text: str, pointer: str = "") -> list[Hit]:
    """Personal data in one string."""
    if not text or len(text) > MAX_SCAN:
        return []
    hits: list[Hit] = []

    for match in _EMAIL.finditer(text):
        hits.append(Hit("email address", pointer, len(match.group(0))))

    for match in _IPV4.finditer(text):
        try:
            ipaddress.IPv4Address(match.group(0))
        except ValueError:
            continue  # `999.1.1.1` is a version string, not an address
        hits.append(Hit("IP address", pointer, len(match.group(0))))

    for match in _IPV6.finditer(text):
        candidate = match.group(0)
        if candidate.count(":") < 2:
            continue
        try:
            ipaddress.IPv6Address(candidate)
        except ValueError:
            continue
        hits.append(Hit("IP address", pointer, len(candidate)))

    for match in _CARD.finditer(text):
        digits = re.sub(r"[ -]", "", match.group(0))
        if luhn(digits):
            hits.append(Hit("payment card number", pointer, len(digits)))

    for match in _IBAN.finditer(text):
        if iban_valid(match.group(0)):
            hits.append(Hit("bank account number (IBAN)", pointer, len(match.group(0))))

    return hits


def scan(value: Any, pointer: str = "", depth: int = 0) -> list[Hit]:
    """Personal data anywhere in a structure."""
    if depth > 24:
        return []
    if isinstance(value, str):
        return scan_text(value, pointer)
    if isinstance(value, dict):
        out: list[Hit] = []
        for key, child in value.items():
            out.extend(scan(child, f"{pointer}.{key}" if pointer else str(key), depth + 1))
        return out
    if isinstance(value, list):
        out = []
        for index, child in enumerate(value):
            out.extend(scan(child, f"{pointer}[{index}]", depth + 1))
        return out
    return []


def redact_text(text: str) -> str:
    """The same string with every recognised value replaced."""
    if not text or len(text) > MAX_SCAN:
        return text
    text = _EMAIL.sub(REPLACEMENT, text)

    def _ip4(match: re.Match[str]) -> str:
        try:
            ipaddress.IPv4Address(match.group(0))
        except ValueError:
            return match.group(0)
        return REPLACEMENT

    text = _IPV4.sub(_ip4, text)

    def _ip6(match: re.Match[str]) -> str:
        candidate = match.group(0)
        if candidate.count(":") < 2:
            return candidate
        try:
            ipaddress.IPv6Address(candidate)
        except ValueError:
            return candidate
        return REPLACEMENT

    text = _IPV6.sub(_ip6, text)

    def _card(match: re.Match[str]) -> str:
        digits = re.sub(r"[ -]", "", match.group(0))
        return REPLACEMENT if luhn(digits) else match.group(0)

    text = _CARD.sub(_card, text)

    def _iban(match: re.Match[str]) -> str:
        return REPLACEMENT if iban_valid(match.group(0)) else match.group(0)

    return _IBAN.sub(_iban, text)


def redact(value: Any, depth: int = 0) -> Any:
    """The same structure with every recognised value replaced."""
    if depth > 24:
        return value
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {k: redact(v, depth + 1) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, depth + 1) for v in value]
    return value


__all__ = [
    "MAX_SCAN",
    "REPLACEMENT",
    "Hit",
    "iban_valid",
    "luhn",
    "redact",
    "redact_text",
    "scan",
    "scan_text",
]
