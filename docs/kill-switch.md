---
description: >-
  The emergency policy freeze auditors of agent-era systems ask for by name, as one command -- plus the activity log and permission review alongside it.
---

# Emergency freeze

Auditors of agent-era systems ask for three things by name: activity logs,
permission reviews, and a **kill-switch procedure**. The first two are
[`audit export`](audit-export.md) and the RBAC model in
[self-hosting](self-hosting.md). This is the third.

"Revoke the tokens" is not a procedure. It is an outage; it takes down the
verification runs that would tell you whether it is safe to restart; and it
leaves no record of who decided or why. A freeze is the smaller, reversible
version: **releases stop, everything that tells you whether it is safe to
restart keeps running.**

```bash
apiverity freeze on --reason "tool poisoning suspected on orders-mcp" \
  --server https://verity.internal --token-env APIVERITY_TOKEN
```

```bash
apiverity freeze status --server https://verity.internal
apiverity freeze off --reason "contained; manifest reverted" --server https://verity.internal
```

`status` exits **1** while frozen and **3** when the server cannot be reached.
Neither is `0`, so a pipeline that gates on it fails closed — a kill switch a
network partition disables is not a kill switch.

## Who can pull it, and who can release it

| Action | Minimum role |
|---|---|
| `freeze on` | member (`request_approval`) |
| `freeze status` | viewer (`read`) |
| `freeze off` | admin (`decide_approval`) |

Deliberately asymmetric. An emergency in which only an administrator can stop
deployments, and the administrator is asleep, **is** the emergency. The cost of
a member freezing in error is a paused pipeline and a loud audit entry; the cost
of nobody being able to stop is the thing the switch exists for. Restarting is
the decision that deserves the higher bar, because it is the one that says the
danger has passed.

A freeze without a `--reason` is refused. An unexplained freeze is an outage
whose cause nobody can find, at the moment everybody is looking for it.

## What it stops

- `can-i-deploy` returns `deployable: false`, whatever the verifications say —
  and the freeze is checked *before* the contract lookup, so a frozen org gets
  the freeze as the reason rather than "has never been published", which during
  an incident sends somebody to debug the wrong thing.
- An approval cannot be **granted**.

## What it does not stop

Returned in the state object on every frozen response, not only written here: a
caller reading `deployable: false` is mid-incident and is not going to go and
find a documentation page.

- **Verification runs, drift checks and the job queue.** Those are how you find
  out whether it is safe to lift. Taking them down with the releases would leave
  you frozen and blind.
- **Anything that never calls this server.** A deploy pipeline that does not ask
  `can-i-deploy` is unaffected, and so is an MCP server somebody else operates.
  This is an interlock on the decisions *this* server makes, not a network kill
  switch. Saying otherwise would be the most dangerous sentence in this
  repository.
- **Credentials.** A valid token still reads, publishes and records runs.
- **Denying an approval.** Only granting is refused. Refusing a denial during an
  incident would freeze the wrong direction.

## No auto-expiry

There is no timer that lifts a freeze. A kill switch that releases itself is not
a kill switch, and the moment it would fire is exactly the moment nobody is
watching.

`--review-by` sets an advisory timestamp; after it passes, the state reports
`overdue_for_review: true`. Nothing acts on it. That gives the "do not forget
this is on" property without the "turns itself back on" hazard.

## The record

Both transitions append to the hash-chained audit log with the actor and the
reason (`org.frozen`, `org.freeze_lifted`), and both fire a webhook. Freeze rows
are never deleted — the table is the freeze *history*: what was stopped, by
whom, why, and when it was released. A boolean column on the org would have
thrown that away, and an incident review needs it.

```bash
apiverity audit export --db server.db --org-id 1 -o incident-4412.json
```

That export is the evidence that the procedure was followed, verifiable away
from the server that produced it.

## HTTP

| Route | Role | Notes |
|---|---|---|
| `GET /v1/freeze` | viewer | current state plus the freeze history |
| `POST /v1/freeze` | member | `{"reason": "...", "review_by": "..."}`; `400` without a reason |
| `DELETE /v1/freeze` | admin | `{"reason": "..."}` |

Both `POST` and `DELETE` are idempotent. Somebody reaching for this is
mid-incident and may well hit it twice, or twice from two terminals; a `409`
there reads as "the switch did not work".
