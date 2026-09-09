"""api-verity-lab: unified API contract governance and reliability testing."""

from __future__ import annotations


def _installed_version() -> str:
    """The version actually installed, not a literal in this file.

    This was hardcoded to "0.1.0" while ``pyproject.toml`` said 0.2.0, so
    ``apiverity --version`` (which the bug-report template asks reporters to
    run) would have reported a release that does not exist. Deriving it from
    the distribution's own metadata makes that drift unrepresentable.
    """
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("api-verity-lab")
    except PackageNotFoundError:  # source tree, not installed
        import pathlib

        pyproject = pathlib.Path(__file__).resolve().parent.parent / "pyproject.toml"
        try:
            import tomllib

            return str(tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"])
        except Exception:
            return "unknown"


__version__ = _installed_version()

PLUGIN_API_VERSION = "1"
