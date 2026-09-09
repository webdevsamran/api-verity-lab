"""Shared fixtures for the apiverity test suite."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from apiverity.specs.loader import detect_and_load  # noqa: E402

_ONES = (
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
)
_TENS = ("", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety")


def _spell(n: int) -> str:
    if n < len(_ONES):
        return _ONES[n]
    tens, ones = divmod(n, 10)
    return _TENS[tens] + (f"-{_ONES[ones]}" if ones else "")


@pytest.fixture(scope="session")
def spell_number():
    """Spell a small number the way the prose in this repository does.

    Shared because two documents state counts in words and both are bound to
    code that keeps growing; a hardcoded lookup in each test broke three times
    in one session as commands were added. The guard should be about the
    document being wrong, not about the table inside the test being short.

    Delivered as a fixture rather than an import on purpose. Four sibling
    projects are installed editable on a maintainer machine, each putting its
    own root on `sys.path`, so `from tests.conftest import ...` resolves to
    whichever `tests` package Python reaches first -- which on this machine is
    a different repository entirely. pytest loads conftest by path, so a
    fixture cannot be captured by that.
    """
    return _spell


@pytest.fixture(scope="session")
def crud_service():
    service, _, _ = detect_and_load(str(ROOT / "fixtures/apis/crud/openapi.yaml"))
    return service


@pytest.fixture(scope="session")
def v1_service():
    service, _, _ = detect_and_load(str(ROOT / "fixtures/apis/versioned/v1.yaml"))
    return service


@pytest.fixture(scope="session")
def v2_service():
    service, _, _ = detect_and_load(str(ROOT / "fixtures/apis/versioned/v2.yaml"))
    return service
