---
description: >-
  Server-Sent Events, JSON Lines and multipart streams: the OpenAPI 3.2 itemSchema, itemEncoding and prefixEncoding keywords, and the rules that diff them.
---

# Streaming payloads

Server-Sent Events, JSON Lines, and multipart streams — the payloads that have
no end, and that OpenAPI had no way to describe until 3.2.

```bash
apiverity validate stream.yaml                      # is one item described at all?
apiverity breaking stream-v1.yaml stream-v2.yaml    # did the event shape change?
```

## The problem 3.2 solved

Before OpenAPI 3.2 a streaming endpoint had two options and both were wrong.

Declare `schema`, and you are describing the whole body — but a stream has no
whole body, so the schema describes something the client never holds. Or
declare nothing, and the payload is documented in prose, which means no tool
can check it, mock it or notice when it changes.

3.2 added **`itemSchema`**: the shape of *one item*, not of the body.

```yaml
responses:
  '200':
    content:
      text/event-stream:
        itemSchema:            # one event, not the stream
          type: object
          required: [id, kind]
          properties:
            id:   { type: string }
            kind: { type: string, enum: [created, updated, deleted] }
```

## What this tool does with it

**Every schema rule applies to an item.** `itemSchema` is parsed into the same
`SchemaNode` a body schema is, so removing a field from an event produces
`BRK-RESP-FIELD-REMOVED` exactly as removing it from a body does — with the
finding labelled `stream item` so a reader knows which it was.

```
[ERROR] BRK-RESP-FIELD-REMOVED  response 200 stream item (text/event-stream): field 'detail' was removed
[WARN]  BRK-ENUM-NARROWED-RESPONSE  response 200 stream item (text/event-stream).kind: enum changed (removed ['deleted'])
```

A second family of item-shaped rules would have been forty duplicates of rules
that already exist, and they would have drifted.

## The five rules that are about streaming itself

These are the changes no schema rule can see, because no schema changed.

| Rule | |
|---|---|
| `BRK-STREAM-SEQUENTIAL-CHANGED` | A payload moved between a single document and a sequence of items. |
| `BRK-STREAM-ITEM-SCHEMA-REMOVED` | A sequential media type stopped declaring `itemSchema`. |
| `BRK-STREAM-ITEM-SCHEMA-ADDED` | It started declaring one. |
| `BRK-STREAM-ENCODING-CHANGED` | A streamed item's `contentType` changed. |
| `BRK-STREAM-PREFIX-COUNT-CHANGED` | The number of leading parts in a multipart stream changed. |

### The one worth having

`BRK-STREAM-SEQUENTIAL-CHANGED`. Moving a payload from `application/json` to
`application/jsonl` breaks every consumer even when the item shape is
byte-identical:

- a client reading `application/json` waits for the body to end, then parses
  once;
- a client reading `application/jsonl` parses a line at a time, and may never
  see an end at all.

Nothing about the schema changed, so every schema-diffing tool reports a clean
run. This is the finding that exists because somebody will make that change
thinking it is a content-negotiation detail.

The non-breaking route, which `--suggest-fix` prints: serve both, and let
content negotiation decide rather than a deploy.

### `prefixEncoding` is positional

`BRK-STREAM-PREFIX-COUNT-CHANGED` is an ERROR for a reason that is easy to miss:
`prefixEncoding` describes the leading parts of a multipart stream *by
position*. Inserting or removing one renumbers every part after it, so a reader
that correctly identified part three now reads part four's bytes with part
three's decoder.

Append, or version the operation.

## Two validation rules

`apiverity validate` reports both directions of the mistake:

- **`SPEC-STREAM-ITEM-SCHEMA-MISSING`** — a sequential media type with no
  `itemSchema`. This is what every pre-3.2 contract looks like, and it is worth
  a warning rather than silence: the payload is invisible to every rule, mock
  and drift check, and the contract does not say so.
- **`SPEC-STREAM-ITEM-SCHEMA-UNUSED`** — `itemSchema` on a media type that is
  not sequential. Nothing reads it.

## Which media types count as sequential

`text/event-stream`, `application/jsonl`, `application/x-ndjson`,
`application/json-seq`, `application/jsonlines`, and anything under
`multipart/`.

Parameters are ignored: `text/event-stream; charset=utf-8` is the same media
type as `text/event-stream`, and a contract writing one against a service
sending the other are not disagreeing about anything.

## `itemEncoding` is read in both shapes it is written in

The documented shape is a map of property name to Encoding Object. Some
documents write a single Encoding Object there instead, meaning "this applies
to the whole item".

Both are read. The single-object form is stored under the empty key and
reported as *the item* rather than as a named property — because a contract
this tool silently ignored half of would be worse than one it read generously
and reported on accurately.

## What is not modelled

`contentType`, `style`, `explode` and the header *names* of an Encoding Object.
The header schemas inside an encoding are not carried into the model, so a
change to one produces no finding. That is a real gap and it is recorded here
rather than left for somebody to discover from a clean run — it is listed in
[product gaps](product-gaps.md).
