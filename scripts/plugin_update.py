"""plugin_update.py: is this machine's Shepherd current, and what is the one step to take.

    uv run scripts/plugin_update.py check [--refresh] [--project DIR] [--json]
    uv run scripts/plugin_update.py auto-update --catalogue NAME [--json]

`check` reads what Claude Code recorded about its plugins and prints where Shepherd stands and the
next `claude plugin` command to run (the decision is `plugin_update_model.plan`). It changes
nothing, except that `--refresh` first runs `claude plugin marketplace update` for each catalogue
Shepherd comes from, which is what Claude Code's own automatic update does. Exit 0 on every path.

`auto-update` turns on Claude Code's automatic updates for one catalogue, by setting `autoUpdate` on
that catalogue's `extraKnownMarketplaces` entry in the user settings file. Only after a person says
yes: it changes their Claude Code settings. Exit 0 done, 1 refused (nothing written).

Where Claude Code keeps things: the settings file is in `CLAUDE_CONFIG_DIR` (else ~/.claude); the
plugin registry and catalogues are in `CLAUDE_CODE_PLUGIN_CACHE_DIR` (else ~/.claude/plugins),
which `CLAUDE_CONFIG_DIR` does not move.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import plugin_update_model as model

PLUGIN_NAMES = (model.PLUGIN, *model.LEGACY_PLUGINS)


def config_dir() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def plugins_dir() -> Path:
    return Path(os.environ.get("CLAUDE_CODE_PLUGIN_CACHE_DIR") or Path.home() / ".claude" / "plugins")


def read_json(path: Path) -> dict:
    """A JSON object from `path`, or {} when it is absent or unreadable."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def settings_files(project: Path) -> list[Path]:
    """Claude Code's settings in the order a later value wins: user, project, local."""
    return [config_dir() / "settings.json", project / ".claude" / "settings.json",
            project / ".claude" / "settings.local.json"]


def read_installs(registry: dict) -> list[model.Install]:
    found = []
    for plugin_id, entries in (registry.get("plugins") or {}).items():
        plugin, _, catalogue = plugin_id.partition("@")
        if plugin not in PLUGIN_NAMES or not isinstance(entries, list):
            continue
        for e in entries:
            if isinstance(e, dict):
                found.append(model.Install(plugin, catalogue, str(e.get("version") or "unknown"),
                                           str(e.get("scope") or "user"), str(e.get("projectPath") or "")))
    return found


def folder_remote(folder: Path) -> str:
    """`owner/repo` of a folder's `origin` remote on GitHub, read from git's own config file."""
    git = folder / ".git"
    try:
        if git.is_file():  # a worktree: .git names the real git dir, whose commondir has the config
            git = (folder / git.read_text(encoding="utf-8").split(":", 1)[1].strip()).resolve()
            common = git / "commondir"
            if common.is_file():
                git = (git / common.read_text(encoding="utf-8").strip()).resolve()
        lines = (git / "config").read_text(encoding="utf-8").splitlines()
    except (OSError, IndexError):
        return ""
    in_origin = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("["):
            in_origin = stripped == '[remote "origin"]'
        elif in_origin and stripped.startswith("url") and "=" in stripped:
            return model.repo_from_url(stripped.split("=", 1)[1])
    return ""


def offered_plugins(clone: Path) -> tuple[dict[str, str], dict[str, str], bool]:
    """What a catalogue clone offers (plugin -> version, as Claude Code resolves it: the plugin's
    own manifest first, then the catalogue entry), its renames, and whether it was readable."""
    market = read_json(clone / ".claude-plugin" / "marketplace.json")
    offered = {}
    for entry in market.get("plugins") or []:
        if not isinstance(entry, dict) or not entry.get("name"):
            continue
        version = entry.get("version")
        source = entry.get("source")
        if isinstance(source, str):
            own = read_json(clone / source / ".claude-plugin" / "plugin.json").get("version")
            version = own or version
        offered[str(entry["name"])] = str(version or "unknown")
    raw = market.get("renames")
    renames = raw if isinstance(raw, dict) else {}
    return offered, {str(k): str(v) for k, v in renames.items()}, bool(market)


def read_catalogues(known: dict, user_settings: dict) -> list[model.Catalogue]:
    declared = user_settings.get("extraKnownMarketplaces") or {}
    found = []
    for name, entry in known.items():
        if not isinstance(entry, dict):
            continue
        raw = entry.get("source")
        source: dict = raw if isinstance(raw, dict) else {}
        kind = str(source.get("source") or "unknown")
        location = str(source.get("repo") or source.get("url") or source.get("path") or "")
        clone = Path(str(entry.get("installLocation") or location or "."))
        repo = folder_remote(Path(location)) if kind == "directory" else model.repo_from_url(location)
        mine = declared.get(name)
        auto = mine.get("autoUpdate") if isinstance(mine, dict) else None
        if not isinstance(auto, bool):
            auto = entry.get("autoUpdate") is True
        offered, renames, readable = offered_plugins(clone)
        found.append(model.Catalogue(name, kind, location, str(source.get("ref") or source.get("sha") or ""),
                                     auto, str(entry.get("lastUpdated") or ""), readable, offered, renames, repo))
    return found


def enabled_map(project: Path) -> dict[str, bool]:
    merged: dict[str, bool] = {}
    for path in settings_files(project):
        for key, value in (read_json(path).get("enabledPlugins") or {}).items():
            if isinstance(value, bool):
                merged[key] = value
    return merged


def project_legacy(project: Path) -> tuple[str, ...]:
    """Project settings files (which teams commit) that still enable a 1.x id."""
    files = settings_files(project)[1:]
    return tuple(str(p) for p in files
                 if any(k.split("@")[0] in model.LEGACY_PLUGINS for k in read_json(p).get("enabledPlugins") or {}))


def refresh(names: list[str]) -> list[str]:
    """Run `claude plugin marketplace update` per catalogue; one line of outcome each."""
    claude = shutil.which("claude")
    if not claude:
        return ["claude is not on PATH, so no catalogue was refreshed"]
    out = []
    for name in names:
        try:
            proc = subprocess.run([claude, "plugin", "marketplace", "update", name], capture_output=True,
                                  text=True, encoding="utf-8", errors="replace", timeout=300)
            last = (proc.stdout.strip() or proc.stderr.strip()).splitlines()[-1:] or ["no output"]
            out.append(f"{name}: {'refreshed' if proc.returncode == 0 else 'not refreshed'} ({last[0].strip()})")
        except (OSError, subprocess.TimeoutExpired) as exc:
            out.append(f"{name}: not refreshed ({exc})")
    return out


def check(project: Path, do_refresh: bool) -> tuple[model.Report, list[model.Catalogue], list[model.Install], list[str]]:
    refreshed: list[str] = []
    if do_refresh:
        names = sorted({i.catalogue for i in read_installs(read_json(plugins_dir() / "installed_plugins.json"))})
        refreshed = refresh(names)
    installs = read_installs(read_json(plugins_dir() / "installed_plugins.json"))
    catalogues = read_catalogues(read_json(plugins_dir() / "known_marketplaces.json"),
                                 read_json(config_dir() / "settings.json"))
    report = model.plan(installs, catalogues, enabled_map(project), project_legacy(project))
    return report, catalogues, installs, refreshed


def set_auto_update(name: str) -> tuple[bool, str]:
    """Turn on automatic updates for catalogue `name` in the user settings file."""
    known = read_json(plugins_dir() / "known_marketplaces.json").get(name)
    if not isinstance(known, dict) or not isinstance(known.get("source"), dict):
        return False, f"Claude Code has no catalogue named {name}; nothing was changed."
    path = config_dir() / "settings.json"
    try:
        raw = path.read_text(encoding="utf-8-sig") if path.exists() else "{}"
        doc = json.loads(raw)
    except (OSError, ValueError) as exc:
        return False, f"{path} could not be read as JSON ({exc}); nothing was changed."
    if not isinstance(doc, dict):
        return False, f"{path} is not a JSON object; nothing was changed."
    declared = doc.setdefault("extraKnownMarketplaces", {})
    entry = declared.setdefault(name, {"source": known["source"]})
    if entry.get("autoUpdate") is True:
        return True, f"Automatic updates are already on for catalogue {name}."
    entry["autoUpdate"] = True
    text = json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
    tmp = path.with_name(path.name + ".shepherd-tmp")
    tmp.write_text(text.replace("\n", "\r\n") if "\r\n" in raw else text, encoding="utf-8")
    os.replace(tmp, path)
    return True, (f"Automatic updates are on for catalogue {name} ({path}). Claude Code checks it "
                  "after a session starts and applies an update on the next launch.")


def as_json(report: model.Report, catalogues, installs, refreshed) -> dict:
    step = report.next_step
    return {
        "status": report.status, "summary": report.summary,
        "installed_version": report.installed_version, "current_version": report.current_version,
        "next_step": {"command": step.command, "argv": list(step.argv), "why": step.why} if step else None,
        "then": list(report.then), "auto_update_offers": list(report.offers), "notes": list(report.notes),
        "installs": [{"id": i.id, "version": i.version, "scope": i.scope, "legacy": i.legacy} for i in installs],
        "catalogues": [{"name": c.name, "edition": c.edition, "kind": c.kind, "location": c.location,
                        "repo": c.repo or None, "ref": c.ref or None, "auto_update": c.auto_update,
                        "refreshed_at": c.refreshed_at or None,
                        "offers": c.plugins.get(model.PLUGIN)} for c in catalogues
                       if any(i.catalogue == c.name for i in installs)],
        "refreshed": refreshed,
    }


def as_text(report: model.Report, refreshed: list[str]) -> str:
    lines = [f"Refreshed {r}" for r in refreshed] + [report.summary]
    if report.current_version and report.status != "current":
        lines.append(f"Current release in that catalogue: {report.current_version}")
    if report.next_step:
        lines += ["", "Next step:", f"  {report.next_step.command}", f"  ({report.next_step.why})"]
    if report.then:
        lines += ["", "Then:"] + [f"  - {t}" for t in report.then]
    for name in report.offers:
        lines += ["", f"Automatic updates are off for catalogue {name}. To have new releases arrive by "
                      f"themselves, say yes when /sprd-update offers it, or in Claude Code open /plugin, "
                      f"then Marketplaces, {name}, Enable auto-update."]
    if report.notes:
        lines += [""] + [f"Note: {n}" for n in report.notes]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    verbs = parser.add_subparsers(dest="verb", required=True)
    c = verbs.add_parser("check", help="where Shepherd stands and the next step (changes nothing)")
    c.add_argument("--refresh", action="store_true",
                   help="first run `claude plugin marketplace update` for each Shepherd catalogue")
    c.add_argument("--project", default=".", help="project whose .claude settings to read (default: here)")
    c.add_argument("--json", action="store_true", help="print one JSON document")
    a = verbs.add_parser("auto-update", help="turn on Claude Code's automatic updates for a catalogue")
    a.add_argument("--catalogue", required=True, help="catalogue name, e.g. mckruz")
    a.add_argument("--json", action="store_true", help="print one JSON document")
    args = parser.parse_args(argv)

    if args.verb == "auto-update":
        ok, message = set_auto_update(args.catalogue)
        print(json.dumps({"ok": ok, "catalogue": args.catalogue, "message": message}) if args.json else message)
        return 0 if ok else 1
    report, catalogues, installs, refreshed = check(Path(args.project).resolve(), args.refresh)
    print(json.dumps(as_json(report, catalogues, installs, refreshed), indent=2) if args.json
          else as_text(report, refreshed))
    return 0


if __name__ == "__main__":
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure:
        reconfigure(encoding="utf-8")
    sys.exit(main())
