"""Plugin scaffolding generator.

Creates a ready-to-extend v2 plugin package (manifest, implementation,
tests) so contributors start from a conforming reference layout instead of
guessing. Never installs anything; it only writes files into a target dir.
"""

from __future__ import annotations

import re
from pathlib import Path

_TEMPLATE = '''"""{name} plugin for API Verity Lab (plugin API v2)."""

from __future__ import annotations

from typing import Any

from apiverity.core.model import Finding
from apiverity.plugins.v2 import PluginManifest

manifest = PluginManifest(
    name="{name}",
    version="0.1.0",
    description="{description}",
    capabilities=["rules"],
    entry_point="{module}:{class_name}",
)


class {class_name}:
    """Example rules-capability plugin: flags operations without descriptions."""

    manifest = manifest

    def check(self, service: Any) -> list[Finding]:
        findings: list[Finding] = []
        operations = getattr(service, "operations", []) or []
        for op in operations:
            if not getattr(op, "description", None):
                findings.append(
                    Finding(
                        rule_id="{rule_prefix}-NO-DESCRIPTION",
                        severity="INFO",
                        message=f"operation '{{op.key}}' has no description",
                        operation_key=getattr(op, "key", None),
                    )
                )
        return findings
'''

_TEST_TEMPLATE = '''"""Conformance tests for the {name} plugin."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from {module} import {class_name}  # noqa: E402
from apiverity.plugins.conformance import conformance_report


def test_conforms() -> None:
    report = conformance_report({class_name}())
    assert report["conforms"], report["failures"]
'''


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def scaffold_plugin(name: str, target_dir: str | Path, *, description: str = "") -> Path:
    """Write a minimal conforming plugin package; returns the package dir."""
    module = _slug(name)
    class_name = "".join(part.capitalize() for part in module.split("_"))
    pkg = Path(target_dir) / module
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "plugin.py").write_text(
        _TEMPLATE.format(
            name=name,
            description=description or f"{name} plugin",
            module=f"{module}.plugin",
            class_name=class_name,
            rule_prefix=module.upper()[:12],
        ),
        encoding="utf-8",
    )
    tests_dir = pkg / "tests"
    tests_dir.mkdir(exist_ok=True)
    (tests_dir / f"test_{module}_conformance.py").write_text(
        _TEST_TEMPLATE.format(module=f"{module}.plugin", class_name=class_name, name=name),
        encoding="utf-8",
    )
    return pkg
