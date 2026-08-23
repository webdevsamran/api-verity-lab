"""Plugin system.

Six versioned entry-point groups:

- ``apiverity.specs``      — spec adapters (OpenAPI/GraphQL/gRPC/...)
- ``apiverity.rules``      — breaking-change rules
- ``apiverity.checks``     — static contract checks (security, hygiene)
- ``apiverity.generators`` — test-case generators
- ``apiverity.exporters``  — report/bundle exporters
- ``apiverity.transports`` — HTTP/gRPC transports for test runners

The plugin API contract is versioned via ``PLUGIN_API_VERSION``; plugins
declaring an incompatible version are skipped with a warning.
"""

from apiverity import PLUGIN_API_VERSION

__all__ = ["PLUGIN_API_VERSION"]
