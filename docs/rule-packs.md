# Rule packs: writing one, shipping one, finding one

```bash
apiverity rules --packs
```

A rule pack is a versioned bundle of governance rules. Two ship built in
(`apiverity-governance`, `apiverity-security`); anyone can ship a third.

## There is no registry to run, and that is deliberate

"Publish and discover, npm-style" does not need a server here.

A rule pack is Python. Python already has a distribution channel. A pack
published to PyPI that declares an `apiverity.rules` entry point is
discoverable by every installation that `pip install`s it — no index to
operate, no account to create, no second thing to keep up.

```toml
# pyproject.toml, in your pack's own package
[project.entry-points."apiverity.rules"]
acme-house-style = "acme_apiverity_rules:PACK"
```

```python
# acme_apiverity_rules/__init__.py
from apiverity.core.model import Finding, Severity
from apiverity.rules.policy import RuleDefinition, RulePack

def _no_internal_hosts(service):
    return [
        Finding(
            rule_id="ACME-INTERNAL-HOST",
            severity=Severity.ERROR,
            message=f"server '{s.url}' is an internal address",
        )
        for s in service.servers
        if ".internal." in s.url
    ]

PACK = RulePack(
    name="acme-house-style",
    version="1.0.0",
    description="Acme's contract rules",
    rules=(
        RuleDefinition(
            rule_id="ACME-INTERNAL-HOST",
            severity=Severity.ERROR,
            rationale="an internal hostname in a published contract is a leak",
            remediation="use the public gateway hostname",
            check=_no_internal_hosts,
        ),
    ),
)
```

Install it and it runs. The entry point may point at the pack directly or at a
factory returning one.

## Where a rule came from

`apiverity rules --packs` answers the question a list of seventy rule ids
cannot:

```json
{
  "name": "acme-house-style",
  "version": "1.0.0",
  "source": "acme-apiverity-rules 2.1.0",
  "entry_point": "acme-house-style",
  "rules": 1,
  "rule_ids": ["ACME-INTERNAL-HOST"]
}
```

`source` is the distribution and version. That is exactly the field a
hand-rolled registry would have had to invent, and the packaging metadata
already has it.

## Two things it will not hide

**A pack that will not load.** An entry point pointing at a module that raises
on import is listed under `failed`, with the error. Skipping it silently would
leave a team believing their pack is running.

**A rule id two packs both claim.** `PolicyEngine` refuses to run in that state
— two rules with one id cannot both be explained by `apiverity explain`, and
one would silently win. But raising is wrong for the *listing*: one
badly-behaved pack should not stop `--packs` telling you which one it is. So
the conflict is reported as data, naming both packs, and neither side is
dropped from the list.

Either state exits `1`.

## Severity, and who decides it

A pack declares a severity per rule. The project's
[severity profiles and `severity_overrides`](ci.md) still apply on top: a pack
is a source of rules, not an authority over your gate.
