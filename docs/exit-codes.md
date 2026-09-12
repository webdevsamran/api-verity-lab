---
description: >-
  The exit codes api-verity-lab treats as a public contract, so CI gates and onboarding scripts can branch on them without breaking on an upgrade.
---

# Exit codes

`api-verity-lab` treats its exit codes as a public contract: CI gates and onboarding
scripts branch on them, so an existing code never changes meaning -- new ones
are appended.

Defined in [`apiverity/cli/commands/common.py`](https://github.com/webdevsamran/api-verity-lab/blob/main/apiverity/cli/commands/common.py).

## INFO findings do not fail a run

`1` means findings a gate should act on, which is findings at or above `WARN`.
Severity `INFO` is an observation: the protocol era a manifest came from, a
tool list whose *order* varies between connections, a local server that serves
its inventory anonymously. Those are worth recording and they are not defects,
and a run that fails on them teaches people to stop reading the output.

They are still in the artifact. `--json` carries every finding at every
severity, so a report that exits `0` is not a report that found nothing --
read `findings`, not just the status.

| Code | Name | Meaning |
|---|---|---|
| `0` | `OK` | Completed; nothing to report. |
| `1` | `FINDINGS` | Completed; findings at or above **WARN** were detected. A gate should treat this as failure. |
| `2` | `USAGE` | The command was invoked incorrectly. |
| `3` | `UNREACHABLE` | A target could not be contacted. |
| `4` | `INTERNAL` | An unexpected error inside the tool. |

## If you use more than one of these tools

These four projects are independent and their exit codes are **not** a shared
vocabulary. Only `0` means the same thing in all of them (success). Every other
code differs, and two collisions are worth knowing before you write a wrapper:

| Code | api-verity-lab | devrepro-doctor | tooltrace-bench | local-ai-hardware-bench |
|---|---|---|---|---|
| 1 | findings detected | **ready, with warnings** | error | validation error |
| 2 | usage error | **machine blocked** | task validation error | usage error |

The dangerous one is `1`. In devrepro-doctor it means *the machine is usable*;
in the other three it means something went wrong. A wrapper that treats any
non-zero status as failure will block on a DevRepro run that reported success.

The second is `2`: an operator mistake in two of them, and devrepro-doctor's
most important verdict -- the machine cannot build this project -- in the third.

These are not being unified. A shared exit-code library would couple four
independent release cycles, and one of these projects deliberately ships with
no dependencies at all. Knowing the difference is cheaper than removing it.
