"""The image was a server, and the CLI in it was undocumented and untested.

Running the CLI did work -- Docker replaces `CMD` with whatever follows the
image name, and `pip install .` puts the console script on PATH -- but nothing
said so, nothing exercised it, and it meant typing `apiverity` again after an
image already named that. The entrypoint dispatches now.

These tests do not build the image. They read the Dockerfile and *run the
entrypoint script*, which is the part with the logic in it: a shell script that
dispatches on `$1` is exactly the kind of thing that is wrong in a way nobody
notices until a user tries the second documented command.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_DOCKERFILE = _ROOT / "Dockerfile"
_ENTRYPOINT = _ROOT / "docker" / "entrypoint.sh"

_SH = shutil.which("sh") or shutil.which("bash")
needs_sh = pytest.mark.skipif(_SH is None, reason="no POSIX shell on this machine")


def _dockerfile() -> str:
    return _DOCKERFILE.read_text(encoding="utf-8")


# ------------------------------------------------------------- the image


def test_the_image_declares_an_entrypoint() -> None:
    """Without one, the only way in is to repeat the image's own name."""
    text = _dockerfile()
    assert 'ENTRYPOINT ["apiverity-entrypoint"]' in text
    assert 'CMD ["serve"]' in text


def test_serving_is_still_the_default() -> None:
    """The existing published image starts a server, and people have that in
    their compose files. Changing what a bare `docker run` does would break
    them for a feature they did not ask for."""
    assert 'CMD ["serve"]' in _dockerfile()


def test_the_working_directory_is_where_contracts_get_mounted() -> None:
    """`-v "$PWD:/work"` has to land somewhere the CLI already looks."""
    text = _dockerfile()
    assert "WORKDIR /work" in text
    assert "/work" in text


def test_the_mount_point_is_owned_by_the_user_the_image_runs_as() -> None:
    """Otherwise the CLI's first useful invocation is a permission error."""
    text = _dockerfile()
    assert "chown verity:verity /data /work" in text
    assert "USER verity" in text


def test_the_image_does_not_run_as_root() -> None:
    text = _dockerfile()
    assert text.index("USER verity") < text.index("ENTRYPOINT")


def test_cors_origins_are_configurable_and_default_to_none() -> None:
    """The dashboard needs them; a server that answers every origin by default
    is one whose operator never chose to."""
    assert "VERITY_CORS_ORIGINS" in _dockerfile()
    assert "VERITY_CORS_ORIGINS" in _ENTRYPOINT.read_text(encoding="utf-8")


def test_every_environment_variable_the_entrypoint_reads_is_documented() -> None:
    """A variable the image honours and the header does not mention is one
    nobody sets."""
    import re

    entrypoint = _ENTRYPOINT.read_text(encoding="utf-8")
    used = set(re.findall(r"VERITY_[A-Z_]+", entrypoint))
    documented = set(re.findall(r"VERITY_[A-Z_]+", _dockerfile()))
    assert used <= documented, f"undocumented: {sorted(used - documented)}"


# --------------------------------------------------------- the dispatch


@needs_sh
def test_the_script_is_valid_posix_shell() -> None:
    """`/bin/sh` in a slim image is not bash, and a bashism fails on the shell
    rather than on the command -- which reads as the image being broken."""
    result = subprocess.run([str(_SH), "-n", str(_ENTRYPOINT)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@needs_sh
def _run(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run the entrypoint with a stand-in `apiverity` on PATH."""
    stub = tmp_path / "bin"
    stub.mkdir(exist_ok=True)
    script = stub / "apiverity"
    script.write_text('#!/bin/sh\necho "ARGS:$*"\n', encoding="utf-8")
    script.chmod(0o755)

    env = dict(os.environ)
    env["PATH"] = f"{stub}{os.pathsep}{env['PATH']}"
    return subprocess.run(
        [str(_SH), str(_ENTRYPOINT), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


@needs_sh
def test_a_subcommand_reaches_the_cli(tmp_path: Path) -> None:
    result = _run(tmp_path, "breaking", "old.yaml", "new.yaml")
    assert "ARGS:breaking old.yaml new.yaml" in result.stdout


@needs_sh
def test_a_flag_reaches_the_cli(tmp_path: Path) -> None:
    """`docker run IMAGE --help` is the first thing anyone types."""
    result = _run(tmp_path, "--help")
    assert "ARGS:--help" in result.stdout


@needs_sh
def test_arguments_with_spaces_survive(tmp_path: Path) -> None:
    """An unquoted `$*` would split them, and a contract path with a space in
    it is an ordinary contract path."""
    result = _run(tmp_path, "validate", "my contracts/openapi.yaml")
    assert "my contracts/openapi.yaml" in result.stdout


@needs_sh
def test_serve_does_not_reach_the_cli(tmp_path: Path) -> None:
    """It is the one word that means something else. `apiverity serve` is a
    real subcommand -- serving a bundle over HTTP -- and routing the container's
    default to it would start the wrong thing."""
    result = _run(tmp_path, "serve")
    assert "ARGS:" not in result.stdout


@pytest.mark.skipif(sys.platform == "win32", reason="the mode bit is not meaningful on Windows")
def test_the_script_is_executable() -> None:
    assert os.access(_ENTRYPOINT, os.X_OK)
