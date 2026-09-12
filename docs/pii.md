---
description: >-
  Personal data and credential handling: two rules with opposite defaults, because secrets and personal data fail in opposite directions.
---

# Personal data

Two rules with opposite defaults, because credentials and personal data fail in
opposite directions.

A leaked credential is **always** wrong. A returned email address is usually
the entire point of the endpoint.

## What is a finding, and what is not

**Not a finding:** an API returning personal data. `GET /users/{id}` returning
an email is the endpoint working. A check that fired on that would produce
hundreds of findings per contract — and
[`security/hardening.py`](check-rules.md) already records why that is fatal:
the check gets switched off, taking the useful ones with it.

**A finding:** personal data the contract **does not say is there**.

```yaml
properties:
  nickname: {type: string}          # and the service returns an email address
  contact:
    type: string
    x-data-classification: pii      # declared, so not reported
```

`DRIFT-RESPONSE-PII` fires on `nickname` and stays silent on `contact`. Either
the contract is wrong about what it returns or the service is returning
something it should not, and neither is visible without comparing the two.

The finding names the **kind** and the **path** and the **length**. Never the
value — the same rule `SEC-RESPONSE-CREDENTIAL` follows, for the same reason: a
report that quoted the value would have copied a customer's email into a log,
a CI annotation and a result artifact.

**Always redacted:** personal data on its way into a file.
[`apiverity capture`](capture.md) replaces it with `[PII]` before the HAR is
written. A corpus is something people commit, and no credential pattern names
the field a customer's email arrived in.

## Shapes, with checksums where there are any

| | How it is confirmed |
|---|---|
| payment card number | Luhn — a sixteen-digit number that fails it is an order reference |
| bank account (IBAN) | ISO 13616 mod-97 |
| email address | a structure nothing else uses |
| IP address (v4/v6) | parsed, not pattern-matched, so `999.1.1.1` is a version string |

## What is deliberately not detected

**Names. Street addresses. Dates of birth. Free-text notes.**

They have no shape. "Paris" is a city and a person; `1990-03-14` is a birthday
and a release date; any string at all can be a name.

A detector for them is wrong most of the time, and a check that is wrong most
of the time trains people to ignore the times it is right — which is the one
thing a privacy check cannot afford.

That absence is why the **field-name** rules in `traffic/redact.py` still
matter: a field *called* `date_of_birth` is redactable by name even though its
value is not recognisable. The two mechanisms cover different halves and
neither covers everything.

## `x-data-classification`

```yaml
ssn:
  type: string
  x-data-classification: pii
```

Silences `SEC-SENSITIVE-FIELD` on that property and `DRIFT-RESPONSE-PII` on
that path.

> This annotation did nothing until now. `SEC-SENSITIVE-FIELD` read
> `data_classification` off a model that never declared the field, so the value
> was always `None` and the rule fired whatever the document said — while its
> own hint told people to add the annotation. It was also read off the *parent*
> object rather than the sensitive property, so even with the field present,
> annotating the field itself would not have silenced it. Both are fixed.

## Turning redaction off

`apiverity capture` redacts by default. The cost of an unnecessary `[PII]` is a
replayed request that is slightly less realistic; the cost of the opposite is a
customer's email address in a repository.
