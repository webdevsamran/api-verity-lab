# GraphQL federation

```bash
# what one subgraph's change does to the composed graph
apiverity federation --subgraph products.graphql --against products-previous.graphql

# whether a set of subgraphs can compose
apiverity federation --subgraph products.graphql --subgraph reviews.graphql
```

An SDL diff compares two documents. In a federated graph that is the wrong
unit: a subgraph is one contributor to the schema clients actually query, and
the changes that matter most are the ones invisible in the subgraph and
decisive in the supergraph.

## The one-line example

```diff
 type Product @key(fields: "id") {
   id: ID!
-  price: Int
+  price: Int @inaccessible
 }
```

Same field. Same name. Same type. Same subgraph.

`apiverity diff` reports no removal — nothing about the field changed. And
`price` is gone from the supergraph, so every client loses it.

## This is not a composition

Composing a supergraph is what `rover` and `@apollo/composition` do. They do it
properly, and a second implementation whose output looked like theirs and was
computed differently is exactly what this project refuses to build — the same
argument [the Spectral importer](spectral-migration.md) makes.

So this checks the **preconditions**: the conditions under which composition
fails, or silently changes what clients see. Every run says so in its own
output:

```json
"note": "these are composition preconditions, not a composition. A clean result
         is not a claim that `rover compose` succeeds, and a subgraph missing
         from this run may own a field reported here as unresolved."
```

That sentence is there because the alternative is a tool that reports no
findings and gets read as "this composes".

## The rules

**Comparing one subgraph with its previous revision** (`--against`):

| Rule | |
|---|---|
| `FED-KEY-REMOVED` | a type stopped being an entity |
| `FED-KEY-CHANGED` | a `@key` it used to declare is gone |
| `FED-INACCESSIBLE-ADDED` | the field left the supergraph without leaving the subgraph |
| `FED-SHAREABLE-REMOVED` | another subgraph resolving it now breaks composition |
| `FED-EXTERNAL-ADDED` | declared here, owned elsewhere |
| `FED-OWNERSHIP-MOVED` | an `@override` changed which subgraph resolves it |

**Checking a set of subgraphs against each other:**

| Rule | |
|---|---|
| `FED-UNSHAREABLE-DUPLICATE` | two subgraphs resolve one field, not `@shareable` in all |
| `FED-KEY-INCONSISTENT` | an entity in one subgraph, not keyed in another |
| `FED-EXTERNAL-DANGLING` | an `@external` field nothing here resolves |
| `FED-REQUIRES-UNKNOWN-FIELD` | a `@requires` naming a field nothing here defines |

`apiverity explain FED-INACCESSIBLE-ADDED` for any of them.

## Two places it is careful not to overreach

**Key fields are never duplicates.** `@key` fields are implicitly shareable in
Federation v2, and every subgraph keying the entity is *required* to declare
them. The first version of `FED-UNSHAREABLE-DUPLICATE` reported `Product.id` on
every correctly federated graph there is — which is how a rule gets switched off
before anybody reads its second finding.

**An incomplete run looks like a broken graph.** `FED-EXTERNAL-DANGLING` and
`FED-REQUIRES-UNKNOWN-FIELD` both fire when a subgraph that owns the field was
simply not passed. The findings say so in their hints, and `@requires` is a WARN
rather than an ERROR for exactly that reason: from inside this run, a missing
subgraph and a wrong selection are indistinguishable.

## What it reads

The federation v2 directives, from the parsed AST: `@key`, `@shareable`,
`@external`, `@requires`, `@provides`, `@override`, `@inaccessible`, `@tag`.

A subgraph that does not declare them in an `@link` is still understood. The
directives are what the document writes, and requiring the import to read them
would miss every subgraph that forgot it — which is the population most likely
to have a problem.

A `@requires(fields: "price { amount }")` selection is read one level deep.
`price` is on this type; `amount` is on another, and following it would mean
resolving types this deliberately does not.
