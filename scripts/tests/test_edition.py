"""Free code reaches Pro only through edition.pro_module, and says so plainly when Pro is absent.

"Pro is absent" is simulated the way Python itself reports it: the module's sys.modules entry is
set to None, so `import ado_import` raises ModuleNotFoundError naming it. That runs the real
helper, not a stand-in. In the Shepherd Free export the modules are genuinely missing and these
same tests run unchanged.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

import connection_report as cr
import edition
import gate_auth as ga
import handoff as h
import project_settings as ps
import set_setting as st
import spec_status as ss
from github_import import GitHubImportError

NEEDS_PRO = "needs Shepherd Pro"


@pytest.fixture
def no_pro(monkeypatch):
    """Make the Pro modules these scripts reach unimportable, as they are in Shepherd Free."""
    for name in ("ado_import", "approval_settings"):
        monkeypatch.setitem(sys.modules, name, None)


class TestTheHelper:
    def test_a_present_module_is_returned(self):
        assert edition.pro_module("json", "JSON") is sys.modules["json"]

    def test_an_absent_module_names_the_feature(self, no_pro):
        with pytest.raises(edition.ProRequired, match="Azure DevOps support needs Shepherd Pro") as exc:
            edition.pro_module("ado_import", "Azure DevOps support")
        assert exc.value.module == "ado_import"

    def test_a_broken_pro_module_raises_its_real_error(self, tmp_path, monkeypatch):
        """A Pro customer whose module fails to load must see why, not be told to buy Pro."""
        (tmp_path / "broken_pro.py").write_text("import a_dependency_that_is_not_installed\n", encoding="utf-8")
        monkeypatch.syspath_prepend(str(tmp_path))
        with pytest.raises(ModuleNotFoundError, match="a_dependency_that_is_not_installed"):
            edition.pro_module("broken_pro", "Broken")

    def test_has_pro(self, no_pro):
        assert edition.has_pro("json") is True
        assert edition.has_pro("ado_import") is False


class TestAzureDevOpsWithoutPro:
    def test_connection_report_reads_unknown_never_no(self, tmp_path, no_pro):
        checks, error = cr.ado_checks(tmp_path)
        assert [c["state"] for c in checks] == ["unknown"] * 4
        assert all(NEEDS_PRO in c["detail"] for c in checks)
        assert NEEDS_PRO in error

    def test_gate_auth_status_is_unchecked_not_empty(self, tmp_path, no_pro):
        status = ga._ado_status(tmp_path, SimpleNamespace(remote=None))
        assert status["checked"] is False and status["gates_can_sign_in"] is None
        assert NEEDS_PRO in status["detail"]

    def test_gate_auth_refuses_a_write_with_the_reason(self, tmp_path, no_pro):
        with pytest.raises(ga.GateAuthError, match=NEEDS_PRO):
            ga._refuse_on_ado(tmp_path, SimpleNamespace(remote=None), "create", ga.SUBSCRIPTION_SECRET)

    @pytest.mark.parametrize("module,name", [(h, "assign_on_host"), (ss, "find_pr_for_branch")])
    def test_host_dispatch_fails_through_the_usual_code_host_error(self, module, name, no_pro):
        """GitHubImportError is what every caller already reports as "no code-host access"."""
        with pytest.raises(GitHubImportError, match=NEEDS_PRO):
            module._host_fn(name, "azure-devops")

    @pytest.mark.parametrize("module,name", [(h, "assign_on_host"), (ss, "find_pr_for_branch")])
    def test_the_github_path_does_not_need_pro(self, module, name, no_pro):
        assert module._host_fn(name, "github") is getattr(module, name)


class TestChangeApprovalWithoutPro:
    def test_settings_say_so_and_read_nothing(self, tmp_path, no_pro):
        (tmp_path / ".sdlc").mkdir()
        (tmp_path / ".sdlc" / "approval-settings.yaml").write_text("stages: []\n", encoding="utf-8")
        section = ps.read_approval(tmp_path)
        assert section["unavailable"] == "Change approval needs Shepherd Pro"
        assert section["stages"] == []
        assert "Change approval needs Shepherd Pro." in ps.format_report(ps.read_settings(tmp_path))

    def test_setting_it_is_refused_and_writes_nothing(self, tmp_path, no_pro):
        with pytest.raises(st.SettingError, match=NEEDS_PRO) as exc:
            st.set_approval(tmp_path, "requirements", True, "@priya-n")
        assert exc.value.kind == "pro_required"
        assert not (tmp_path / ".sdlc").exists()
