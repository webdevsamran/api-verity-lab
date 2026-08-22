# Breaking-Rule Catalog

Severity levels: **ERROR** (blocks CI), **WARN** (risky, review), **INFO** (informational).
Rules are *direction-aware*: the same schema edit can be safe in a request and
breaking in a response. Override any severity with
`apiverity breaking --severity-override BRK-XXX=WARN` or in config.

## Operations
| Rule | Severity | Fires when |
|---|---|---|
| BRK-OP-REMOVED | ERROR | an operation is deleted |
| BRK-OP-ADDED | INFO | a new operation appears |
| BRK-DEPRECATED | INFO | an operation gains `deprecated: true` |

## Parameters
| Rule | Severity | Fires when |
|---|---|---|
| BRK-PARAM-REMOVED | ERROR | a required parameter is deleted |
| BRK-PARAM-REQUIRED | ERROR | a parameter becomes required |
| BRK-PARAM-TYPE-CHANGED | ERROR | request parameter type/format narrows |
| BRK-CONSTRAINT-TIGHTENED | ERROR | request min/max/enum/pattern tightens |
| BRK-CONSTRAINT-LOOSENED | INFO | request constraints widen (response: WARN) |

## Request / response bodies
| Rule | Severity | Fires when |
|---|---|---|
| BRK-REQ-BODY-REQUIRED | ERROR | request body becomes required |
| BRK-FIELD-REQUIRED-REQUEST | ERROR | a request field becomes required |
| BRK-FIELD-REMOVED-RESPONSE | ERROR | a response field disappears |
| BRK-ENUM-NARROWED-REQUEST | ERROR | request enum loses values |
| BRK-ENUM-NARROWED-RESPONSE | WARN | response enum loses values |
| BRK-TYPE-CHANGED-RESPONSE | ERROR | response field type changes |
| BRK-RESP-STATUS-REMOVED | ERROR | a declared success status disappears |
| BRK-HEADER-REMOVED | WARN | a declared response header disappears |

## Security & versioning
| Rule | Severity | Fires when |
|---|---|---|
| BRK-SEC-ADDED | ERROR | auth is newly required |
| BRK-SEC-REMOVED | WARN | auth requirement dropped |
| SEMVER-MAJOR-REQUIRED | ERROR | breaking changes without a major bump |
| SEMVER-DECREASE | ERROR | version went backwards |
| SEMVER-NO-BUMP | WARN | material change with identical version |
| SEMVER-MINOR-POLICY | WARN | warnings shipped without a minor bump (configurable) |

Run `apiverity rules --json` for the live catalog with descriptions.