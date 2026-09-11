# Framework adapters

Most teams keep an `openapi.yaml` in the repository and check it in CI. The
check is only ever as true as the file, and the file is the thing that goes
stale — a service whose handlers changed and whose committed contract did not
passes every rule in this project and describes something that no longer
exists.

`apiverity app` closes that gap by reading the document the application itself
produces.

```bash
# What does the application actually serve?
apiverity app myapp.main:app

# Does the committed contract still describe it?
apiverity app myapp.main:app --against openapi.yaml

# Regenerate the file, then use it like any other contract
apiverity app myapp.main:app -o openapi.json
apiverity breaking baselines/v2.json openapi.json
```

The target is named the way `uvicorn` and `gunicorn` name it —
`module:attribute` — because that string already exists in every deployment
that runs the application.

## `--against` is the check worth having

Without it, `apiverity app` validates the application's contract, which is
useful. With it, the run answers the question the committed file cannot answer
about itself: **is it still true?**

A stale file fails the run whether or not the difference is breaking. An added
operation breaks nobody and the file is still wrong; a command that passed on
additive drift would only catch the staleness that happened to be breaking,
which is the smaller half of it.

```
$ apiverity app orders.main:app --against openapi.yaml
committed:
  file: openapi.yaml
  changes: 3
  in_sync: false
$ echo $?
1
```

## What it works with

Any object with an `openapi()` method that returns a document — which is
FastAPI's, every Starlette-derived framework's, APIFlask's, and anything else
that adopted the convention. An `openapi` attribute holding the document
directly is accepted too.

This is deliberately a **shape**, not a class check. `isinstance(app, FastAPI)`
would make FastAPI a dependency of a tool that does not need one, and would
refuse an application that produces exactly the right document because its
class belongs to somebody else.

## Importing an application runs it

This is the whole cost of the feature and it is stated rather than buried.
`apiverity app` imports the module you name, which executes its top-level code:
decorators, module-level clients, database connections, whatever the
application does at import time.

That is the same cost `uvicorn myapp:app` has, so a team already starting the
application this way takes on no new risk. Pointing it at code you have not
read is a different proposition, and the answer there is to export the document
in that project and check the file.

## What it does not do

Start the application, bind a port, or send a request. The document is built
in process from the route table.

`apiverity drift --base-url` is the command for asking what a *running* service
does. Conflating the two would produce a check that claims to have observed
something it constructed — and the distinction is the reason `apiverity app`
reports its comparison under `committed` rather than `drift`.

## Why only Python ships an adapter

The catalogue entry for this work (RUN-06) listed FastAPI, Express, NestJS,
Laravel, Spring and gin. One of them ships. The reason is worth stating plainly,
because "six adapters" would have been a better-sounding and less true claim.

An adapter is only worth writing where this tool shares a runtime with the
framework, so it can hold the application object in memory. That is Python, and
in Python it is one adapter covering every framework that produces an OpenAPI
document.

For the others, an OpenAPI generator already exists and is maintained by people
closer to the framework than this project will ever be. The "adapter" is a shell
pipeline, and it needs no code here:

| Framework | Generate the document | Then |
|---|---|---|
| Express | `swagger-jsdoc`, `express-oas-generator` | `apiverity breaking base.json openapi.json` |
| NestJS | `@nestjs/swagger` (`SwaggerModule.createDocument`) | ″ |
| Laravel | `l5-swagger`, `scramble` | ″ |
| Spring Boot | `springdoc-openapi-maven-plugin` | ″ |
| gin | `swaggo/swag init` | ″ |

Shipping a thin wrapper around each of those commands would add five things to
maintain, five ways to be out of date with somebody else's tool, and no
capability. The table is the adapter.

What a Node or Go project does gain from this repository is the CI gate
([`docs/ci.md`](ci.md)) and the container image, both of which take a document
from any producer.
