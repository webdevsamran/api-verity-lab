#!/bin/sh
# One-line install for apiverity, on anything with a POSIX shell.
#
#   curl -fsSL https://raw.githubusercontent.com/webdevsamran/api-verity-lab/main/install.sh | sh
#
# This script does one job: find a Python new enough to run the tool. Everything
# after that is `scripts/install.py`, fetched from the same repository and ref,
# so there is one installer rather than two that drift apart -- and the drift is
# only ever noticed by whichever platform the author does not use.
#
# Arguments are passed straight through:
#
#   curl -fsSL .../install.sh | sh -s -- --version v0.2.0 --method pipx
#   curl -fsSL .../install.sh | sh -s -- --dry-run
#
# Environment:
#   VERITY_INSTALL_REF   branch or tag to fetch the installer from (default: main)
#   VERITY_PYTHON        use this interpreter instead of searching

set -eu

REF="${VERITY_INSTALL_REF:-main}"
RAW="https://raw.githubusercontent.com/webdevsamran/api-verity-lab/${REF}/scripts/install.py"

# 3.11 is the floor the package declares. Searched newest-first so a machine
# with several gets the newest rather than whichever `python3` happens to be.
find_python() {
  if [ -n "${VERITY_PYTHON:-}" ]; then
    printf '%s\n' "$VERITY_PYTHON"
    return 0
  fi
  for candidate in python3.14 python3.13 python3.12 python3.11 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 &&
      "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' \
        >/dev/null 2>&1; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

if ! PYTHON="$(find_python)"; then
  echo "error: apiverity needs Python 3.11 or newer, and none was found on PATH." >&2
  echo "       Install one (https://www.python.org/downloads/), or set VERITY_PYTHON." >&2
  exit 2
fi

fetch() {
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$1" -o "$2"
  elif command -v wget >/dev/null 2>&1; then
    wget -qO "$2" "$1"
  else
    echo "error: neither curl nor wget is available to download the installer." >&2
    exit 2
  fi
}

TMP="$(mktemp -d 2>/dev/null || mktemp -d -t apiverity)"
# Removed on every exit path, including the failure ones. A downloaded
# installer left in /tmp is a file somebody else can edit before the next run.
trap 'rm -rf "$TMP"' EXIT INT TERM

fetch "$RAW" "$TMP/install.py"

# Not `exec`: exec replaces this shell, the EXIT trap never runs, and the
# downloaded installer stays in a world-readable temp directory where somebody
# else can edit it before the next run.
"$PYTHON" "$TMP/install.py" "$@"
