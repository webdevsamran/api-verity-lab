"""Shared fixtures for the apiverity test suite."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from apiverity.specs.loader import detect_and_load  # noqa: E402


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
