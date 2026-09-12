"""A Postman collection, read into the same entries a HAR produces.

The most common answer to "run the contract gate on this API" is "we do not
have a contract". The second most common is "we have a Postman collection" --
which for a great many teams is the only written description of their API that
exists.

This reads one into the flat entry shape `traffic.redact.import_har` produces,
so `infer` drafts a contract from it with the same engine, the same thresholds
and the same honesty markings. A second inference path would be a second set of
decisions about when a field is required, and the two would disagree.

## A collection is not traffic, and the draft has to say so

A HAR is a recording: those requests happened, in that order, at those times.
A collection is a **set of requests somebody saved**, and its saved responses
are examples somebody pasted -- possibly years ago, possibly by hand, possibly
from staging.

That difference matters to every threshold `infer` applies. "Present in all
four samples" means something about four observations and much less about four
examples one person typed. So:

- entries carry no timestamp, because a collection records none and inventing
  one would put a fabricated window in the draft's own description;
- `Import.note` says where the requests came from, and the caller puts it in
  the document;
- a request with no saved response produces an entry with a `None` body and a
  reason, exactly as `import_har` does when bodies are excluded -- so a reader
  can tell "nothing was returned" from "nobody saved one".

## What is read, and what is not

**Read:** nested folders (`item` groups, to any depth), `request.method`,
`request.url` in both its string and object forms, `header`, `body.raw` and
`body.urlencoded`, saved `response` entries with their `code` and `body`.

**Not read, and reported rather than dropped:**

| Construct | Why |
|---|---|
| `body.formdata`, `body.file` | A multipart upload's shape is not a JSON schema, and the file it names is not in the collection. |
| `body.graphql` | A GraphQL request is one POST to one endpoint; inferring REST operations from it would describe an API that does not exist. `apiverity` reads GraphQL SDL directly. |
| `auth`, `event` (pre-request and test scripts) | Scripts compute values at send time. What a script would have produced is not in the file. |
| `protocolProfileBehavior`, `proxy`, `certificate` | Transport settings, not contract. |

## Variables

`{{base_url}}/users/{{userId}}` is the normal shape of a collection URL. The
collection's own `variable` block is substituted where it has a value; anything
left unresolved stays as written and is reported, because a URL containing
`{{userId}}` would otherwise become a literal path segment and `infer` would
draft an operation at `/users/{{userId}}`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

#: Body modes this reads. The others are named in `Import.skipped` rather than
#: dropped -- see the module docstring.
READABLE_BODY_MODES = ("raw", "urlencoded")

#: `{{name}}`, the collection variable syntax.
_VARIABLE = "{{"


@dataclass
class Import:
    """The entries, and everything that did not survive the conversion."""

    entries: list[dict[str, Any]] = field(default_factory=list)
    #: Collection name, for the drafted document's title.
    name: str = ""
    #: What was in the collection and is not in the entries, each with a
    #: reason. Reported rather than dropped: a draft missing a third of an API
    #: because those requests used form bodies looks like an API with a third
    #: fewer endpoints.
    skipped: list[str] = field(default_factory=list)
    #: URLs still containing `{{...}}` after substitution. Left as written --
    #: guessing a value would draft an operation at a path nobody serves.
    unresolved: list[str] = field(default_factory=list)
    #: Requests with no saved response. Counted, because a draft with no
    #: response schemas is a different document from one whose responses were
    #: all empty.
    without_response: int = 0

    @property
    def note(self) -> str:
        """One line for the drafted document, saying what this came from."""
        return (
            f"Drafted from the Postman collection {self.name!r}: "
            f"{len(self.entries)} saved request(s). These are requests somebody saved, "
            "not traffic anybody observed -- there is no time window, and a saved "
            "response is an example rather than a recording."
        )


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _variables(collection: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for entry in collection.get("variable") or []:
        if isinstance(entry, dict) and entry.get("key") is not None:
            value = entry.get("value")
            if isinstance(value, str | int | float):
                out[str(entry["key"])] = str(value)
    return out


def _substitute(text: str, variables: dict[str, str]) -> str:
    for key, value in variables.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def _url(raw: Any, variables: dict[str, str]) -> str:
    """A URL from either form the schema allows.

    `raw` is preferred when present because it is what the author wrote; the
    object form is reassembled only when it is absent, and then from `protocol`,
    `host`, `port` and `path` exactly as the schema defines them.
    """
    if isinstance(raw, str):
        return _substitute(raw, variables)
    if not isinstance(raw, dict):
        return ""
    if isinstance(raw.get("raw"), str):
        return _substitute(raw["raw"], variables)

    protocol = _text(raw.get("protocol")) or "https"
    host = raw.get("host")
    host_text = ".".join(str(part) for part in host) if isinstance(host, list) else _text(host)
    port = raw.get("port")
    if port:
        host_text = f"{host_text}:{port}"
    path = raw.get("path")
    if isinstance(path, list):
        path_text = "/".join(str(part) for part in path)
    else:
        path_text = _text(path).lstrip("/")
    return _substitute(f"{protocol}://{host_text}/{path_text}", variables)


def _query(raw: Any, variables: dict[str, str]) -> dict[str, str]:
    """Query parameters, skipping the ones the author disabled.

    A disabled parameter is one somebody deliberately turned off. Carrying it
    into a draft would declare a parameter the collection says not to send.
    """
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for item in raw.get("query") or []:
        if not isinstance(item, dict) or item.get("disabled"):
            continue
        key = item.get("key")
        if key is None:
            continue
        out[str(key)] = _substitute(_text(item.get("value")), variables)
    return out


def _headers(raw: Any, variables: dict[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict) or item.get("disabled"):
                continue
            key = item.get("key")
            if key is None:
                continue
            out[str(key)] = _substitute(_text(item.get("value")), variables)
    return out


def _decode(text: str) -> Any:
    if not text.strip():
        return None
    try:
        return json.loads(text)
    except ValueError:
        # Not JSON. Kept as the string it is: `infer` types it as a string,
        # which is what it saw.
        return text


def _body(raw: Any, variables: dict[str, str], skipped: list[str], where: str) -> Any:
    if not isinstance(raw, dict):
        return None
    mode = _text(raw.get("mode"))
    if mode and mode not in READABLE_BODY_MODES:
        skipped.append(f"{where}: body mode {mode!r} is not read into the draft")
        return None
    if mode == "urlencoded":
        pairs = {}
        for item in raw.get("urlencoded") or []:
            if isinstance(item, dict) and item.get("key") is not None and not item.get("disabled"):
                pairs[str(item["key"])] = _substitute(_text(item.get("value")), variables)
        return pairs or None
    return _decode(_substitute(_text(raw.get("raw")), variables))


def _walk(items: Any, path: tuple[str, ...] = ()) -> list[tuple[tuple[str, ...], dict[str, Any]]]:
    """Every request in the tree, with the folder names above it.

    Folders nest to any depth, and a collection of forty requests in six
    folders is the normal shape. Flattening only the top level would draft a
    contract from whichever requests happened to be at the root.
    """
    found: list[tuple[tuple[str, ...], dict[str, Any]]] = []
    if not isinstance(items, list):
        return found
    for item in items:
        if not isinstance(item, dict):
            continue
        name = _text(item.get("name"))
        if isinstance(item.get("item"), list):
            found.extend(_walk(item["item"], (*path, name)))
        elif item.get("request") is not None:
            found.append(((*path, name), item))
    return found


#: The hosts Postman publishes its collection schemas on.
SCHEMA_HOSTS = frozenset({"schema.getpostman.com", "schema.postman.com"})


def _served_by_postman(url: str) -> bool:
    """True when `url`'s host is one Postman publishes its schemas on.

    The host is parsed rather than searched for. `"schema.postman.com" in url`
    also matches `https://example.invalid/?q=schema.postman.com`, and while
    nothing bad follows from misreading a file here -- it simply fails to parse
    a moment later -- the substring shape is the one that does real damage the
    first time somebody copies it into a check that decides something.
    """
    return (urlsplit(url).hostname or "").lower() in SCHEMA_HOSTS


def is_collection(document: Any) -> bool:
    """Does this look like a Postman collection?

    Keyed on the schema URL the format requires in `info.schema`, falling back
    to the two required top-level members. A JSON file with `info` and `item`
    and no schema URL is almost certainly a collection somebody hand-edited.
    """
    if not isinstance(document, dict):
        return False
    info = document.get("info")
    if not isinstance(info, dict):
        return False
    if _served_by_postman(_text(info.get("schema"))):
        return True
    return isinstance(document.get("item"), list)


def read(path: str | Path) -> Import:
    """Read a collection file into entries `infer` can draft from."""
    document = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not is_collection(document):
        raise ValueError(f"{path} is not a Postman collection (no `info` and `item`)")
    return convert(document)


def convert(document: dict[str, Any]) -> Import:
    info = document.get("info") if isinstance(document.get("info"), dict) else {}
    result = Import(name=_text((info or {}).get("name")) or "Postman collection")
    variables = _variables(document)

    for folders, item in _walk(document.get("item")):
        where = " / ".join(part for part in folders if part) or "(unnamed)"
        request = item.get("request")
        if isinstance(request, str):
            request = {"method": "GET", "url": request}
        if not isinstance(request, dict):
            result.skipped.append(f"{where}: request is not a URL or an object")
            continue

        url = _url(request.get("url"), variables)
        if not url:
            result.skipped.append(f"{where}: no URL")
            continue
        if _VARIABLE in url:
            # Left as written. Substituting a guess would draft an operation at
            # a path nobody serves, and dropping the request would quietly
            # shrink the API.
            result.unresolved.append(f"{where}: {url}")

        headers = _headers(request.get("header"), variables)
        body = _body(request.get("body"), variables, result.skipped, where)

        saved = [r for r in (item.get("response") or []) if isinstance(r, dict)]
        if not saved:
            result.without_response += 1
            result.entries.append(
                _entry(
                    request,
                    url,
                    headers,
                    body,
                    variables,
                    status=None,
                    response_body=None,
                    response_dropped="the collection saved no response for this request",
                    response_mime="",
                )
            )
            continue

        for response in saved:
            result.entries.append(
                _entry(
                    request,
                    url,
                    headers,
                    body,
                    variables,
                    status=response.get("code"),
                    response_body=_decode(_text(response.get("body"))),
                    response_dropped=None,
                    response_mime=_response_mime(response),
                )
            )
    return result


def _response_mime(response: dict[str, Any]) -> str:
    for header in response.get("header") or []:
        if isinstance(header, dict) and _text(header.get("key")).lower() == "content-type":
            return _text(header.get("value"))
    return ""


def _entry(
    request: dict[str, Any],
    url: str,
    headers: dict[str, str],
    body: Any,
    variables: dict[str, str],
    *,
    status: Any,
    response_body: Any,
    response_dropped: str | None,
    response_mime: str,
) -> dict[str, Any]:
    """One entry, in exactly the shape `import_har` produces.

    `started_at` and `elapsed_ms` are `None` rather than absent: a collection
    records neither, and a fabricated timestamp would put a window in the
    draft's description that nobody observed.
    """
    return {
        "method": (_text(request.get("method")) or "GET").upper(),
        "url": url,
        "request_headers": headers,
        "query": _query(request.get("url"), variables),
        "request_body": body,
        "request_body_dropped": None,
        "status": int(status) if isinstance(status, int) else None,
        "response_headers": {},
        "response_body": response_body,
        "response_body_dropped": response_dropped,
        "response_mime": response_mime,
        "started_at": None,
        "elapsed_ms": None,
    }


__all__ = ["READABLE_BODY_MODES", "Import", "convert", "is_collection", "read"]
