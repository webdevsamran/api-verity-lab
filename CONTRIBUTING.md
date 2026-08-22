# Contributing to api-verity-lab

Thank you for considering a contribution! This document explains how to set up
a development environment and the standards we hold contributions to.

## Development setup

Requirements: Python 3.11+, Node 20+ (for the frontend), Git.

```bash
git clone https://github.com/webdevsamran/api-verity-lab.git
cd api-verity-lab

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

pre-commit install

cd web && npm install && cd ..
```

## Running checks locally

```bash
ruff check apiverity tests       # lint
ruff format --check apiverity    # format
mypy apiverity                   # strict type checking
pytest                           # unit + property tests
pytest -m integration            # fixture integration tests
cd web && npm run lint && npm run typecheck && npm test && npm run build
```

## Branching model

- `main` is the only permanent branch.
- Work happens on short-lived feature branches (`feat/<topic>`,
  `fix/<topic>`); stale branches are deleted after merge.
- Published history is never rewritten.

## Commit style

Use [Conventional Commits](https://www.conventionalcommits.org):
`feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `ci:`, `chore:`.
Commits are squashed or rebased into logical units on merge.

## Coding standards

- Python 3.11+, fully typed (`mypy --strict` must pass).
- Every new rule, generator, reporter, or spec adapter ships with tests.
- Property-based tests (Hypothesis) are expected for schema/diff logic.
- No secrets, tokens, or real traffic data may be committed — fixtures use
  synthetic values only.
- Findings must carry source locations wherever the contract model has them.

## Adding a breaking-change rule

1. Add the rule class under `apiverity/rules/breaking/`.
2. Register it in the catalog with a stable rule ID (`BRK-###`) and default
   severity (`ERROR` / `WARN` / `INFO`).
3. Document it in `docs/rules.md`.
4. Add positive and negative tests, including direction-awareness cases
   (request vs response).

## Adding a plugin

Implement one of the plugin protocols in `apiverity/plugins/api.py`
(SpecPlugin, RulePlugin, CheckPlugin, GeneratorPlugin, ExporterPlugin,
TransportPlugin) and expose it via the matching entry-point group in your
package's `pyproject.toml`. Plugin APIs are versioned; see
`apiverity/plugins/__init__.py`.

## Reporting issues

Open an issue with: version, OS, minimal reproduction, expected vs actual
behavior. For security issues see SECURITY.md — do not open public issues.

## License

By contributing you agree that your contributions are licensed under the
Apache-2.0 license of this repository.