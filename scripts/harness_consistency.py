"""Checks that the shipped harness agrees with itself.

The harness states several facts twice: the branch ruleset names the status checks a merge
needs, and the workflows name the jobs that produce them; a workflow comment documents the
reference model, and its `--model` flag invokes one; the security dial is assigned in code and
restated in a comment; `harness/README.md` lists the components the folders ship. Each pair can
drift silently. Every function here returns the drifts it found as plain sentences, and
`test_harness_consistency.py` holds the real `harness/` to zero.

These checks used to live in the delivery standard's `check_standard.py`, when the harness was
authored there as `kit/`. Only the mechanical, harness-internal claims moved here; whether the
written standard describes the harness correctly is no longer checked mechanically.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# A job is a declared merge gate when its `name:` line carries this marker. Matched on the
# parenthesised file reference rather than the whole phrase, because the wording varies
# ("required status-check context", "required-to-RUN status-check context").
JOB_NAME = re.compile(r"^\s{4}name:\s*(\S+)\s*(#.*)?$", re.MULTILINE)
GATE_MARKER = "status-check context (branch-protection.json)"

MODEL_REFERENCE = re.compile(r"<<MODEL>>.*?\(reference:\s*([A-Za-z0-9.-]+)\)")
MODEL_FLAG = re.compile(r"^\s*--model\s+([A-Za-z0-9.-]+)\s*$", re.MULTILINE)

PASSES_ASSIGNMENT = re.compile(r"^\s*PASSES_HIGH=(\d+)\s*$", re.MULTILINE)
PASSES_REFERENCE = re.compile(r"<<SECURITY_PASSES_HIGH>>\s*—\s*reference value\s*(\d+)")

# Component folders whose contents harness/README.md must name, one entry per component.
ENUMERATED_DIRS = ("hooks", "agents", "skills", "workflows")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def workflow_jobs(workflow_dir: Path) -> dict[str, list[tuple[str, bool]]]:
    """Job `name:` values per workflow file, each flagged as a declared merge gate or not."""
    jobs: dict[str, list[tuple[str, bool]]] = {}
    for wf in sorted(workflow_dir.glob("*.yml")):
        found = [(name, GATE_MARKER in (comment or "")) for name, comment in JOB_NAME.findall(_read(wf))]
        if found:
            jobs[wf.name] = found
    return jobs


def required_contexts(ruleset_path: Path) -> list[str]:
    """The ruleset's required status-check contexts, or raise LookupError.

    Raising rather than returning [] is deliberate: an empty list would let both context checks
    pass vacuously at the exact moment branch protection stopped requiring anything.
    """
    ruleset = json.loads(_read(ruleset_path))
    for rule in ruleset.get("rules", []):
        if rule.get("type") == "required_status_checks":
            return [c["context"] for c in rule["parameters"]["required_status_checks"]]
    raise LookupError(
        f"{ruleset_path.name} has no required_status_checks rule. Either branch protection "
        f"stopped requiring checks, or the ruleset shape changed."
    )


def required_contexts_without_a_job(workflow_dir: Path, ruleset_path: Path) -> list[str]:
    """Required checks no job produces. Each one makes every PR wait forever."""
    try:
        contexts = required_contexts(ruleset_path)
    except LookupError as exc:
        return [str(exc)]
    produced = {name for jobs in workflow_jobs(workflow_dir).values() for name, _ in jobs}
    return [
        f"the ruleset requires the status check '{c}', but no workflow job is named '{c}'. "
        f"Every PR would block forever."
        for c in contexts
        if c not in produced
    ]


def gate_jobs_not_required(workflow_dir: Path, ruleset_path: Path) -> list[str]:
    """Jobs marked as merge gates that the ruleset does not require: they report, and red merges."""
    try:
        required = set(required_contexts(ruleset_path))
    except LookupError as exc:
        return [str(exc)]
    return [
        f"{wf_name} marks job '{name}' as a required status-check context, but the ruleset "
        f"does not require it. A red run would merge anyway."
        for wf_name, jobs in workflow_jobs(workflow_dir).items()
        for name, is_gate in jobs
        if is_gate and name not in required
    ]


def model_reference_drift(workflow_dir: Path) -> list[str]:
    """Workflows whose documented reference model differs from the model they invoke."""
    drifts = []
    for wf in sorted(workflow_dir.glob("*.yml")):
        text = _read(wf)
        reference = MODEL_REFERENCE.search(text)
        if not reference:
            continue
        expected = reference.group(1)
        invoked = set(MODEL_FLAG.findall(text))
        if not invoked:
            drifts.append(f"{wf.name} documents reference model '{expected}' but never passes --model.")
        elif invoked != {expected}:
            drifts.append(f"{wf.name} documents reference model '{expected}' but invokes {sorted(invoked)}.")
    return drifts


def security_dial_drift(security_yml: Path) -> list[str]:
    """The security repetition dial must read the same in its assignment and its comment."""
    text = _read(security_yml)
    assigned, documented = PASSES_ASSIGNMENT.search(text), PASSES_REFERENCE.search(text)
    if assigned is None or documented is None:
        return [
            f"could not read the repetition dial from {security_yml.name} (assignment or reference "
            f"comment). The wording moved, so agreement cannot be confirmed."
        ]
    if assigned.group(1) != documented.group(1):
        return [
            f"{security_yml.name} sets PASSES_HIGH={assigned.group(1)} but its comment documents "
            f"reference value {documented.group(1)}."
        ]
    return []


def components(harness_root: Path, subdir: str) -> list[str]:
    """Component names in harness/<subdir>: `.ps1`/`.sh` twins collapse to one, skills are dirs."""
    root = harness_root / subdir
    if not root.is_dir():
        return []
    return sorted(
        {entry.stem if entry.is_file() else entry.name for entry in root.iterdir() if entry.name != "README.md"}
    )


def undocumented_components(harness_root: Path, readme: Path) -> list[str]:
    """Components the harness ships that its README never names (word-bounded, not substring)."""
    text = _read(readme) if readme.is_file() else ""
    missing = []
    for subdir in ENUMERATED_DIRS:
        for name in components(harness_root, subdir):
            if not re.search(rf"(?<![A-Za-z0-9_-]){re.escape(name)}(?![A-Za-z0-9_-])", text):
                missing.append(f"{readme.name} never names `{name}`, which harness/{subdir}/ ships.")
    return missing
