"""Install `apiverity` from a published GitHub release.

This is the implementation behind `install.sh` and `install.ps1`. Both of those
do one job -- find a Python new enough to run this tool -- and then hand over
here, so there is one installer rather than two that can disagree. Twin
installers maintained by hand diverge, and the divergence is only ever found by
whichever platform is not the author's.

    python scripts/install.py                 # latest release, best available method
    python scripts/install.py --version v0.2.0
    python scripts/install.py --method pipx
    python scripts/install.py --dry-run       # resolve and verify, install nothing

## What the checksum check is and is not

The wheel is downloaded, hashed, and compared against the digest GitHub reports
for that asset. That catches a truncated or corrupted download and a mirror
serving different bytes than the release does.

It is **not** a signature. GitHub computes that digest from the bytes it is
storing, so an attacker who could replace the asset would change both. The
integrity story with actual teeth is the Sigstore attestation the release
workflow produces, and this prints the command for it rather than implying the
hash did that job.

Standard library only, on purpose: an installer that needs something installed
first is not an installer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

#: The repository releases are read from. Overridable so a fork, a mirror, or
#: an air-gapped copy can be installed the same way -- see `docs/air-gapped.md`.
DEFAULT_API = "https://api.github.com/repos/webdevsamran/api-verity-lab"

#: The minimum interpreter this project supports. Checked by the shell
#: bootstraps before they get here; repeated as an assertion because
#: `scripts/install.py` can also be run directly.
MIN_PYTHON = (3, 11)

#: Install methods, best first. `uv` and `pipx` both give the tool its own
#: environment, which is what a CLI wants; `pip --user` is the fallback for a
#: machine that has neither and cannot install one.
METHODS = ("uv", "pipx", "pip")

USER_AGENT = "api-verity-lab-installer"


class InstallError(Exception):
    """Something the installer will not guess its way past."""


def say(message: str) -> None:
    """Progress, flushed.

    stdout is block-buffered when it is a pipe and stderr never is, so without
    this the error explaining a failure arrives *ahead* of the lines saying what
    was being attempted -- backwards, in the one output somebody pastes into an
    issue.
    """
    print(message, flush=True)


def _get_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url, headers={"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT}
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise InstallError(
                f"{url} returned 404. Either the repository has no releases yet, or the "
                "version you named does not exist"
            ) from exc
        if exc.code == 403:
            raise InstallError(
                "GitHub rate-limited this request. Unauthenticated API calls are limited "
                "by IP; wait, or set GITHUB_TOKEN and retry"
            ) from exc
        raise InstallError(f"{url} returned HTTP {exc.code}") from exc
    except OSError as exc:
        raise InstallError(f"could not reach {url}: {exc}") from exc
    if not isinstance(body, dict):
        raise InstallError(f"{url} did not return a JSON object")
    return body


def release(api: str, version: str | None) -> dict[str, Any]:
    """The release to install: a named tag, or the latest published one."""
    if version:
        tag = version if version.startswith("v") else f"v{version}"
        return _get_json(f"{api}/releases/tags/{tag}")
    return _get_json(f"{api}/releases/latest")


def wheel_asset(data: dict[str, Any]) -> dict[str, Any]:
    """The wheel in a release, with its name, URL and digest.

    A release with no wheel is an error rather than a fallback to the sdist:
    installing from an sdist builds on the target machine, which needs a
    toolchain this script did not check for and cannot install.
    """
    assets = data.get("assets") or []
    wheels = [a for a in assets if str(a.get("name", "")).endswith(".whl")]
    if not wheels:
        names = sorted(str(a.get("name", "")) for a in assets)
        raise InstallError(
            f"release {data.get('tag_name')} has no wheel. It has: {names or 'nothing'}. "
            "Install from source instead: pip install "
            "'git+https://github.com/webdevsamran/api-verity-lab'"
        )
    # Newest wheel wins when a release carries several -- this project builds
    # one pure-Python wheel, but a release that gained per-platform wheels
    # should not silently install whichever came back first.
    return sorted(wheels, key=lambda a: str(a.get("name")))[-1]


def declared_digest(asset: dict[str, Any]) -> str | None:
    """The sha256 GitHub reports for an asset, if it reports one.

    `None` is a real answer: the field was added to the API after this
    project's first release, so an older release has no digest to check
    against. Refusing to install one would be treating a gap in GitHub's
    metadata as evidence of tampering; installing it silently would be
    claiming a check that did not happen. It is reported instead.
    """
    raw = str(asset.get("digest") or "")
    return raw.split("sha256:", 1)[1] if raw.startswith("sha256:") else None


def download(url: str, into: Path, *, attempts: int = 3, pause: float = 2.0) -> Path:
    """Fetch the asset, retrying a transient failure.

    Release downloads redirect to a CDN, and a reset connection or a timed-out
    TLS handshake there is common enough to have happened while this was being
    written. One attempt turns a blip into "the installer is broken"; a handful
    of them, spaced out, does not.

    A retry loop that also retried a 404 would be waiting for a file that is
    not there, so only `OSError` -- the transport -- is retried.
    """
    target = into / url.rsplit("/", 1)[-1]
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    last: OSError | None = None
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                target.write_bytes(response.read())
        except urllib.error.HTTPError as exc:
            raise InstallError(f"could not download {url}: HTTP {exc.code}") from exc
        except OSError as exc:
            last = exc
            if attempt < attempts:
                say(f"  {exc}; retrying ({attempt + 1} of {attempts})")
                time.sleep(pause)
            continue
        else:
            return target
    raise InstallError(f"could not download {url}: {last}")


def verify(path: Path, expected: str | None) -> str:
    """Hash the file; refuse on a mismatch. Returns the hash either way."""
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if expected and actual != expected:
        path.unlink(missing_ok=True)
        raise InstallError(
            f"checksum mismatch for {path.name}: the release declares {expected} and the "
            f"downloaded bytes hash to {actual}. Nothing was installed"
        )
    return actual


def available_methods() -> list[str]:
    found = []
    if shutil.which("uv"):
        found.append("uv")
    if shutil.which("pipx"):
        found.append("pipx")
    found.append("pip")
    return found


def in_virtualenv() -> bool:
    return sys.prefix != sys.base_prefix


def install_command(method: str, wheel: Path) -> list[str]:
    if method == "uv":
        # `--force` so re-running the installer upgrades rather than reporting
        # the tool as already present, which is what someone piping a URL into
        # a shell a second time is asking for.
        return ["uv", "tool", "install", "--force", str(wheel)]
    if method == "pipx":
        return ["pipx", "install", "--force", str(wheel)]
    command = [sys.executable, "-m", "pip", "install", "--upgrade"]
    if not in_virtualenv():
        # `--user` inside an activated virtualenv is a hard error -- "User
        # site-packages are not visible in this virtualenv" -- and running the
        # installer inside one is an ordinary thing to do. Reading that message
        # the obvious way is concluding the installer is broken.
        command.append("--user")
    return [*command, str(wheel)]


def run(command: list[str]) -> int:
    say("+ " + " ".join(command))
    return subprocess.run(command, check=False).returncode


def where_it_landed() -> str | None:
    return shutil.which("apiverity")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="install.py", description="Install apiverity from a GitHub release."
    )
    parser.add_argument("--version", help="release tag to install (default: the latest)")
    parser.add_argument("--api", default=DEFAULT_API, help=f"API base (default: {DEFAULT_API})")
    parser.add_argument(
        "--method",
        choices=("auto", *METHODS),
        default="auto",
        help="auto prefers uv, then pipx, then pip --user",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="resolve, download and verify; install nothing",
    )
    args = parser.parse_args(argv)

    if sys.version_info < MIN_PYTHON:
        print(
            f"error: apiverity needs Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer; this is "
            f"{sys.version.split()[0]}",
            file=sys.stderr,
        )
        return 2

    try:
        data = release(args.api, args.version)
        asset = wheel_asset(data)
        expected = declared_digest(asset)

        tag = data.get("tag_name", "?")
        say(f"api-verity-lab {tag}: {asset['name']}")

        with tempfile.TemporaryDirectory(prefix="apiverity-install-") as tmp:
            wheel = download(str(asset["browser_download_url"]), Path(tmp))
            actual = verify(wheel, expected)
            if expected:
                say(f"sha256 {actual} (matches the release)")
            else:
                # Said out loud. A silent install here would be a checksum
                # check the user believes happened.
                say(f"sha256 {actual} (the release declares none, so nothing was compared)")

            if args.dry_run:
                say("dry run: nothing installed")
                return 0

            method = args.method
            if method == "auto":
                method = available_methods()[0]
            code = run(install_command(method, wheel))
    except InstallError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if code != 0:
        print(f"error: {method} exited {code}; apiverity was not installed", file=sys.stderr)
        return code

    path = where_it_landed()
    if path:
        print(f"\ninstalled: {path}")
    else:
        # The most common outcome of `pip install --user` on a fresh machine,
        # and the one that reads as a failed install.
        print(
            "\ninstalled, but `apiverity` is not on PATH. Add the scripts directory "
            f"({'%APPDATA%/Python/Scripts' if sys.platform == 'win32' else '~/.local/bin'}) "
            "to PATH, or use `uv tool install` / `pipx install`, which do it for you.",
            file=sys.stderr,
        )
    print(
        "verify the bytes independently:\n"
        f"  gh attestation verify {asset['name']} --repo webdevsamran/api-verity-lab"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
