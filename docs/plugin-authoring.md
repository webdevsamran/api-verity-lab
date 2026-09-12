---
description: >-
  Writing a plugin for api-verity-lab: six versioned entry-point groups, discovered by any installation that pip-installs your distribution.
---

# Writing a plugin

This project has six versioned entry-point groups. A distribution declaring one
is discovered by every installation that pip-installs it — there is no registry
to register with, because Python already has a distribution channel and
inventing a second index would mean operating one.

| Group | What it adds | Discovered by |
|---|---|---|
| `apiverity.specs` | A contract format the loader can recognise | `apiverity.plugins.registry` |
| `apiverity.rules` | A governance rule pack | `apiverity.rules.packs_registry` |
| `apiverity.checks` | A check the security engine runs | `apiverity.plugins.registry` |
| `apiverity.generators` | A fuzz-case generator | `apiverity.plugins.registry` |
| `apiverity.exporters` | A result exporter | `apiverity.plugins.registry` |
| `apiverity.transports` | A client for a protocol the tool can speak | `apiverity.plugins.registry` |

`apiverity plugins` lists what an installation has. `apiverity rules --packs`
lists rule packs specifically, with the distribution each came from.

## The worked example

[`examples/plugins/apiverity-house-rules`](https://github.com/webdevsamran/api-verity-lab/tree/main/examples/plugins/apiverity-house-rules)
is a complete rule pack as its own package: `pyproject.toml`, the rules, and its
own tests. It is installed into a throwaway virtualenv by
`tests/unit/test_example_plugin.py`, which then runs the CLI there and asserts
the rules actually fire — so the example cannot rot into one that no longer
loads.

```bash
pip install -e examples/plugins/apiverity-house-rules
apiverity rules --packs
apiverity validate openapi.yaml     # HOUSE-* findings appear alongside the built-ins
```

## A rule pack in full

```toml
# pyproject.toml
[project]
name = "apiverity-house-rules"
dependencies = ["api-verity-lab>=0.2,<1.0"]

[project.entry-points."apiverity.rules"]
house-rules = "house_rules:pack"
```

```python
# house_rules/__init__.py
from apiverity.core.model import Finding, Protocol, Service, Severity
from apiverity.rules.policy import RuleDefinition, RulePack


def no_camel_case_paths(service: Service) -> list[Finding]:
    return [
        Finding(
            rule_id="HOUSE-PATH-CASE",
            severity=Severity.WARN,
            message=f"path '{op.path}' is not kebab-case",
            operation_key=op.key,
            hint="rename the segment, or drop this rule if your house style differs",
        )
        for op in service.operations
        if any(c.isupper() for c in (op.path or ""))
    ]


PACK = RulePack(
    name="house-rules",
    version="1.0.0",
    description="House style rules the engine does not ship.",
    rules=(
        RuleDefinition(
            rule_id="HOUSE-PATH-CASE",
            severity=Severity.WARN,
            rationale="Mixed path casing makes an API read as several APIs stitched together.",
            remediation="Rename the segment to kebab-case.",
            protocols=frozenset({Protocol.OPENAPI}),
            check=no_camel_case_paths,
        ),
    ),
)


def pack() -> RulePack:
    return PACK
```

The entry point may be the pack or a callable returning one; `discover()` calls
it if it is callable. A factory is the better habit, because it defers the work
until something asks.

## What a rule owes its reader

The catalogue holds built-in rules to this, and a pack that skips it teaches the
wrong shape.

**A rationale and a remediation.** A rule that says only "no" is a rule that
gets switched off, and it takes its neighbours with it. `rationale` says why
this matters; `remediation` says what to do instead.

**A protocol set it can actually be satisfied in.** A path-casing rule run
against a GraphQL schema fires on nothing or on everything, and neither is
information. Declare `protocols` narrowly.

**Both directions, tested.** A check that fires on everything and a check that
fires on nothing are equally useless, and only running them against a passing
contract *and* a failing one tells the two apart. The example's tests do exactly
that, and so does the test in this repository that holds the example to it.

**A rule id nobody else owns.** `PolicyEngine` refuses to run two rules with one
id — it cannot explain both — so prefix yours. `apiverity rules --packs`
reports conflicts as data before the engine refuses them, naming which packs
clash.

## What breaks, and how you find out

**A pack that raises on import is named, not skipped.** `apiverity rules
--packs --json` lists it under `failed`, with the exception. A team whose pack
raises should find that out rather than believe it is running.

**A pack whose entry point returns something that is not a `RulePack` is
ignored.** That is deliberate: `apiverity.rules` is also how this project
publishes its own breaking-change catalogue, which is a dict, and reporting
"not a RulePack" about the project's own entry point would be a false alarm on
every installation.

**The plugin API is versioned.** `apiverity.plugins.PLUGIN_API_VERSION` is the
v1 contract; `apiverity.plugins.v2` adds a `PluginManifest` with declared
capabilities. A v2 plugin's manifest states which host versions it supports, and
the loader refuses one that does not support the host rather than importing it
and finding out.

## The conformance kit

For v2 plugins, `apiverity.plugins.conformance` checks a plugin object against
the contract before anybody installs it: a valid manifest, capabilities that map
to methods that exist, and safe failure modes.

```python
from apiverity.plugins.conformance import conformance_report

report = conformance_report(MyPlugin())
assert report["conforms"], report["failures"]
```

## Starting from a scaffold

```bash
apiverity plugins scaffold my-plugin --out ./my-plugin
```

writes a conforming v2 layout — manifest, implementation and a conformance
test — so a first plugin starts from a working shape rather than from this
page.

## Publishing

There is nothing to publish *to*. Push the package to PyPI, or to a private
index, or install it from a path; discovery is `importlib.metadata` either way.
Provenance in the listing is the distribution name and version, which is what a
reader needs to answer "where did this rule come from" — and exactly the field a
hand-rolled registry would have had to invent.
