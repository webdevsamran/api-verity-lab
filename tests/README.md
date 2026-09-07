# Test suite layout

- `unit/` — fast, isolated tests of pure logic (models, rules engines,
  generators, plugins, protocol compatibility). No network, no servers.
- `integration/` — tests that exercise real processes: the deterministic
  mock server (`MockServer`) and the self-hosted Flask API (`create_app`)
  over live HTTP.
- `conftest.py` — shared fixtures (loaded specs from `fixtures/`).

Run everything with `pytest` from the repository root. The CI pipeline runs
the same suite with coverage enforced (`--cov-fail-under`, see
`.github/workflows/ci.yml`).
