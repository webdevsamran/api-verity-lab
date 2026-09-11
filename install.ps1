<#
.SYNOPSIS
One-line install for apiverity on Windows.

.DESCRIPTION
    irm https://raw.githubusercontent.com/webdevsamran/api-verity-lab/main/install.ps1 | iex

This script does one job: find a Python new enough to run the tool. Everything
after that is `scripts/install.py`, fetched from the same repository and ref, so
there is one installer rather than two that drift apart -- and the drift is only
ever noticed by whichever platform the author does not use.

To pass arguments, download it first (`irm ... | iex` has no way to forward
them):

    irm https://raw.githubusercontent.com/webdevsamran/api-verity-lab/main/install.ps1 -OutFile install.ps1
    ./install.ps1 -Arguments '--version','v0.2.0'

.PARAMETER Arguments
Passed through to scripts/install.py verbatim.

.PARAMETER Ref
Branch or tag to fetch the installer from. Defaults to main.

.PARAMETER Python
Use this interpreter instead of searching for one.
#>
[CmdletBinding()]
param(
    [string[]] $Arguments = @(),
    [string] $Ref = $(if ($env:VERITY_INSTALL_REF) { $env:VERITY_INSTALL_REF } else { 'main' }),
    [string] $Python = $env:VERITY_PYTHON
)

$ErrorActionPreference = 'Stop'

function Find-Python {
    param([string] $Preferred)

    if ($Preferred) { return $Preferred }

    # `py -3` first: the launcher is what a python.org install puts on PATH,
    # and it resolves to the newest interpreter rather than whichever one a
    # PATH edit happens to shadow.
    $candidates = @(
        @{ exe = 'py'; args = @('-3') },
        @{ exe = 'python3'; args = @() },
        @{ exe = 'python'; args = @() }
    )
    foreach ($candidate in $candidates) {
        $found = Get-Command $candidate.exe -ErrorAction SilentlyContinue
        if (-not $found) { continue }
        $probe = @($candidate.args) + @(
            '-c', 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'
        )
        & $found.Source @probe 2>$null
        if ($LASTEXITCODE -eq 0) {
            return (@($found.Source) + @($candidate.args)) -join ' '
        }
    }
    return $null
}

$resolved = Find-Python -Preferred $Python
if (-not $resolved) {
    Write-Error (
        'apiverity needs Python 3.11 or newer, and none was found on PATH. ' +
        'Install one (https://www.python.org/downloads/, or `winget install Python.Python.3.12`), ' +
        'or set VERITY_PYTHON.'
    )
    exit 2
}

# Split back apart: `py -3` is an executable plus an argument, and passing the
# whole string as a command name looks for a file called "py -3".
$parts = @($resolved -split ' ' | Where-Object { $_ })
$exe = $parts[0]
# `Select-Object -Skip`, not `$parts[1..($parts.Length - 1)]`: for a one-element
# array that range is `1..0`, which PowerShell evaluates *descending* and which
# therefore yields element 0 -- so a plain `python` path was passed to itself as
# an argument, and python tried to open a file named after the first letter of
# its own path.
$exeArgs = @($parts | Select-Object -Skip 1)

$raw = "https://raw.githubusercontent.com/webdevsamran/api-verity-lab/$Ref/scripts/install.py"
$tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("apiverity-install-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $tmp | Out-Null
try {
    $script = Join-Path $tmp 'install.py'
    Invoke-WebRequest -Uri $raw -OutFile $script -UseBasicParsing
    & $exe @exeArgs $script @Arguments
    exit $LASTEXITCODE
}
finally {
    # Removed on every exit path. A downloaded installer left in TEMP is a file
    # somebody else can edit before the next run.
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
}
