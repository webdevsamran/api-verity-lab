"""Resolve external `$ref`s into one document, before anything else reads it.

Why this is not optional
------------------------
A multi-file spec is the normal shape of a real OpenAPI document: an entry
file, a `schemas/` directory beside it, and often a `../../shared/` tree in a
monorepo. Until now every one of those refs produced `SPEC-REF-EXTERNAL` and
resolved to nothing -- so the schema behind it was absent from the model, and
every consequence followed from that absence rather than from an error. The
differ compared a field that was not there against a field that was not there
and reported no change; `validate_value` accepted anything at that position.

The finding was honest about the limitation. It was still the wrong outcome:
the tool declined to read a document that every other tool in this space reads.

What is refused, and why
------------------------
**Absolute filesystem paths.** A portable contract never contains one, so
refusing `/etc/passwd` or `C:\\Windows\\...` costs nothing real and closes the
blunt version of reading a file the *document* chose rather than the caller.

**Remote refs, unless asked for.** A `$ref` to `https://...` makes this process
request an address named by the document. That is the hazard
[`SAFETY_MODEL.md`](../../docs/safety-model.md) §1 exists for, so it sits
behind an explicit opt-in -- and when the opt-in is given, the fetch really
happens. A flag that silently changes nothing is worse than no flag.

Both refusals produce a finding naming the ref. Skipping one silently is what
produced the absent-schema problem in the first place.

Determinism
-----------
Bundled fragments are hoisted to `#/components/schemas/<name>`, named from the
file and pointer and disambiguated by a hash of the *relative* posix path. Two
machines bundling the same tree produce byte-identical output, which matters
because the result feeds a diff: generated names that depended on the absolute
path would make the next diff on a different checkout call every schema
renamed.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urljoin, urlparse

from apiverity.core.model import Finding, Severity, SourceLocation

#: A ref cycle across files, or a directory of thousands of fragments, must not
#: turn a `validate` into an unbounded read. Both caps report when they are
#: hit, and never apply silently.
DEFAULT_MAX_FILES = 200
DEFAULT_MAX_DEPTH = 20

#: Remote fetches get their own budget. It is smaller because each one is a
#: network request to an address the caller did not type.
DEFAULT_MAX_REMOTE = 20
REMOTE_TIMEOUT_SECONDS = 15.0

_SAFE_NAME = re.compile(r"[^A-Za-z0-9_.-]+")


@dataclass
class BundleResult:
    """The bundled document, and everything the run established about it."""

    document: dict[str, Any]
    findings: list[Finding] = field(default_factory=list)
    #: Sources actually read, entry document first, in the order they were read.
    files: list[str] = field(default_factory=list)
    #: `id(node)` -> the source that node came from, so a finding inside an
    #: included file is reported against *that* file, not against the entry.
    origins: dict[int, str] = field(default_factory=dict)
    #: Line/column index merged across every file read, the same shape as the
    #: single-file one the parser already keeps.
    lines: dict[int, tuple[int, int]] = field(default_factory=dict)
    #: External refs rewritten to local ones: original -> new.
    rewritten: dict[str, str] = field(default_factory=dict)

    @property
    def external_count(self) -> int:
        return len(self.rewritten)


def _split_ref(ref: str) -> tuple[str, str]:
    """`path#/pointer` -> (path, pointer). A bare path means the whole file."""
    location, _, pointer = ref.partition("#")
    return location, pointer


def _is_remote(location: str) -> bool:
    return location.startswith(("http://", "https://"))


def _is_absolute(location: str) -> bool:
    """True for a filesystem path relative to nothing.

    Checked as a string rather than with `Path.is_absolute`, because a POSIX
    runner reading a Windows-authored spec must still refuse `C:\\...`: the
    hazard belongs to the document, not to the platform reading it.
    """
    if location.startswith(("/", "\\")):
        return True
    return len(location) > 2 and location[1] == ":" and location[2] in "/\\"


def _resolve_pointer(document: Any, pointer: str) -> tuple[Any, str | None]:
    """Follow a JSON pointer. Returns (node, error)."""
    if not pointer or pointer == "/":
        return document, None
    node = document
    for raw in pointer.lstrip("/").split("/"):
        part = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict):
            if part not in node:
                return None, f"missing segment '{part}'"
            node = node[part]
        elif isinstance(node, list):
            try:
                node = node[int(part)]
            except (ValueError, IndexError):
                return None, f"no index '{part}'"
        else:
            return None, "traversal dead-end"
    return node, None


def _component_name(relative: str, pointer: str) -> str:
    """A deterministic, collision-resistant name for a hoisted fragment.

    A readable half from the file and pointer, so a bundled document can still
    be read by a person, and a hashed half from the relative posix path, so two
    files both named `user.yaml` in different directories do not collide.
    """
    tail = pointer.rstrip("/").rsplit("/", 1)[-1] if pointer else ""
    stem = PurePosixPath(relative).stem
    readable = "_".join(part for part in (stem, tail) if part) or "external"
    readable = _SAFE_NAME.sub("_", readable).strip("_")
    digest = hashlib.sha256(f"{relative}#{pointer}".encode()).hexdigest()[:8]
    return f"{readable}_{digest}"


class _Bundler:
    """Origins are plain strings: either a URL or a filesystem path.

    Keeping one type for both is what makes a relative ref inside a fetched
    document resolve against the URL it came from rather than against the
    working directory -- which is what the JSON Reference specification says,
    and the difference between bundling a remote tree and silently reading the
    wrong local files.
    """

    def __init__(
        self,
        *,
        base: str,
        allow_remote: bool,
        max_files: int,
        max_depth: int,
        max_remote: int,
        read_lines: Any,
        fetch: Any,
    ) -> None:
        self.base = base
        self.root = Path(base).resolve().parent if not _is_remote(base) else None
        self.allow_remote = allow_remote
        self.max_files = max_files
        self.max_depth = max_depth
        self.max_remote = max_remote
        self.read_lines = read_lines
        self.fetch = fetch
        self.result = BundleResult(document={})
        self._documents: dict[str, Any] = {}
        self._remote_reads = 0
        #: resolved "source#pointer" -> generated component name, so a fragment
        #: referenced from five places is hoisted once.
        self._hoisted: dict[str, str] = {}
        self._capped = False

    # -- naming ----------------------------------------------------------

    def _label(self, source: str) -> str:
        """A short, checkout-independent name for a source."""
        if _is_remote(source):
            parsed = urlparse(source)
            return f"{parsed.netloc}{parsed.path}"
        path = Path(source).resolve()
        if self.root is not None:
            try:
                return path.relative_to(self.root).as_posix()
            except ValueError:
                pass
        # Outside the entry document's directory -- legitimate in a monorepo
        # (`../../shared/user.yaml`). The name still has to be stable across
        # checkouts, so the drive/root prefix is dropped rather than kept.
        return PurePosixPath(*path.parts[1:]).as_posix()

    def _join(self, origin: str, location: str) -> str:
        """Resolve `location` against the source that referenced it."""
        if _is_remote(location):
            # An absolute URL is already resolved. Without this it would be
            # appended to a local directory and read as a file that cannot
            # exist, turning a refused fetch into a confusing "file not found".
            return location
        if _is_remote(origin):
            return urljoin(origin, location)
        return str((Path(origin).parent / location).resolve())

    # -- reading ---------------------------------------------------------

    def _load(self, source: str, pointer: str) -> Any:
        if source in self._documents:
            return self._documents[source]
        if len(self._documents) >= self.max_files:
            if not self._capped:
                self._capped = True
                self._finding(
                    "SPEC-REF-BUNDLE-CAPPED",
                    Severity.WARN,
                    f"stopped after reading {self.max_files} referenced documents; refs "
                    "beyond this point are unresolved, and the schemas behind them are "
                    "absent from the model rather than merely unchecked",
                    pointer,
                )
            return None

        text = self._read_text(source, pointer)
        if text is None:
            self._documents[source] = None
            return None

        document, lines = self.read_lines(text)
        if not document:
            from apiverity.specs import parse_document

            try:
                document = parse_document(text.encode("utf-8"))
            except ValueError as exc:
                self._finding(
                    "SPEC-REF-UNREADABLE",
                    Severity.ERROR,
                    f"referenced document '{source}' is not a JSON or YAML mapping: {exc}",
                    pointer,
                )
                self._documents[source] = None
                return None
            lines = {}

        label = self._label(source)
        self._documents[source] = document
        self.result.files.append(label)
        self.result.lines.update(lines)
        self._mark_origin(document, label)
        return document

    def _read_text(self, source: str, pointer: str) -> str | None:
        if _is_remote(source):
            if self._remote_reads >= self.max_remote:
                self._finding(
                    "SPEC-REF-BUNDLE-CAPPED",
                    Severity.WARN,
                    f"stopped after {self.max_remote} remote fetches; '{source}' was not read",
                    pointer,
                )
                return None
            self._remote_reads += 1
            try:
                return str(self.fetch(source))
            except Exception as exc:
                self._finding(
                    "SPEC-REF-UNREADABLE",
                    Severity.ERROR,
                    f"remote reference '{source}' could not be fetched: {exc}",
                    pointer,
                )
                return None
        try:
            return Path(source).read_bytes().decode("utf-8-sig")
        except OSError as exc:
            self._finding(
                "SPEC-REF-UNREADABLE",
                Severity.ERROR,
                f"referenced file '{source}' could not be read: {exc}",
                pointer,
            )
            return None

    def _mark_origin(self, node: Any, origin: str) -> None:
        """Record which source every node in a subtree came from.

        Keyed by `id`, the technique the parser's line index already uses, and
        safe for the same reason: the bundled document is held for the whole
        parse, so nothing here is collected and no id is reused.
        """
        stack = [node]
        while stack:
            current = stack.pop()
            if isinstance(current, dict):
                self.result.origins.setdefault(id(current), origin)
                stack.extend(current.values())
            elif isinstance(current, list):
                self.result.origins.setdefault(id(current), origin)
                stack.extend(current)

    def _finding(self, rule_id: str, severity: Severity, message: str, pointer: str) -> None:
        self.result.findings.append(
            Finding(
                rule_id=rule_id,
                severity=severity,
                message=message,
                location=SourceLocation(file=self._label(self.base), pointer=pointer),
            )
        )

    # -- walking ---------------------------------------------------------

    def run(self, document: dict[str, Any]) -> BundleResult:
        self.result.document = document
        self._documents[self.base] = document
        self.result.files.append(self._label(self.base))
        self._walk(document, self.base, "", depth=0)
        return self.result

    def _walk(self, node: Any, origin: str, pointer: str, *, depth: int) -> None:
        if depth > self.max_depth:
            self._finding(
                "SPEC-REF-BUNDLE-CAPPED",
                Severity.WARN,
                f"stopped following references at depth {self.max_depth}; anything deeper "
                "is unresolved",
                pointer,
            )
            return
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and not ref.startswith("#"):
                replacement = self._hoist(ref, origin, pointer, depth=depth)
                if replacement is not None:
                    node["$ref"] = replacement
                    self.result.rewritten[ref] = replacement
                # Siblings of a `$ref` are ignored by the parser anyway, so
                # nothing below this node needs walking.
                return
            # Snapshotted: hoisting writes into `components.schemas`, which
            # may be the very dict being walked. Each hoisted fragment is
            # walked by `_hoist` itself, so nothing is missed by iterating a
            # copy.
            for key, value in list(node.items()):
                self._walk(value, origin, f"{pointer}/{key}", depth=depth + 1)
        elif isinstance(node, list):
            for index, value in enumerate(list(node)):
                self._walk(value, origin, f"{pointer}/{index}", depth=depth + 1)

    def _hoist(self, ref: str, origin: str, pointer: str, *, depth: int) -> str | None:
        """Pull one external fragment into the entry document's components."""
        location, fragment = _split_ref(ref)
        if not location:
            return None  # `#/...` is the parser's job; nothing external here

        if _is_remote(location) and not self.allow_remote:
            self._finding(
                "SPEC-REF-REMOTE-REFUSED",
                Severity.WARN,
                f"remote reference '{ref}' was not fetched. A URL in a document makes this "
                "process request an address the caller did not choose; pass "
                "--allow-remote-refs to permit it",
                pointer,
            )
            return None

        if _is_absolute(location):
            self._finding(
                "SPEC-REF-ABSOLUTE-REFUSED",
                Severity.ERROR,
                f"reference '{ref}' names an absolute filesystem path. A portable contract "
                "never contains one, and reading a file the document chose rather than the "
                "caller is not something this tool does",
                pointer,
            )
            return None

        target = self._join(origin, location)
        if _is_remote(target) and not self.allow_remote:
            # A relative ref inside a fetched document is still a fetch.
            self._finding(
                "SPEC-REF-REMOTE-REFUSED",
                Severity.WARN,
                f"reference '{ref}' resolves to '{target}', which is a network fetch; pass "
                "--allow-remote-refs to permit it",
                pointer,
            )
            return None

        key = f"{self._label(target)}#{fragment}"
        existing = self._hoisted.get(key)
        if existing is not None:
            return f"#/components/schemas/{existing}"

        document = self._load(target, pointer)
        if document is None:
            return None

        node, error = _resolve_pointer(document, fragment)
        if error is not None:
            self._finding(
                "SPEC-REF-UNRESOLVED",
                Severity.ERROR,
                f"reference '{ref}' does not resolve inside '{self._label(target)}': {error}",
                pointer,
            )
            return None

        schemas = self._schema_table(pointer)
        if schemas is None:
            return None

        name = _component_name(self._label(target), fragment)
        # Reserved before walking, so a fragment that refers back to itself
        # across files terminates instead of recursing.
        self._hoisted[key] = name
        schemas[name] = node
        self._walk(node, target, f"/components/schemas/{name}", depth=depth + 1)
        return f"#/components/schemas/{name}"

    def _schema_table(self, pointer: str) -> dict[str, Any] | None:
        components = self.result.document.setdefault("components", {})
        if not isinstance(components, dict):
            self._finding(
                "SPEC-REF-UNRESOLVED",
                Severity.ERROR,
                "`components` is not a mapping, so external references cannot be bundled",
                pointer,
            )
            return None
        schemas = components.setdefault("schemas", {})
        if not isinstance(schemas, dict):
            self._finding(
                "SPEC-REF-UNRESOLVED",
                Severity.ERROR,
                "`components.schemas` is not a mapping, so external references cannot be bundled",
                pointer,
            )
            return None
        return schemas


def _default_fetch(url: str) -> str:
    import httpx

    response = httpx.get(url, timeout=REMOTE_TIMEOUT_SECONDS, follow_redirects=True)
    response.raise_for_status()
    return response.text


def bundle(
    document: dict[str, Any],
    *,
    base: str | Path,
    allow_remote: bool = False,
    max_files: int = DEFAULT_MAX_FILES,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_remote: int = DEFAULT_MAX_REMOTE,
    read_lines: Any = None,
    fetch: Any = None,
) -> BundleResult:
    """Rewrite external `$ref`s in `document` into local ones, in place.

    `base` is the entry document's path or URL. Relative refs resolve against
    whichever document contains them, which is what the JSON Reference
    specification says and what every multi-file spec in the wild assumes.

    `read_lines` is the parser's YAML loader, injected rather than imported so
    this module does not depend on the parser that calls it. It returns
    `(document, line_index)`.
    """
    if read_lines is None:

        def read_lines(text: str) -> tuple[dict[str, Any], dict[int, tuple[int, int]]]:
            from apiverity.specs.openapi.parser import load_yaml_with_lines

            return load_yaml_with_lines(text)

    return _Bundler(
        base=str(base),
        allow_remote=allow_remote,
        max_files=max_files,
        max_depth=max_depth,
        max_remote=max_remote,
        read_lines=read_lines,
        fetch=fetch or _default_fetch,
    ).run(document)


__all__ = [
    "DEFAULT_MAX_DEPTH",
    "DEFAULT_MAX_FILES",
    "DEFAULT_MAX_REMOTE",
    "BundleResult",
    "bundle",
]
