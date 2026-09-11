"""The one-line install, exercised rather than described.

An installer is the piece of a project most likely to be written once and never
run again, and the one whose failure the author never sees: it runs on machines
that do not have the project on them.

So these tests stand up a fake release -- a real wheel, a real HTTP server
speaking the shape of GitHub's releases API -- and run the installer against it:
resolution, download, checksum verification, and the refusal when the bytes do
not match.

The shell bootstraps are run too, each on the platform it belongs to. `sh` and
PowerShell are not both present everywhere, and CI's `platform-matrix` job runs
this suite on ubuntu, macos and windows, so each script is exercised somewhere
on every pull request.
"""

from __future__ import annotations

import hashlib
import http.server
import json
import shutil
import subprocess
import sys
import threading
import zipfile
from collections.abc import Iterator
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_INSTALLER = _ROOT / "scripts" / "install.py"
_SH = _ROOT / "install.sh"
_PS1 = _ROOT / "install.ps1"

sys.path.insert(0, str(_ROOT / "scripts"))

WHEEL_NAME = "api_verity_lab-9.9.9-py3-none-any.whl"


def _wheel(directory: Path) -> Path:
    """A real wheel -- a zip with a dist-info -- not a file full of zeros.

    The installer hands this to `uv`, `pipx` or `pip`, and a fixture those tools
    reject would make the download path untestable end to end.
    """
    path = directory / WHEEL_NAME
    info = "api_verity_lab-9.9.9.dist-info"
    names = [
        "apiverity_stub/__init__.py",
        info + "/METADATA",
        info + "/WHEEL",
        info + "/RECORD",
    ]
    bodies = {
        names[0]: "",
        names[1]: "Metadata-Version: 2.1\nName: api-verity-lab\nVersion: 9.9.9\n",
        names[2]: (
            "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
        ),
        # pip refuses a wheel with no RECORD -- "Could not install packages due
        # to an OSError: RECORD" -- so a fixture without one would fail the
        # end-to-end install test for a reason that is not the installer's.
        names[3]: "".join(name + ",,\n" for name in names),
    }
    with zipfile.ZipFile(path, "w") as archive:
        for name in names:
            archive.writestr(name, bodies[name])
    return path


class _Body:
    """What `urlopen` returns, as much of it as `download` uses."""

    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def __enter__(self) -> _Body:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return self.payload


class _Release:
    """A fake GitHub releases API plus the asset it points at."""

    def __init__(self, root: Path, *, digest: str | None, corrupt: bool = False) -> None:
        self.root = root
        self.digest = digest
        self.corrupt = corrupt
        self.port = 0

    def _payload(self) -> dict:
        asset: dict[str, object] = {
            "name": WHEEL_NAME,
            "browser_download_url": f"http://127.0.0.1:{self.port}/dl/{WHEEL_NAME}",
        }
        if self.digest is not None:
            asset["digest"] = f"sha256:{self.digest}"
        return {"tag_name": "v9.9.9", "assets": [asset]}

    def handler(self) -> type[http.server.BaseHTTPRequestHandler]:
        release = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_: object) -> None:  # keep the test output readable
                return

            def do_GET(self) -> None:
                if self.path.endswith(".whl"):
                    body = (release.root / WHEEL_NAME).read_bytes()
                    if release.corrupt:
                        body += b"tampered"
                    self.send_response(200)
                    self.send_header("Content-Type", "application/octet-stream")
                elif self.path.endswith(("/releases/latest", "/releases/tags/v9.9.9")):
                    body = json.dumps(release._payload()).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                else:
                    self.send_response(404)
                    self.send_header("Content-Type", "application/json")
                    body = b'{"message":"Not Found"}'
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        return Handler


@pytest.fixture
def serving(tmp_path: Path) -> Iterator[tuple[str, Path]]:
    """`(api_base, wheel_path)` for a release whose digest is the truth."""
    yield from _serve(tmp_path, corrupt=False, declare_digest=True)


@pytest.fixture
def serving_corrupt(tmp_path: Path) -> Iterator[tuple[str, Path]]:
    """The same release, serving bytes that do not match the declared digest."""
    yield from _serve(tmp_path, corrupt=True, declare_digest=True)


@pytest.fixture
def serving_undeclared(tmp_path: Path) -> Iterator[tuple[str, Path]]:
    """A release from before GitHub's API reported asset digests."""
    yield from _serve(tmp_path, corrupt=False, declare_digest=False)


def _serve(tmp_path: Path, *, corrupt: bool, declare_digest: bool) -> Iterator[tuple[str, Path]]:
    wheel = _wheel(tmp_path)
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest() if declare_digest else None
    release = _Release(tmp_path, digest=digest, corrupt=corrupt)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), release.handler())
    release.port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{release.port}", wheel
    finally:
        server.shutdown()
        server.server_close()


def _install_py(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(_INSTALLER), *args], capture_output=True, text=True)


# -- resolution and verification -----------------------------------------


def test_the_wheel_is_resolved_downloaded_and_verified(serving: tuple[str, Path]) -> None:
    api, wheel = serving
    result = _install_py("--api", api, "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "v9.9.9" in result.stdout
    assert hashlib.sha256(wheel.read_bytes()).hexdigest() in result.stdout
    assert "matches the release" in result.stdout
    assert "nothing installed" in result.stdout


def test_bytes_that_do_not_match_the_digest_are_refused(serving_corrupt: tuple[str, Path]) -> None:
    """The whole reason to hash the download. A mismatch installs nothing, and
    says so, rather than handing the bytes to pip and hoping."""
    api, _ = serving_corrupt
    result = _install_py("--api", api, "--dry-run")
    assert result.returncode == 1
    assert "checksum mismatch" in result.stderr
    assert "Nothing was installed" in result.stderr


def test_a_release_with_no_declared_digest_says_nothing_was_compared(
    serving_undeclared: tuple[str, Path],
) -> None:
    """GitHub added the digest field after this project's first release. An
    older release still installs -- treating a gap in GitHub's metadata as
    evidence of tampering would be wrong -- but the output must not leave the
    reader believing a check happened."""
    api, _ = serving_undeclared
    result = _install_py("--api", api, "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "the release declares none, so nothing was compared" in result.stdout


def test_a_dropped_connection_is_retried_rather_than_fatal(tmp_path: Path) -> None:
    """Release downloads redirect to a CDN, and a reset connection or a timed
    out TLS handshake there is common -- it happened while this was being
    written. One attempt turns a blip into "the installer is broken"."""
    from install import InstallError, download

    calls = {"n": 0}

    def flaky(request: object, timeout: float = 0) -> object:
        calls["n"] += 1
        if calls["n"] < 3:
            raise OSError("connection reset by peer")
        return _Body(b"payload")

    import install

    original = install.urllib.request.urlopen
    install.urllib.request.urlopen = flaky  # type: ignore[assignment]
    try:
        path = download("http://example.invalid/x.whl", tmp_path, pause=0)
        assert path.read_bytes() == b"payload"
        assert calls["n"] == 3

        # And it gives up rather than looping: an endpoint that is simply gone
        # is not something more attempts will fix.
        calls["n"] = -100
        with pytest.raises(InstallError, match="connection reset"):
            download("http://example.invalid/x.whl", tmp_path, attempts=2, pause=0)
    finally:
        install.urllib.request.urlopen = original  # type: ignore[assignment]


def test_an_http_error_is_not_retried(tmp_path: Path) -> None:
    """A 404 is an answer. Retrying one is waiting for a file that is not
    there, three times, before saying so."""
    import urllib.error

    import install
    from install import InstallError, download

    calls = {"n": 0}

    def gone(request: object, timeout: float = 0) -> object:
        calls["n"] += 1
        raise urllib.error.HTTPError("http://example.invalid/x.whl", 404, "Not Found", {}, None)

    original = install.urllib.request.urlopen
    install.urllib.request.urlopen = gone  # type: ignore[assignment]
    try:
        with pytest.raises(InstallError, match="HTTP 404"):
            download("http://example.invalid/x.whl", tmp_path, pause=0)
    finally:
        install.urllib.request.urlopen = original  # type: ignore[assignment]
    assert calls["n"] == 1


def test_a_named_version_is_fetched_by_tag(serving: tuple[str, Path]) -> None:
    api, _ = serving
    assert _install_py("--api", api, "--version", "v9.9.9", "--dry-run").returncode == 0
    # Without the `v`, too: people type the number they see in a changelog.
    assert _install_py("--api", api, "--version", "9.9.9", "--dry-run").returncode == 0


def test_a_version_that_does_not_exist_says_so(serving: tuple[str, Path]) -> None:
    api, _ = serving
    result = _install_py("--api", api, "--version", "v0.0.1", "--dry-run")
    assert result.returncode == 1
    assert "404" in result.stderr


def test_a_release_with_no_wheel_is_an_error_not_an_sdist_fallback() -> None:
    """Installing from an sdist builds on the target machine, which needs a
    toolchain this script never checked for and cannot install. Failing with
    the git command is more useful than failing inside a compiler."""
    from install import InstallError, wheel_asset

    with pytest.raises(InstallError) as exc:
        wheel_asset({"tag_name": "v1", "assets": [{"name": "api_verity_lab-1.tar.gz"}]})
    assert "has no wheel" in str(exc.value)
    assert "git+https://" in str(exc.value)


def test_the_install_command_matches_the_method() -> None:
    from install import in_virtualenv, install_command

    wheel = Path("x.whl")
    assert install_command("uv", wheel)[:3] == ["uv", "tool", "install"]
    assert install_command("pipx", wheel)[:2] == ["pipx", "install"]
    assert install_command("pip", wheel)[:4] == [sys.executable, "-m", "pip", "install"]
    # `--user` inside an activated virtualenv is a hard error, and running an
    # installer inside one is an ordinary thing to do.
    assert ("--user" in install_command("pip", wheel)) is not in_virtualenv()
    # Re-running a piped-URL installer means "upgrade me", not "tell me it is
    # already there".
    for method in ("uv", "pipx"):
        assert "--force" in install_command(method, wheel)
    assert "--upgrade" in install_command("pip", wheel)


# -- installing for real --------------------------------------------------


def test_pip_actually_installs_the_downloaded_wheel(
    serving: tuple[str, Path], tmp_path: Path
) -> None:
    """End to end, into a throwaway environment: resolve, download, verify,
    install. Everything above this proves the installer decided correctly; this
    proves the decision reaches `pip`."""
    venv = tmp_path / "venv"
    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True, capture_output=True)
    python = venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")

    api, _ = serving
    result = subprocess.run(
        [str(python), str(_INSTALLER), "--api", api, "--method", "pip"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    installed = subprocess.run(
        [str(python), "-c", "import apiverity_stub; print('ok')"],
        capture_output=True,
        text=True,
    )
    assert installed.stdout.strip() == "ok", installed.stderr


# -- the shell bootstraps -------------------------------------------------


def test_the_posix_bootstrap_runs_the_installer(serving: tuple[str, Path], tmp_path: Path) -> None:
    """`install.sh` fetches `scripts/install.py` from a raw.githubusercontent
    URL, which a test must not depend on. The local copy is substituted, and
    what is checked is the rest: the interpreter search, the argument
    pass-through, and the temp directory it must not leave behind."""
    sh = shutil.which("sh") or shutil.which("bash")
    if sh is None:
        pytest.skip("no POSIX shell here; ci.yml runs this suite on ubuntu and macos")

    script = (tmp_path / "install.sh").with_suffix(".sh")
    body = _SH.read_text(encoding="utf-8").replace(
        'RAW="https://raw.githubusercontent.com/webdevsamran/api-verity-lab/${REF}/scripts/install.py"',
        f'RAW="file://{_INSTALLER.as_posix()}"',
    )
    # `curl file://` works; `wget file://` does not, and the substitution above
    # is a test fixture rather than something the script does in the field.
    script.write_text(
        body.replace(
            "  if command -v curl",
            '  if command -v cp >/dev/null 2>&1; then\n    cp "${1#file://}" "$2"\n  elif command -v curl',
        ),
        encoding="utf-8",
    )

    api, wheel = serving
    result = subprocess.run(
        [sh, str(script), "--api", api, "--dry-run"],
        capture_output=True,
        text=True,
        env={"PATH": _path_for(sh), "VERITY_PYTHON": sys.executable, "SYSTEMROOT": _systemroot()},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert hashlib.sha256(wheel.read_bytes()).hexdigest() in result.stdout


def test_the_posix_bootstrap_refuses_when_no_new_enough_python_exists(tmp_path: Path) -> None:
    sh = shutil.which("sh") or shutil.which("bash")
    if sh is None:
        pytest.skip("no POSIX shell here; ci.yml runs this suite on ubuntu and macos")

    fake = tmp_path / "python3"
    fake.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    fake.chmod(0o755)

    result = subprocess.run(
        [sh, str(_SH)],
        capture_output=True,
        text=True,
        env={"PATH": str(tmp_path), "SYSTEMROOT": _systemroot()},
    )
    assert result.returncode == 2
    assert "Python 3.11 or newer" in result.stderr
    # The useful half: what to do about it.
    assert "VERITY_PYTHON" in result.stderr


def test_the_windows_bootstrap_runs_the_installer(
    serving: tuple[str, Path], tmp_path: Path
) -> None:
    powershell = shutil.which("pwsh") or shutil.which("powershell")
    if powershell is None:
        pytest.skip("no PowerShell here; ci.yml runs this suite on windows-latest")

    script = tmp_path / "install.ps1"
    body = _PS1.read_text(encoding="utf-8").replace(
        "    Invoke-WebRequest -Uri $raw -OutFile $script -UseBasicParsing",
        f"    Copy-Item -Path '{_INSTALLER}' -Destination $script",
    )
    script.write_text(body, encoding="utf-8")

    api, wheel = serving
    result = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            # `-Command`, not `-File`: in -File mode PowerShell hands every
            # remaining token over as one literal string, so an array parameter
            # arrives as a single comma-joined element.
            "-Command",
            f"& '{script}' -Python '{sys.executable}' -Arguments '--api','{api}','--dry-run'",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert hashlib.sha256(wheel.read_bytes()).hexdigest() in result.stdout


# -- the two scripts and the docs agree -----------------------------------


def test_both_bootstraps_name_the_same_repository_and_floor() -> None:
    """Two scripts doing the same job in two languages is exactly where a
    repository rename or a version bump gets applied to one of them."""
    sh = _SH.read_text(encoding="utf-8")
    ps1 = _PS1.read_text(encoding="utf-8")
    for text in (sh, ps1):
        assert "webdevsamran/api-verity-lab" in text
        assert "scripts/install.py" in text
        assert "3.11" in text


def test_the_readme_install_line_is_one_the_scripts_support() -> None:
    """A README command nobody runs is the defect this project keeps fixing."""
    readme = (_ROOT / "README.md").read_text(encoding="utf-8")
    assert "install.sh | sh" in readme
    assert "install.ps1 | iex" in readme


def _path_for(executable: str) -> str:
    return str(Path(executable).parent)


def _systemroot() -> str:
    import os

    return os.environ.get("SYSTEMROOT", "")
