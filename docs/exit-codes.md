# Exit codes

`api-verity-lab` treats its exit codes as a public contract: CI gates and onboarding
scripts branch on them, so an existing code never changes meaning -- new ones
are appended.

Defined in [`apiverity/cli/commands/common.py`](../apiverity/cli/commands/common.py).

| Code | Name | Meaning |
|---|---|---|
| `0` | `OK` | Completed; nothing to report. |
| `1` | `FINDINGS` | Completed; findings were detected. A gate should treat this as failure. |
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
