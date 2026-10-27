"""The next-step decision for every starting point a Shepherd install can be in.

Each case is a real state measured in a sandboxed Claude Code (2.1.310) on 2026-10-26: a 1.x
install before and after its catalogue gained the `renames` entry, a 2.x install behind the
catalogue, Free and Pro side by side. The step must be the one `claude plugin` command that moves
that state forward, because /sprd-update runs exactly that and checks again.
"""

import plugin_update_model as m

SOURCE = m.Catalogue("mckruz", "github", "shepherd-sdlc/shepherd-source", on_disk=True,
                     plugins={"shepherd": "2.1.0"}, renames={"claude-code-sdlc": "shepherd"})
OLD_SOURCE = m.Catalogue("mckruz", "github", "MCKRUZ/shepherd-sdlc", on_disk=True,
                         plugins={"claude-code-sdlc": "1.6.2"})
FREE = m.Catalogue("mckruz", "github", "shepherd-sdlc/shepherd", on_disk=True, plugins={"shepherd": "2.1.0"})
def argv(report):
    assert report.next_step is not None, report.summary
    return report.next_step.argv


PRO = m.Catalogue("mckruz-pro", "github", "shepherd-sdlc/shepherd-pro", on_disk=True,
                  plugins={"shepherd": "2.1.0"})


def test_a_catalogue_is_identified_by_where_it_points_not_its_name():
    # `mckruz` is the source for some people and Free for others: Claude Code re-points a name.
    assert SOURCE.edition == "source" and FREE.edition == "free" and PRO.edition == "pro"
    assert OLD_SOURCE.edition == "source"  # the pre-transfer address redirects to the source
    folder = m.Catalogue("mckruz", "directory", "C:/code/shepherd", repo="shepherd-sdlc/shepherd-source")
    assert folder.edition == "source"
    assert m.Catalogue("x", "github", "someone/else").edition == "unknown"


def test_repo_from_url_reads_https_and_ssh_remotes():
    assert m.repo_from_url("https://github.com/shepherd-sdlc/shepherd-pro.git") == "shepherd-sdlc/shepherd-pro"
    assert m.repo_from_url("git@github.com:MCKRUZ/shepherd-sdlc.git") == "MCKRUZ/shepherd-sdlc"
    assert m.repo_from_url("https://example.com/a/b") == ""


def test_1x_on_a_stale_catalogue_refreshes_it_first():
    # The installed 1.x code is frozen; only the catalogue can carry the rename, so it goes first.
    old = m.Install("claude-code-sdlc", "mckruz", "1.6.2")
    report = m.plan([old], [OLD_SOURCE], {"claude-code-sdlc@mckruz": True})
    assert report.status == "action-needed"
    assert argv(report) == ("claude", "plugin", "marketplace", "update", "mckruz")
    assert m.APP_FIRST in report.then and m.PER_PROJECT in report.then


def test_1x_whose_catalogue_already_offers_shepherd_installs_it():
    old = m.Install("claude-code-sdlc", "mckruz", "1.6.2")
    report = m.plan([old], [SOURCE], {})
    assert argv(report) == ("claude", "plugin", "install", "shepherd@mckruz")
    assert report.current_version == "2.1.0"


def test_after_the_rename_shepherd_is_enabled_but_not_installed():
    # Measured: the refresh rewrote enabledPlugins and dropped the 1.x record, installing nothing.
    report = m.plan([], [SOURCE], {"shepherd@mckruz": True})
    assert report.status == "action-needed"
    assert argv(report) == ("claude", "plugin", "install", "shepherd@mckruz")


def test_a_1x_record_left_beside_shepherd_is_uninstalled():
    old = m.Install("claude-code-sdlc", "mckruz", "1.6.2")
    new = m.Install("shepherd", "mckruz", "2.1.0")
    report = m.plan([old, new], [SOURCE], {})
    assert argv(report) == ("claude", "plugin", "uninstall", "claude-code-sdlc@mckruz")


def test_a_1x_user_who_installed_pro_has_the_1x_plugin_removed_not_a_second_shepherd():
    old = m.Install("claude-code-sdlc", "mckruz", "1.6.2")
    pro = m.Install("shepherd", "mckruz-pro", "2.1.0")
    report = m.plan([old, pro], [SOURCE, PRO], {})
    assert argv(report) == ("claude", "plugin", "uninstall", "claude-code-sdlc@mckruz")


def test_a_renamed_id_left_enabled_beside_pro_is_disabled():
    # 1.x moved to Pro: the rename enabled shepherd@mckruz, which Claude Code installs at next start.
    pro = m.Install("shepherd", "mckruz-pro", "2.1.0")
    report = m.plan([pro], [SOURCE, PRO], {"shepherd@mckruz": True, "shepherd@mckruz-pro": True})
    assert argv(report) == ("claude", "plugin", "disable", "shepherd@mckruz")
    assert report.summary.startswith("The Shepherd source repository and Shepherd Pro")


def test_a_project_scoped_install_keeps_its_scope_in_the_command():
    old = m.Install("claude-code-sdlc", "mckruz", "1.6.2", scope="project")
    report = m.plan([old], [SOURCE], {})
    assert argv(report)[-2:] == ("--scope", "project")


def test_2x_behind_its_catalogue_is_updated():
    report = m.plan([m.Install("shepherd", "mckruz", "2.0.0")], [SOURCE], {})
    assert report.status == "update-available"
    assert argv(report) == ("claude", "plugin", "update", "shepherd@mckruz")
    assert (report.installed_version, report.current_version) == ("2.0.0", "2.1.0")


def test_versions_compare_as_numbers_not_text():
    assert m.newer("2.10.0", "2.9.0") and not m.newer("2.9.0", "2.10.0")
    assert not m.newer("2.1.0", "2.1.0")
    assert m.newer("abc123def456", "0123456789ab")  # a hash-versioned plugin: any change is new


def test_current_install_has_no_step_and_says_how_fresh_the_catalogue_is():
    cat = m.Catalogue("mckruz", "github", "shepherd-sdlc/shepherd", refreshed_at="2026-10-26T19:55Z",
                      on_disk=True, plugins={"shepherd": "2.1.0"}, auto_update=True)
    report = m.plan([m.Install("shepherd", "mckruz", "2.1.0")], [cat], {})
    assert report.status == "current" and report.next_step is None
    assert "2026-10-26T19:55Z" in report.summary and report.offers == ()


def test_automatic_updates_are_offered_when_off_with_the_private_repo_caveat():
    report = m.plan([m.Install("shepherd", "mckruz-pro", "2.1.0")], [PRO], {})
    assert report.offers == ("mckruz-pro",)
    assert any("gh auth setup-git" in n for n in report.notes)
    free = m.plan([m.Install("shepherd", "mckruz", "2.1.0")], [FREE], {})
    assert free.offers == ("mckruz",) and not any("gh auth" in n for n in free.notes)


def test_free_and_pro_both_enabled_disables_free():
    installs = [m.Install("shepherd", "mckruz", "2.1.0"), m.Install("shepherd", "mckruz-pro", "2.1.0")]
    report = m.plan(installs, [FREE, PRO], {})
    assert argv(report) == ("claude", "plugin", "disable", "shepherd@mckruz")
    assert report.summary == "Shepherd Free and Shepherd Pro are both enabled."
    # Already disabled: no collision, and the report is about Pro, the install that runs.
    after = m.plan(installs, [FREE, PRO], {"shepherd@mckruz": False})
    assert after.next_step is None
    assert "Shepherd Pro" in after.summary and after.offers == ("mckruz-pro",)


def test_a_pinned_catalogue_is_named_because_it_never_moves():
    pinned = m.Catalogue("mckruz", "github", "shepherd-sdlc/shepherd-source", ref="v2.0.0", on_disk=True,
                         plugins={"shepherd": "2.0.0"})
    report = m.plan([m.Install("shepherd", "mckruz", "2.0.0")], [pinned], {})
    assert report.status == "current"
    assert any("follows v2.0.0" in n for n in report.notes)


def test_an_unreadable_catalogue_is_unknown_not_current():
    gone = m.Catalogue("mckruz", "github", "shepherd-sdlc/shepherd")
    report = m.plan([m.Install("shepherd", "mckruz", "2.1.0")], [gone], {})
    assert report.status == "unknown"
    assert argv(report) == ("claude", "plugin", "marketplace", "update", "mckruz")


def test_project_settings_naming_the_old_id_are_flagged_for_a_commit():
    report = m.plan([], [], {}, project_legacy=(".claude/settings.json",))
    assert report.status == "not-installed"
    assert any(".claude/settings.json" in n and "Commit" in n for n in report.notes)
