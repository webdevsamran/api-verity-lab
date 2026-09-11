# Installing

Every channel this project has, what each one actually needs, and which of them
work today. The last column is the point: a published install matrix that lists
channels nobody can use is a worse artefact than a short one.

| Channel | Command | Works today |
|---|---|---|
| Shell installer | `curl -fsSL …/install.sh \| sh` | **yes** |
| PowerShell installer | `irm …/install.ps1 \| iex` | **yes** |
| Wheel from a release | `pipx install <release wheel URL>` | **yes** |
| From source | `pipx install 'git+https://github.com/webdevsamran/api-verity-lab'` | **yes** |
| Throwaway run | `uvx --from 'git+https://github.com/webdevsamran/api-verity-lab' apiverity --help` | **yes** |
| Container | `docker run --rm -v "$PWD:/work" ghcr.io/webdevsamran/api-verity-lab-server validate /work/openapi.yaml` | **yes**, from a release |
| PyPI | `pipx install api-verity-lab` · `uvx api-verity-lab` | not yet — see below |
| Homebrew, Scoop, winget | — | no, and honestly probably not — see below |

## The one-liner

```bash
curl -fsSL https://raw.githubusercontent.com/webdevsamran/api-verity-lab/main/install.sh | sh
```

```powershell
irm https://raw.githubusercontent.com/webdevsamran/api-verity-lab/main/install.ps1 | iex
```

Each shell script does exactly one thing — find a Python 3.11 or newer — and
then runs [`scripts/install.py`](https://github.com/webdevsamran/api-verity-lab/blob/main/scripts/install.py),
fetched from the same repository and ref. One installer, two bootstraps. Two
hand-maintained installers drift, and the drift is only ever found by whichever
platform the author does not use.

`install.py` then:

1. resolves the latest release (or `--version v0.2.0`) through the GitHub API;
2. downloads the wheel;
3. hashes it and compares against the digest GitHub reports for that asset,
   installing nothing on a mismatch;
4. installs with `uv tool install`, else `pipx install`, else `pip install`
   — `--method` overrides the choice;
5. prints where `apiverity` landed, and says so if it is not on `PATH`.

Options worth knowing:

```bash
curl -fsSL .../install.sh | sh -s -- --dry-run            # resolve and verify, install nothing
curl -fsSL .../install.sh | sh -s -- --version v0.2.0     # pin a release
curl -fsSL .../install.sh | sh -s -- --method pipx        # choose the method
VERITY_PYTHON=/opt/python3.12/bin/python3 sh install.sh   # name the interpreter
```

## What the checksum check is, and what it is not

It is **not** a signature. GitHub computes that digest from the bytes it stores,
so anyone able to replace the asset would change both, and the check would still
pass. What it does catch is a truncated download, a proxy that mangled the
transfer, and a mirror serving something other than what the release holds.

A release from before GitHub's API reported asset digests has nothing to compare
against. It still installs — treating a gap in GitHub's metadata as evidence of
tampering would be wrong — but the installer says `the release declares none, so
nothing was compared` rather than letting the absence read as a pass.

The integrity story with teeth is the Sigstore attestation the release workflow
produces, which the installer prints at the end:

```bash
gh attestation verify api_verity_lab-<version>-py3-none-any.whl \
  --repo webdevsamran/api-verity-lab
```

## If you would rather not pipe a URL into a shell

Reasonable. Every one of these is the same install without the pipe:

```bash
# Read it first, then run it
curl -fsSLO https://raw.githubusercontent.com/webdevsamran/api-verity-lab/main/install.sh
less install.sh && sh install.sh

# Or skip the installer entirely and take the wheel yourself
pipx install https://github.com/webdevsamran/api-verity-lab/releases/download/v0.2.0/api_verity_lab-0.2.0-py3-none-any.whl

# Or build from source
pipx install 'git+https://github.com/webdevsamran/api-verity-lab'
```

## PyPI

`pip install api-verity-lab` does not work, and saying otherwise in a README was
a defect this page exists partly to correct.

The release workflow is wired for it — OIDC trusted publishing, no stored token
— and is guarded behind the `PUBLISH_ENABLED` repository variable. Registering a
Trusted Publisher is a form on the PyPI account that owns the name, and cannot be
done from a repository. Until an account owner does that and flips the variable,
tagged releases build, attest, checksum and publish a GitHub Release, and skip
the upload with a notice.

That one step unlocks `pipx install api-verity-lab`, `uvx api-verity-lab`, and
`pip install api-verity-lab` at once.

## Homebrew, Scoop and winget

These want a self-contained executable to put on `PATH`. `apiverity` is a Python
package with real dependencies, so serving those channels honestly means one of:

- **a standalone binary per platform** (PyInstaller or similar), built and
  tested on each of macOS, Linux and Windows. That is a real option and a real
  amount of work — a frozen build of a project with `pydantic`, `flask` and
  `httpx` in it needs its own test matrix, because the way it breaks is at
  import time on somebody else's machine;
- **a Homebrew formula with a `resource` block per dependency**, each pinned and
  checksummed, regenerated on every dependency bump.

Neither exists here, so neither channel is listed as available. A formula that
has never been installed is a claim, and this project does not publish those.
The gap is recorded in [product-gaps.md](product-gaps.md) rather than papered
over with a manifest pointing at a binary nobody built.

## Air-gapped and mirrors

`--api` points the installer at any host that speaks the shape of GitHub's
releases API, which is how a mirror or an internal artifact host is used:

```bash
python scripts/install.py --api https://git.internal/api/v3/repos/platform/api-verity-lab
```

For a network with no egress at all, [air-gapped.md](air-gapped.md) covers the
offline path: the wheel, the container image and the vendored schemas.

## From a clone, for development

```bash
git clone https://github.com/webdevsamran/api-verity-lab
cd api-verity-lab
pip install -e ".[dev]"
pytest tests/ -q
```

The `dev` extra deliberately pulls `graphql-core`, `pyjwt`, `fastapi` and
`jsonschema`: without them the tests covering GraphQL, OIDC, the application
adapter and Arazzo conformance would skip, and a suite that silently skips its
coverage of a feature is indistinguishable from one that passes it.
