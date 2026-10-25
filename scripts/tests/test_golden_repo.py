"""Golden-repo test — the REAL payload composed with the starter profile.

The starter profile is the one Free ships. The enterprise and Azure DevOps installs, and their tree
snapshots, are Pro's: test_golden_repo_pro.py.
"""

import io
import subprocess
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest
import yaml

from install_harness import install

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PAYLOAD = _REPO_ROOT / "harness"
STARTER_PROFILE = _REPO_ROOT / "profiles" / "starter" / "profile.yaml"


@pytest.fixture(scope="class")
def starter_repo(tmp_path_factory):
    target = tmp_path_factory.mktemp("starter-repo")
    subprocess.run(["git", "init", "-q"], cwd=target, check=True)
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = install(PAYLOAD, target, force=False, profile_path=STARTER_PROFILE)
    assert rc == 0, f"install failed rc={rc}\n{out.getvalue()}\n{err.getvalue()}"
    return target, out.getvalue(), err.getvalue()


class TestStarterRepoIsNode:
    """The point of the whole seam: a Node profile must get a NODE pipeline. Before the seam was
    mechanical, this repo would have been handed `dotnet restore`."""

    def _ci(self, target: Path) -> str:
        return (target / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    def test_pipeline_runs_node_not_dotnet(self, starter_repo):
        target, _, _ = starter_repo
        ci = self._ci(target)
        assert "uses: actions/setup-node@v7" in ci        # github pack's toolchain_map for id: node
        assert "node-version: '24.x'" in ci               # map's input name + ci-profile's version
        assert "npm ci" in ci                             # ci-profile.commands.restore
        assert "npx vitest run" in ci
        # THE WHOLE FILE, not just the blocking job. This assertion was scoped to the blocking job
        # while the eval-gate carried a hardcoded `dotnet test` on every stack; closing that seam
        # (intent-driven-development#15) retired the exemption. A Node repo now receives no .NET
        # anywhere in its pipeline — which is the entire promise of the seam.
        assert "dotnet" not in ci, "a .NET command leaked into a Node repo's pipeline"

    def test_eval_gate_is_realized_from_the_node_stack(self, starter_repo):
        """The gap this closed (intent-driven-development#15): the eval job used to hardcode
        `dotnet test` regardless of stack, because ci-profile declared only a FILTER and not the
        runner invocation that consumes it."""
        target, _, _ = starter_repo
        eval_job = self._ci(target).split("eval-gate:", 1)
        assert len(eval_job) == 2, "eval-gate job vanished"
        assert 'npx vitest run -t "@owasp-agentic"' in eval_job[1]

    def test_node_eval_gate_cannot_pass_by_matching_nothing(self, starter_repo):
        """`vitest run -t` matching ZERO tests exits 0 (verified on vitest 3.2.7 and 4.1.10), so a
        bare invocation would be a gate that passes green having run nothing. The realized job must
        carry the guard that fails closed — and it must guard on numPassed+numFailed, because
        `success` is true and `numTotalTests` counts COLLECTED (not matched) on a zero-match run."""
        eval_job = self._ci(starter_repo[0]).split("eval-gate:", 1)[1]
        assert "numPassedTests+r.numFailedTests" in eval_job, "eval gate lost its fail-closed guard"
        assert "failing closed" in eval_job

    def test_coverage_floor_comes_from_the_customer_profile(self, starter_repo):
        # starter states quality.coverage_minimum: 60; the node pack declares 80. The profile is
        # the later layer, so 60 is what the gate must enforce.
        target, _, _ = starter_repo
        assert "COVERAGE_FLOOR: '60'" in self._ci(target)

    def test_no_seam_token_survives(self, starter_repo):
        target, _, _ = starter_repo
        from ci_tokens import residual_tokens
        for path in target.rglob("*"):
            if path.is_file() and path.suffix in (".yml", ".yaml"):
                left = residual_tokens(path.read_text(encoding="utf-8"))
                assert not left, f"{path.name} kept seam tokens: {left}"

    def test_node_stack_standards_spliced(self, starter_repo):
        target, _, _ = starter_repo
        claude = (target / "CLAUDE.md").read_text(encoding="utf-8")
        assert "{{STACK}}" not in claude
        assert (target / ".claude" / "skills" / "api-pattern-node" / "SKILL.md").is_file()

    def test_emitted_workflows_parse(self, starter_repo):
        target, _, _ = starter_repo
        for wf in sorted((target / ".github" / "workflows").glob("*.yml")):
            yaml.safe_load(wf.read_text(encoding="utf-8"))


class TestGithubSettingsCarryNoAzEntries:
    """Fold C's additive guarantee: the az permission fragment ships only with the ADO pack —
    a GitHub install's settings.json must not grow az entries it has no use for."""

    def test_starter_settings_have_no_az_permissions(self, starter_repo):
        target, _, _ = starter_repo
        settings = (target / ".claude" / "settings.json").read_text(encoding="utf-8")
        assert "az repos" not in settings
        assert ".azuredevops" not in settings
