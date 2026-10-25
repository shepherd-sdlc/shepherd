"""The shipped harness agrees with itself, and each check can actually fail.

Every check is run twice over: once against the real `harness/` (which must be clean, or the
check is already being ignored), and against a synthetic harness with real drift injected (which
must be caught). A check that cannot fail reports green forever and everyone stops looking.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import harness_consistency as hc

HARNESS = Path(__file__).resolve().parents[2] / "harness"
WORKFLOWS = HARNESS / "workflows"
RULESET = HARNESS / "profile" / "rulesets" / "branch-protection.json"
GATE_COMMENT = "# <-- required status-check context (branch-protection.json)"


@pytest.fixture
def fake(tmp_path):
    (tmp_path / "workflows").mkdir()
    (tmp_path / "ruleset.json").write_text("{}", encoding="utf-8")
    return tmp_path


def write_ruleset(root: Path, contexts: list[str]) -> Path:
    path = root / "ruleset.json"
    rule = {"type": "required_status_checks",
            "parameters": {"required_status_checks": [{"context": c} for c in contexts]}}
    path.write_text(json.dumps({"rules": [{"type": "deletion"}, rule]}), encoding="utf-8")
    return path


def write_job(root: Path, filename: str, job_name: str, gate: bool = False, body: str = "") -> None:
    comment = f"  {GATE_COMMENT}" if gate else ""
    (root / "workflows" / filename).write_text(
        f"jobs:\n  job:\n    name: {job_name}{comment}\n{body}", encoding="utf-8"
    )


class TestTheRealHarness:
    def test_every_required_check_is_produced_by_a_job(self):
        assert hc.required_contexts_without_a_job(WORKFLOWS, RULESET) == []

    def test_every_declared_gate_is_required(self):
        assert hc.gate_jobs_not_required(WORKFLOWS, RULESET) == []

    def test_the_ruleset_requires_something(self):
        """Both context checks pass vacuously on an empty ruleset; this pins that it isn't."""
        assert hc.required_contexts(RULESET)

    def test_model_comments_match_the_invoked_model(self):
        assert hc.model_reference_drift(WORKFLOWS) == []

    def test_the_security_dial_agrees_with_its_comment(self):
        assert hc.security_dial_drift(WORKFLOWS / "security.yml") == []

    def test_the_readme_names_every_shipped_component(self):
        assert hc.undocumented_components(HARNESS, HARNESS / "README.md") == []


class TestRequiredChecks:
    def test_a_required_check_no_job_produces_is_caught(self, fake):
        ruleset = write_ruleset(fake, ["build-and-test", "phantom-gate"])
        write_job(fake, "ci.yml", "build-and-test", gate=True)
        drifts = hc.required_contexts_without_a_job(fake / "workflows", ruleset)
        assert len(drifts) == 1 and "phantom-gate" in drifts[0]

    def test_a_ruleset_requiring_nothing_is_caught_not_passed(self, fake):
        ruleset = fake / "ruleset.json"
        ruleset.write_text(json.dumps({"rules": [{"type": "deletion"}]}), encoding="utf-8")
        write_job(fake, "ci.yml", "build-and-test", gate=True)
        assert "no required_status_checks rule" in hc.required_contexts_without_a_job(fake / "workflows", ruleset)[0]
        assert hc.gate_jobs_not_required(fake / "workflows", ruleset)

    def test_a_gate_job_the_ruleset_does_not_require_is_caught(self, fake):
        ruleset = write_ruleset(fake, ["build-and-test"])
        write_job(fake, "ci.yml", "build-and-test", gate=True)
        write_job(fake, "extra.yml", "new-gate", gate=True)
        drifts = hc.gate_jobs_not_required(fake / "workflows", ruleset)
        assert len(drifts) == 1 and "new-gate" in drifts[0]

    def test_an_unmarked_job_is_not_expected_to_be_required(self, fake):
        ruleset = write_ruleset(fake, ["build-and-test"])
        write_job(fake, "ci.yml", "build-and-test", gate=True)
        write_job(fake, "deploy-dev.yml", "deploy-dev")
        assert hc.gate_jobs_not_required(fake / "workflows", ruleset) == []

    def test_the_gate_marker_tolerates_wording_variants(self, fake):
        """grader.yml says 'required-to-RUN status-check context' — still a declared gate."""
        ruleset = write_ruleset(fake, [])
        (fake / "workflows" / "grader.yml").write_text(
            "jobs:\n  g:\n    name: grader   # <-- required-to-RUN status-check context "
            "(branch-protection.json)\n",
            encoding="utf-8",
        )
        assert "grader" in hc.gate_jobs_not_required(fake / "workflows", ruleset)[0]


class TestModelReferences:
    def test_a_comment_that_disagrees_with_the_flag_is_caught(self, fake):
        write_job(fake, "grader.yml", "grader",
                  body="# <<MODEL>> Grader model (reference: sonnet).\n          --model opus\n")
        drifts = hc.model_reference_drift(fake / "workflows")
        assert len(drifts) == 1 and "sonnet" in drifts[0] and "opus" in drifts[0]

    def test_a_documented_model_that_is_never_invoked_is_caught(self, fake):
        write_job(fake, "grader.yml", "grader", body="# <<MODEL>> Grader model (reference: opus).\n")
        assert "never passes --model" in hc.model_reference_drift(fake / "workflows")[0]

    def test_one_invocation_drifting_from_the_rest_is_caught(self, fake):
        write_job(fake, "security.yml", "security-review",
                  body="# <<MODEL>> Reviewer (reference: opus).\n          --model opus\n          --model sonnet\n")
        assert hc.model_reference_drift(fake / "workflows")


class TestSecurityDial:
    @staticmethod
    def _yml(fake: Path, assigned: int, documented: int) -> Path:
        path = fake / "workflows" / "security.yml"
        path.write_text(
            f"  # <<SECURITY_PASSES_HIGH>> — reference value {documented} (current).\n"
            f"  PASSES_HIGH={assigned}\n",
            encoding="utf-8",
        )
        return path

    def test_code_drifting_from_its_comment_is_caught(self, fake):
        assert hc.security_dial_drift(self._yml(fake, 3, 1))

    def test_agreement_passes(self, fake):
        assert hc.security_dial_drift(self._yml(fake, 2, 2)) == []

    def test_an_unreadable_dial_fails_rather_than_passing(self, fake):
        path = fake / "workflows" / "security.yml"
        path.write_text("PASSES_HIGH=1\n", encoding="utf-8")
        assert "could not read" in hc.security_dial_drift(path)[0]


class TestInventory:
    def test_a_component_the_readme_never_names_is_caught(self, fake):
        (fake / "hooks").mkdir()
        (fake / "hooks" / "new-gate.ps1").write_text("x", encoding="utf-8")
        (fake / "hooks" / "new-gate.sh").write_text("x", encoding="utf-8")
        (fake / "README.md").write_text("hooks: stop-gate", encoding="utf-8")
        drifts = hc.undocumented_components(fake, fake / "README.md")
        assert len(drifts) == 1 and "new-gate" in drifts[0], "twins are one component"

    def test_a_substring_does_not_count_as_naming_it(self, fake):
        (fake / "agents").mkdir()
        (fake / "agents" / "grader.md").write_text("x", encoding="utf-8")
        (fake / "README.md").write_text("the harness was upgraded last week", encoding="utf-8")
        assert hc.undocumented_components(fake, fake / "README.md")

    def test_skills_are_directories(self, fake):
        (fake / "skills" / "spec-writer").mkdir(parents=True)
        (fake / "README.md").write_text("skills: spec-writer", encoding="utf-8")
        assert hc.undocumented_components(fake, fake / "README.md") == []
