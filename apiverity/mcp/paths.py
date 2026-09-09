"""Path confinement for the MCP server.

Every tool this server exposes takes a file path chosen by a model. Without a
root, a spec-path argument is unrestricted read access to the filesystem
dressed up as a contract check.

The subtlety is not the check, it is what the check returns. `detect_and_load`
reads the caller's string **twice** -- once in `specs/loader.py` to sniff the
format, and again inside the winning plugin's `load()` -- and each read does
`Path(source).read_bytes()`. Validating a candidate and then passing the
original string onward is therefore not confinement at all: the resolved path
is the safe one, and the resolved path is what has to travel.
"""

from __future__ import annotations

from pathlib import Path


class PathRefused(ValueError):
    """A path was refused, with a message safe to hand back to a model."""


def resolve_within(root: Path, candidate: str) -> Path:
    """Resolve `candidate` under `root`, or refuse.

    Refuses remote sources outright. `specs.read_source` accepts `http://` and
    `https://` and will fetch them, which in a server documented as making no
    network calls is a server-side request forgery hole reachable through an
    argument a model chooses.
    """
    if candidate.startswith(("http://", "https://")):
        raise PathRefused(
            "remote sources are not accepted; this server reads files under its "
            "configured root and makes no network requests"
        )

    root = root.resolve()
    try:
        resolved = (
            (root / candidate).resolve()
            if not Path(candidate).is_absolute()
            else Path(candidate).resolve()
        )
    except OSError as exc:  # pragma: no cover - platform dependent
        raise PathRefused("path could not be resolved") from exc

    # `is_relative_to` rather than a string prefix: "/srv/rootkit" starts with
    # "/srv/root" as text and is a different directory.
    if not resolved.is_relative_to(root):
        raise PathRefused(
            "path is outside the configured root; this server only reads files beneath it"
        )
    return resolved


def relative_label(root: Path, path: Path) -> str:
    """How a path is named back to the caller.

    Always relative to the root. An error carrying an absolute path discloses
    the operator's directory layout to the model on every typo, which is the
    same class of leak as echoing exception text over HTTP.
    """
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:  # pragma: no cover - resolve_within already refused
        return "<outside root>"
