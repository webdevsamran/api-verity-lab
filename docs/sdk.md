# SDK

```python
from apiverity.sdk import (
    Contract, Operation, SchemaNode, Change, Finding, RuleSpec,
    TestCase, TestResult, Workflow, DriftFinding, PerformanceReport,
    diff_services, evaluate_breaking, SemverPolicy,
)
from apiverity.specs.loader import detect_and_load

service, findings, plugin = detect_and_load("api/openapi.yaml")
op: Operation = service.find_operation("GET /users")
changes: list[Change] = diff_services(old, new)
findings = evaluate_breaking(changes)
```

All types are pydantic models: serialize with `.model_dump()` /
`.model_dump_json()`. Plugin API contract version:
`from apiverity.sdk import PLUGIN_API_VERSION` (currently `1`).