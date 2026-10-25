"""The session-start hook twins: the banner, the phase reminder and the retired section-plan block.

The first test of the hook itself. It runs the real scripts via subprocess with cwd = a tmp
project that holds `.sdlc/state.yaml` (+ `profile.yaml`) from conftest's `state_yaml` fixture,
exactly the way Claude Code invokes them. The bash twin always runs; the PowerShell twin runs
only when `pwsh` is on PATH (skipped otherwise) and must print identical `[SHEPHERD-PHASE]` and
banner lines after `\\r\\n` normalisation — the two scripts share one output contract.

What these tests hold the hook to:

- the hook runs, exits 0 and creates nothing;
- the Build reminder opens with the loop's one-spec-at-a-time rule;
- the retired `[SHEPHERD] Session Handoff:` section-plan summary is gone even when a legacy
  `session-handoff.json` is still present.

The `[SHEPHERD-SPRINT]` line and the Build reminder's refinement clause are the sprint layer's,
and are tested in test_session_start_hook_pro.py.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

HOOKS_DIR = Path(__file__).resolve().parents[2] / "hooks"
BASH_HOOK = HOOKS_DIR / "shepherd-session-start.sh"
PS1_HOOK = HOOKS_DIR / "shepherd-session-start.ps1"
PWSH = shutil.which("pwsh")


def _bash() -> str | None:
    """The bash that can actually run the hook (mirrors test_review_gate_hook.py).

    On Windows, PATH's `bash` is System32's WSL shim, which on CI runners (no distro
    installed) prints "Windows Subsystem for Linux has no installed distributions" and
    exits 1 — it never runs the script at all. Git Bash is the bash a real Windows
    install executes hooks with, so resolve it explicitly and never fall back to the shim.
    """
    if os.name != "nt":
        return shutil.which("bash")
    for var in ("ProgramFiles", "ProgramFiles(x86)"):
        base = os.environ.get(var)
        if base and (Path(base) / "Git" / "bin" / "bash.exe").is_file():
            return str(Path(base) / "Git" / "bin" / "bash.exe")
    git = shutil.which("git")
    if git:  # <git-root>/cmd/git.exe -> <git-root>/bin/bash.exe
        cand = Path(git).parent.parent / "bin" / "bash.exe"
        if cand.is_file():
            return str(cand)
    found = shutil.which("bash")
    return None if found and "system32" in found.lower() else found


BASH = _bash()
pytestmark = pytest.mark.skipif(
    BASH is None, reason="shepherd-session-start.sh needs bash (Git Bash on Windows)"
)

SPRINT_TAG = "[SHEPHERD-SPRINT]"
PHASE_TAG = "[SHEPHERD-PHASE]"
BUILD_RULE = "[SHEPHERD-PHASE] One spec at a time: Intent -> Delegate -> Discern."
RETIRED_MARKERS = ("Session Handoff", "[SHEPHERD] Context:", "[SHEPHERD] Next action:", "active blocker")

LEGACY_HANDOFF = """{
  "$schema": "session-handoff-v1",
  "session_number": 3,
  "sections": [{"id": "SECTION-001", "status": "complete"}, {"id": "SECTION-002", "status": "in_progress"}],
  "context_for_next_session": "wire the gateway next",
  "next_actions": [{"action": "Implement routes", "section": "SECTION-002"}],
  "blockers": [{"id": "B1", "resolved": false}]
}
"""


# --------------------------------------------------------------------------- helpers


def _run(cmd: list[str], project: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "PWD": str(project)}
    return subprocess.run(
        cmd, cwd=project, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60
    )


def run_bash(project: Path) -> subprocess.CompletedProcess:
    return _run([BASH, str(BASH_HOOK)], project)


def run_pwsh(project: Path) -> subprocess.CompletedProcess:
    return _run([PWSH, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(PS1_HOOK)], project)


def lines(out: str) -> list[str]:
    return out.replace("\r\n", "\n").rstrip("\n").split("\n") if out.strip() else []


def sprint_lines(out: str) -> list[str]:
    return [line for line in lines(out) if line.startswith(SPRINT_TAG)]


def phase_line(out: str) -> str:
    found = [line for line in lines(out) if line.startswith(PHASE_TAG)]
    assert len(found) == 1, found
    return found[0]


def set_phase(state_path: Path, phase_id: str, phase_name: str) -> None:
    state = yaml.safe_load(state_path.read_text(encoding="utf-8"))
    state["current_phase"] = phase_id
    state["phase_name"] = phase_name
    state_path.write_text(yaml.dump(state, default_flow_style=False), encoding="utf-8")


@pytest.fixture
def project(state_yaml):
    """Repo root of the fixture project (state_yaml lives at <root>/.sdlc/state.yaml)."""
    return state_yaml.parent.parent


# --------------------------------------------------------------------------- bash twin


def test_no_sprints_dir_prints_no_sprint_line(project):
    proc = run_bash(project)

    assert proc.returncode == 0
    assert proc.stderr == ""
    assert lines(proc.stdout)[0].startswith("[SHEPHERD] Project: test-project")  # the hook actually ran
    assert sprint_lines(proc.stdout) == []
    assert not (project / ".sdlc" / "sprints").exists()  # the hook is read-only: it created nothing


def test_build_reminder_opens_with_the_one_spec_at_a_time_rule(project):
    set_phase(project / ".sdlc" / "state.yaml", "build", "build")

    out = run_bash(project).stdout

    assert phase_line(out).startswith(BUILD_RULE)


def test_retired_session_handoff_block_is_gone_even_with_a_legacy_file(project):
    set_phase(project / ".sdlc" / "state.yaml", "build", "build")
    handoff = project / ".sdlc" / "artifacts" / "build" / "session-handoff.json"
    handoff.parent.mkdir(parents=True, exist_ok=True)
    handoff.write_text(LEGACY_HANDOFF, encoding="utf-8")

    proc = run_bash(project)

    assert proc.returncode == 0
    assert proc.stderr == ""
    for marker in RETIRED_MARKERS:
        assert marker not in proc.stdout, marker
    assert "malformed" not in proc.stdout


def test_malformed_legacy_handoff_file_no_longer_warns(project):
    set_phase(project / ".sdlc" / "state.yaml", "build", "build")
    handoff = project / ".sdlc" / "artifacts" / "build" / "session-handoff.json"
    handoff.parent.mkdir(parents=True, exist_ok=True)
    handoff.write_text("{ not json", encoding="utf-8")

    proc = run_bash(project)

    assert proc.returncode == 0
    assert "session-handoff.json" not in proc.stdout


# --------------------------------------------------------------------------- source-level guards


def test_hook_sources_are_lf_only_and_free_of_json_readers():
    sh = BASH_HOOK.read_bytes()
    ps1 = PS1_HOOK.read_bytes()

    # Only the shell script must be LF (.gitattributes forces `*.sh text eol=lf`; bash chokes on
    # CRLF). The .ps1 is left to the platform default and legitimately checks out CRLF on Windows.
    assert b"\r" not in sh
    for needle in (b"jq", b"python", b"session-handoff", b"Session Handoff", b"PYEOF"):
        assert needle not in sh, needle
    for needle in (b"ConvertFrom-Json", b"session-handoff", b"Session Handoff"):
        assert needle not in ps1, needle
    # The closing context tags moved with their openers in the Shepherd rename, and no old
    # marker may creep back into either twin when `scripts/dev/rename_brand.py` is replayed.
    for closer in (b"[/SHEPHERD-CONTEXT:LAYER]", b"[/SHEPHERD-CONTEXT:INTAKE-INDEX]"):
        assert closer in sh and closer in ps1, closer
    for stale in (b"[SDLC", b"[/SDLC"):
        assert stale not in sh and stale not in ps1, stale


# --------------------------------------------------------------------------- pwsh twin


pwsh_only = pytest.mark.skipif(PWSH is None, reason="pwsh not on PATH; the PowerShell twin cannot be exercised here")


@pwsh_only
def test_pwsh_twin_prints_identical_banner_and_phase_lines(project):
    set_phase(project / ".sdlc" / "state.yaml", "build", "build")

    bash = run_bash(project)
    pwsh = run_pwsh(project)

    assert pwsh.returncode == 0, pwsh.stderr
    assert phase_line(pwsh.stdout) == phase_line(bash.stdout)
    assert lines(pwsh.stdout)[0] == lines(bash.stdout)[0]


@pwsh_only
def test_pwsh_twin_no_longer_prints_the_retired_handoff_summary(project):
    set_phase(project / ".sdlc" / "state.yaml", "build", "build")
    handoff = project / ".sdlc" / "artifacts" / "build" / "session-handoff.json"
    handoff.parent.mkdir(parents=True, exist_ok=True)
    handoff.write_text(LEGACY_HANDOFF, encoding="utf-8")

    pwsh = run_pwsh(project)

    assert pwsh.returncode == 0, pwsh.stderr
    for marker in RETIRED_MARKERS:
        assert marker not in pwsh.stdout, marker
