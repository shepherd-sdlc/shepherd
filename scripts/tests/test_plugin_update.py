"""plugin_update.py reads what Claude Code recorded, exactly as Claude Code 2.1.310 writes it.

The file shapes below are copied from a sandboxed install (CLAUDE_CONFIG_DIR plus
CLAUDE_CODE_PLUGIN_CACHE_DIR, 2026-10-26). The one write, `auto-update`, changes the user's own
Claude Code settings, so it must keep every other key and refuse rather than guess.
"""

import json

import pytest

import plugin_update as pu


def write(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")


@pytest.fixture
def claude(tmp_path, monkeypatch):
    """An isolated Claude Code: settings in cfg/, registry and catalogues in plugins/."""
    cfg, plugins = tmp_path / "cfg", tmp_path / "plugins"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    monkeypatch.setenv("CLAUDE_CODE_PLUGIN_CACHE_DIR", str(plugins))
    return tmp_path


def catalogue_clone(root, name, version, plugin_json_version=None, renames=None):
    clone = root / "plugins" / "marketplaces" / name
    market = {"name": name, "plugins": [{"name": "shepherd", "source": ".", "version": version}]}
    if renames:
        market["renames"] = renames
    write(clone / ".claude-plugin" / "marketplace.json", market)
    if plugin_json_version:
        write(clone / ".claude-plugin" / "plugin.json", {"name": "shepherd", "version": plugin_json_version})
    return clone


def install(root, plugin_id, version, scope="user"):
    write(root / "plugins" / "installed_plugins.json", {"version": 2, "plugins": {plugin_id: [
        {"scope": scope, "installPath": str(root / "cache" / version), "version": version}]}})


def known(root, name, source, clone, **extra):
    write(root / "plugins" / "known_marketplaces.json",
          {name: {"source": source, "installLocation": str(clone), "lastUpdated": "2026-10-26T19:53:30Z", **extra}})


def test_a_2x_install_behind_its_catalogue_gets_the_update_command(claude, capsys):
    clone = catalogue_clone(claude, "mckruz", "2.1.0")
    install(claude, "shepherd@mckruz", "2.0.0")
    known(claude, "mckruz", {"source": "github", "repo": "shepherd-sdlc/shepherd-source"}, clone)
    assert pu.main(["check", "--project", str(claude), "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["status"] == "update-available"
    assert doc["next_step"]["command"] == "claude plugin update shepherd@mckruz"
    assert doc["catalogues"][0]["edition"] == "source"
    assert doc["auto_update_offers"] == ["mckruz"]


def test_the_plugin_manifest_version_wins_over_the_catalogue_entry(claude):
    # Claude Code resolves plugin.json's version first; reading the entry alone would misreport.
    clone = catalogue_clone(claude, "mckruz", "2.0.0", plugin_json_version="2.1.0")
    offered, _, readable = pu.offered_plugins(clone)
    assert offered == {"shepherd": "2.1.0"} and readable


def test_a_folder_catalogue_is_identified_by_its_git_remote(claude):
    # The shape of a maintainer's machine: catalogue `mckruz` is a local checkout of the source.
    checkout = claude / "checkout"
    catalogue_clone(claude, "unused", "2.1.0")
    (checkout / ".git").mkdir(parents=True)
    (checkout / ".git" / "config").write_text(
        '[core]\n\tbare = false\n[remote "origin"]\n\turl = https://github.com/MCKRUZ/shepherd-sdlc.git\n',
        encoding="utf-8")
    write(checkout / ".claude-plugin" / "marketplace.json",
          {"name": "mckruz", "plugins": [{"name": "shepherd", "source": ".", "version": "2.1.0"}]})
    cats = pu.read_catalogues({"mckruz": {"source": {"source": "directory", "path": str(checkout)},
                                          "installLocation": str(checkout)}}, {})
    assert cats[0].repo == "MCKRUZ/shepherd-sdlc" and cats[0].edition == "source"


def test_a_worktree_folder_follows_gitdir_to_the_shared_config(claude):
    main = claude / "main"
    (main / ".git" / "worktrees" / "wt").mkdir(parents=True)
    (main / ".git" / "config").write_text('[remote "origin"]\n\turl = git@github.com:shepherd-sdlc/shepherd.git\n',
                                          encoding="utf-8")
    (main / ".git" / "worktrees" / "wt" / "commondir").write_text("../..\n", encoding="utf-8")
    wt = claude / "wt"
    wt.mkdir()
    (wt / ".git").write_text(f"gitdir: {main / '.git' / 'worktrees' / 'wt'}\n", encoding="utf-8")
    assert pu.folder_remote(wt) == "shepherd-sdlc/shepherd"


def test_after_the_rename_check_says_install_shepherd(claude, capsys):
    clone = catalogue_clone(claude, "mckruz", "2.1.0", renames={"claude-code-sdlc": "shepherd"})
    write(claude / "plugins" / "installed_plugins.json", {"version": 2, "plugins": {}})
    known(claude, "mckruz", {"source": "github", "repo": "MCKRUZ/shepherd-sdlc"}, clone)
    write(claude / "cfg" / "settings.json", {"enabledPlugins": {"shepherd@mckruz": True}})
    pu.main(["check", "--project", str(claude), "--json"])
    assert json.loads(capsys.readouterr().out)["next_step"]["argv"] == ["claude", "plugin", "install", "shepherd@mckruz"]


def test_project_settings_still_naming_the_1x_id_are_reported(claude):
    write(claude / ".claude" / "settings.json", {"enabledPlugins": {"claude-code-sdlc@mckruz": True}})
    assert pu.project_legacy(claude) == (str(claude / ".claude" / "settings.json"),)


def test_auto_update_sets_the_flag_and_keeps_every_other_setting(claude, capsys):
    clone = catalogue_clone(claude, "mckruz-pro", "2.1.0")
    source = {"source": "github", "repo": "shepherd-sdlc/shepherd-pro"}
    known(claude, "mckruz-pro", source, clone)
    write(claude / "cfg" / "settings.json", {"model": "opus", "enabledPlugins": {"shepherd@mckruz-pro": True}})
    assert pu.main(["auto-update", "--catalogue", "mckruz-pro", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
    doc = json.loads((claude / "cfg" / "settings.json").read_text(encoding="utf-8"))
    assert doc["model"] == "opus" and doc["enabledPlugins"] == {"shepherd@mckruz-pro": True}
    assert doc["extraKnownMarketplaces"]["mckruz-pro"] == {"source": source, "autoUpdate": True}
    # The check now reads it as on, and stops offering.
    report, *_ = pu.check(claude, False)
    assert report.offers == ()


def test_auto_update_refuses_an_unknown_catalogue_and_unreadable_settings(claude):
    write(claude / "plugins" / "known_marketplaces.json", {})
    assert pu.main(["auto-update", "--catalogue", "mckruz"]) == 1
    clone = catalogue_clone(claude, "mckruz", "2.1.0")
    known(claude, "mckruz", {"source": "github", "repo": "shepherd-sdlc/shepherd"}, clone)
    broken = claude / "cfg" / "settings.json"
    broken.parent.mkdir(parents=True, exist_ok=True)
    broken.write_text("{ not json", encoding="utf-8")
    assert pu.main(["auto-update", "--catalogue", "mckruz"]) == 1
    assert broken.read_text(encoding="utf-8") == "{ not json"


def test_refresh_without_claude_on_path_says_so_and_still_checks(claude, monkeypatch, capsys):
    monkeypatch.setattr(pu.shutil, "which", lambda _name: None)
    install(claude, "shepherd@mckruz", "2.1.0")
    assert pu.main(["check", "--refresh", "--project", str(claude), "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["refreshed"] == ["claude is not on PATH, so no catalogue was refreshed"]
    assert doc["status"] == "unknown"


def test_refresh_runs_one_marketplace_update_per_shepherd_catalogue(claude, monkeypatch):
    install(claude, "shepherd@mckruz", "2.1.0")
    calls = []

    class Done:
        returncode, stdout, stderr = 0, "✔ Successfully updated marketplace: mckruz\n", ""

    monkeypatch.setattr(pu.shutil, "which", lambda _name: "claude")
    monkeypatch.setattr(pu.subprocess, "run", lambda argv, **kw: calls.append(argv) or Done())
    pu.check(claude, True)
    assert calls == [["claude", "plugin", "marketplace", "update", "mckruz"]]
