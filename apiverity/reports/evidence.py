"""An evidence pack: what was verified, when, and what it proves.

An auditor under SOC 2, ISO/IEC 42001, DORA or the EU AI Act does not ask for a
tool's opinion about compliance. They ask for records: what was checked, when,
against what, by what, and what came back — in a form that cannot have been
edited afterwards without anyone noticing.

This assembles exactly that from result artifacts this tool already writes, and
stops there. It does not score, certify, or claim a control is satisfied.

The line this module will not cross
-----------------------------------
Mapping a technical record to a clause of a regulation is a judgement about an
organisation, not about a file. A tool that prints "SOC 2 CC8: PASS" is
inventing an assessment nobody performed, and an auditor who found one would be
right to distrust everything else in the pack.

So the pack names **practices** — change control over a published interface,
verification that a running system still matches what it declared, an inventory
of what an automated agent can reach — and lists, for each, the place in each
regime where that practice is usually evidenced, with the citation and a note
on what the record does *not* establish. The mapping is the auditor's to make;
this makes it possible rather than making it up.

Citations were read on 2026-09-09 and are recorded per reference. Where a
clause number could not be established it is absent rather than guessed: ISO
42001's Annex A group A.10 is not referenced anywhere below because its title
was not confirmed, and an invented citation is worse than a missing one.

Reproducibility
---------------
Every other artifact in this project is deterministic. This one is not, on
purpose: an evidence record with no date is not evidence. `--as-of` fixes the
timestamp for tests and for a rebuild of a historical pack.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

NL = chr(10)

#: Written into the pack so a reader knows which layout they have.
PACK_VERSION = 1


@dataclass(frozen=True)
class RegimeRef:
    """Where a practice is usually evidenced in one regime."""

    regime: str
    reference: str
    #: What this record does and does not establish for that reference.
    note: str
    source: str


@dataclass(frozen=True)
class Practice:
    """Something the run demonstrably did, in the vocabulary of an audit."""

    id: str
    title: str
    #: What a reader can conclude from an artifact of this kind.
    demonstrates: str
    #: `command` values whose artifacts are evidence of this practice.
    commands: tuple[str, ...]
    references: tuple[RegimeRef, ...] = field(default_factory=tuple)


_SOC2 = "https://www.aicpa-cima.com/ (Trust Services Criteria, common criteria CC1-CC9)"
_ISO = "ISO/IEC 42001:2023 Annex A"
_DORA = "Regulation (EU) 2022/2554 (DORA)"
_AIACT = "Regulation (EU) 2024/1689 (AI Act)"


PRACTICES: tuple[Practice, ...] = (
    Practice(
        id="change-control",
        title="Change control over a published interface",
        demonstrates=(
            "every change to the interface was classified against a versioned rule catalogue "
            "before it shipped, and a change graded breaking failed the pipeline"
        ),
        commands=("breaking", "diff", "mcp-lock", "changelog"),
        references=(
            RegimeRef(
                "SOC 2",
                "CC8 Change Management",
                "evidence that changes are assessed before release. It says nothing about "
                "approval workflow, segregation of duties, or who authorised the release",
                _SOC2,
            ),
            RegimeRef(
                "ISO/IEC 42001",
                "Annex A.5 AI system lifecycle",
                "the interface an AI system depends on, governed across its lifecycle. Not the "
                "lifecycle of the AI system itself",
                _ISO,
            ),
            RegimeRef(
                "DORA",
                "Article 9 (Protection and prevention)",
                "a control applied continuously to an ICT system's interfaces. DORA's article "
                "is far broader than this one control",
                _DORA,
            ),
        ),
    ),
    Practice(
        id="conformance",
        title="Verification that a running system still matches what it declared",
        demonstrates=(
            "a live service or MCP server was probed and compared, on this date, against the "
            "contract its consumers were given"
        ),
        commands=("drift", "test", "coverage"),
        references=(
            RegimeRef(
                "SOC 2",
                "CC7 System Operations",
                "evidence of monitoring for deviations. It covers interface conformance only, "
                "not availability, capacity or incident response",
                _SOC2,
            ),
            RegimeRef(
                "DORA",
                "Article 10 (Detection)",
                "a detection mechanism for anomalous ICT behaviour, narrowly scoped to contract "
                "divergence",
                _DORA,
            ),
            RegimeRef(
                "EU AI Act",
                "Article 15 (accuracy, robustness and cybersecurity)",
                "robustness of the *integration* an AI system depends on. This is not a "
                "conformity assessment of a high-risk AI system and does not substitute for one",
                _AIACT,
            ),
        ),
    ),
    Practice(
        id="agent-reach",
        title="Inventory of the tools and servers an automated agent can reach",
        demonstrates=(
            "the tool surface available to an agent was enumerated and compared with an "
            "approved list, and any capability outside that list was reported"
        ),
        commands=("mcp-inventory", "mcp-lock", "drift"),
        references=(
            RegimeRef(
                "SOC 2",
                "CC6 Logical and Physical Access Controls",
                "what an automated identity can reach. It is an inventory, not proof that the "
                "access was authorised or correctly scoped",
                _SOC2,
            ),
            RegimeRef(
                "ISO/IEC 42001",
                "Annex A.9 Third-party relationships",
                "the third-party capabilities an AI system consumes. Contractual and supplier "
                "assessment obligations are not addressed here",
                _ISO,
            ),
            RegimeRef(
                "DORA",
                "Chapter V (Articles 28-30), managing ICT third-party risk",
                "a register of third-party ICT interfaces in use. DORA's register of "
                "information and contractual requirements are separate obligations",
                _DORA,
            ),
            RegimeRef(
                "EU AI Act",
                "Article 14 (human oversight)",
                "knowing what a system can do is a precondition for overseeing it. It is not "
                "an oversight mechanism by itself",
                _AIACT,
            ),
        ),
    ),
    Practice(
        id="exposure",
        title="Detection of credential exposure and tool-description tampering",
        demonstrates=(
            "responses, manifests and tool results were scanned for credentials and for text "
            "aimed at an agent rather than at a reader"
        ),
        commands=("validate", "drift"),
        references=(
            RegimeRef(
                "SOC 2",
                "CC7 System Operations",
                "detection of a security-relevant condition. Remediation and incident handling "
                "are elsewhere",
                _SOC2,
            ),
            RegimeRef(
                "EU AI Act",
                "Article 15 (cybersecurity)",
                "one attack surface -- prompt injection delivered through a tool manifest -- "
                "checked. Not a cybersecurity assessment",
                _AIACT,
            ),
        ),
    ),
    Practice(
        id="record",
        title="A dated, tamper-evident record of each verification",
        demonstrates=(
            "each run produced a schema-conformant artifact, and this pack carries a checksum "
            "for every file, verifiable with `apiverity verify`"
        ),
        commands=(),
        references=(
            RegimeRef(
                "SOC 2",
                "CC4 Monitoring Activities",
                "evidence that the checks were actually run, and when",
                _SOC2,
            ),
            RegimeRef(
                "ISO/IEC 42001",
                "Annex A.7 System information",
                "documented information about a system and the checks applied to it",
                _ISO,
            ),
            RegimeRef(
                "EU AI Act",
                "Articles 12 and 19 (record-keeping, automatically generated logs)",
                "**this pack does not satisfy either.** Those articles require logs generated "
                "by the high-risk AI system over its lifetime, retained by the deployer. This "
                "is a log of governance activity performed *on* an interface, which is a "
                "different artifact and is offered as supporting evidence only",
                _AIACT,
            ),
        ),
    ),
)


@dataclass
class PackedArtifact:
    """One result artifact copied into the pack."""

    filename: str
    source: str
    command: str
    subject: str
    findings: int
    errors: int
    sha256: str


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _subject(payload: dict[str, Any]) -> str:
    """What this artifact is about, in the words the artifact itself used."""
    old_spec, new_spec = payload.get("old_spec"), payload.get("new_spec")
    if isinstance(old_spec, str) and isinstance(new_spec, str):
        return f"{old_spec} -> {new_spec}"
    for key in ("spec", "target", "source", "bundle", "root", "lock"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    # Never invented. An evidence record whose subject is a guess is worse
    # than one that admits it does not know.
    return "not recorded by this artifact"


def _counts(payload: dict[str, Any]) -> tuple[int, int]:
    findings = payload.get("findings")
    if not isinstance(findings, list):
        return 0, 0
    errors = sum(
        1 for f in findings if isinstance(f, dict) and str(f.get("severity", "")).upper() == "ERROR"
    )
    return len(findings), errors


def read_artifact(path: Path) -> dict[str, Any]:
    """A result payload from a JSON file or an exported bundle directory."""
    target = path / "result.json" if path.is_dir() else path
    payload = json.loads(target.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"{target}: a result artifact is a JSON object")
    return payload


def practices_for(commands: set[str]) -> list[Practice]:
    """Practices the given commands actually evidence.

    A practice with no artifact behind it is left out entirely rather than
    listed as unevidenced. A pack is a record of what was done; an empty row
    invites the reader to imagine it was done badly rather than not at all.
    """
    return [p for p in PRACTICES if not p.commands or (set(p.commands) & commands)]


def render_pack(packed: list[PackedArtifact], *, generated_at: str, tool_version: str) -> str:
    """The human-readable index of the pack."""
    commands = {item.command for item in packed}
    lines = [
        "# Verification evidence pack",
        "",
        f"Generated {generated_at} by apiverity {tool_version}. Pack format {PACK_VERSION}.",
        "",
        "## What this is, and what it is not",
        "",
        "A record of technical verification: what was checked, when, against what, and what",
        "came back. Every file is listed in `SHA256SUMS` and can be checked with",
        "`apiverity verify <this directory>`.",
        "",
        "**It is not a compliance assessment.** Nothing here says a control is satisfied.",
        "Mapping a technical record to a clause of a regulation is a judgement about an",
        "organisation, not about a file, and a tool that printed `CC8: PASS` would be",
        "inventing an assessment nobody performed. The practices below name where each",
        "record is usually evidenced, with what it does not establish; the mapping is",
        "yours to make.",
        "",
        "## Records",
        "",
        "| File | Command | Subject | Findings | Errors | SHA-256 |",
        "|---|---|---|---|---|---|",
    ]
    for item in packed:
        lines.append(
            f"| `{item.filename}` | `{item.command}` | `{item.subject}` | {item.findings} | "
            f"{item.errors} | `{item.sha256[:16]}…` |"
        )

    lines += ["", "## Practices evidenced", ""]
    for practice in practices_for(commands):
        lines += [
            f"### {practice.title}",
            "",
            f"{practice.demonstrates.capitalize()}.",
            "",
        ]
        if practice.commands:
            lines.append(
                "Evidenced by: " + ", ".join(f"`apiverity {c}`" for c in practice.commands) + "."
            )
            lines.append("")
        lines += [
            "| Regime | Usually evidenced at | What this record does not establish |",
            "|---|---|---|",
        ]
        for ref in practice.references:
            lines.append(f"| {ref.regime} | {ref.reference} | {ref.note} |")
        lines.append("")

    sources = sorted({ref.source for p in PRACTICES for ref in p.references})
    lines += [
        "## Citations",
        "",
        "Read 2026-09-09. A clause whose number could not be established is absent rather",
        "than guessed.",
        "",
    ]
    lines += [f"- {source}" for source in sources]
    lines += [
        "",
        "---",
        "",
        "This pack is deliberately not reproducible byte-for-byte: it carries the date it",
        "was made, and an evidence record with no date is not evidence. Pass `--as-of` to",
        "rebuild a historical one.",
    ]
    return NL.join(lines) + NL


def write_pack(
    sources: list[str],
    out_dir: Path,
    *,
    generated_at: str,
    tool_version: str,
    frameworks: tuple[str, ...] = ("owasp-mcp", "owasp-asi", "owasp-api"),
) -> list[PackedArtifact]:
    """Assemble the pack on disk. Flat, because `apiverity verify` reads flat.

    A subdirectory would be skipped by that command's file walk, so the files
    inside it would sit in the pack unverified while the pack reported itself
    verified. Prefixed filenames instead.
    """
    from apiverity.reports.compliance import FRAMEWORKS, render_markdown

    out_dir.mkdir(parents=True, exist_ok=True)
    packed: list[PackedArtifact] = []

    for index, source in enumerate(sorted(sources), start=1):
        payload = read_artifact(Path(source))
        command = str(payload.get("command", "unknown"))
        filename = f"{index:02d}-{command}.json"
        body = json.dumps(payload, indent=2, sort_keys=True).encode()
        (out_dir / filename).write_bytes(body)
        findings, errors = _counts(payload)
        packed.append(
            PackedArtifact(
                filename=filename,
                source=source,
                command=command,
                subject=_subject(payload),
                findings=findings,
                errors=errors,
                sha256=_digest(body),
            )
        )
        for key in frameworks:
            rendered = render_markdown(FRAMEWORKS[key], payload).encode()
            (out_dir / f"{index:02d}-{command}-{key}.md").write_bytes(rendered)

    (out_dir / "EVIDENCE.md").write_text(
        render_pack(packed, generated_at=generated_at, tool_version=tool_version),
        encoding="utf-8",
    )

    files = sorted(p for p in out_dir.iterdir() if p.is_file() and p.name != "SHA256SUMS")
    (out_dir / "SHA256SUMS").write_text(
        "".join(f"{_digest(p.read_bytes())}  {p.name}{NL}" for p in files),
        encoding="utf-8",
    )
    return packed


__all__ = [
    "PACK_VERSION",
    "PRACTICES",
    "PackedArtifact",
    "Practice",
    "RegimeRef",
    "practices_for",
    "read_artifact",
    "render_pack",
    "write_pack",
]
