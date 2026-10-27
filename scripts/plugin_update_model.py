"""Where a Shepherd install stands, and the one step that moves it forward. Pure: no file, no process.

Claude Code owns installing and updating plugins (`claude plugin ...`). This module only reads what
Claude Code recorded (the install registry, the catalogues, the enabled list) and names the next
`claude plugin` command to run. Running that command, re-reading, and naming the next one is the
whole upgrade, whatever the starting point:

  - a 1.x install under the old id `claude-code-sdlc`: the catalogue's `renames` entry moves the
    enabled id to `shepherd` when the catalogue is refreshed; `shepherd` is then installed and any
    leftover old record removed;
  - a 2.x install from the source repository, Shepherd Free or Shepherd Pro: `claude plugin update`;
  - Free and Pro both enabled: Pro replaces Free, so Free is disabled.

A catalogue is identified by where it points, never by its name: `mckruz` is the source repository
for some people and Shepherd Free for others, because Claude Code re-points a catalogue name that is
added again from a second source.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

PLUGIN = "shepherd"
LEGACY_PLUGINS = ("claude-code-sdlc",)

# Where each catalogue can point, lower-cased. The old addresses redirect to the source repository.
ORIGINS = {
    "shepherd-sdlc/shepherd-source": "source",
    "mckruz/shepherd-sdlc": "source",
    "mckruz/claude-code-sdlc": "source",
    "shepherd-sdlc/shepherd": "free",
    "shepherd-sdlc/shepherd-pro": "pro",
}
EDITION_NAMES = {
    "source": "the Shepherd source repository",
    "free": "Shepherd Free",
    "pro": "Shepherd Pro",
    "unknown": "an unrecognised source",
}
# Background updates of these need git to reach GitHub without a prompt.
PRIVATE_EDITIONS = {"source", "pro"}
GITHUB_REPO_RE = re.compile(r"github\.com[:/]+([\w.-]+/[\w.-]+?)(?:\.git)?/?\Z", re.IGNORECASE)

RESTART = "Restart Claude Code, or run /reload-plugins, so the session loads the new version."
APP_FIRST = ("If you use the Shepherd desktop app, update the app first: a 1.x app cannot find a "
             "2.x plugin, while a 2.x app finds either.")
PER_PROJECT = ("In each project set up before 2.0, run /sprd-upgrade: it renames the /sdlc-* "
               "commands in the project's CLAUDE.md and brings the harness forward.")


@dataclass(frozen=True)
class Install:
    plugin: str
    catalogue: str
    version: str
    scope: str = "user"
    project: str = ""

    @property
    def id(self) -> str:
        return f"{self.plugin}@{self.catalogue}"

    @property
    def legacy(self) -> bool:
        return self.plugin in LEGACY_PLUGINS


@dataclass(frozen=True)
class Catalogue:
    name: str
    kind: str                      # github | git | url | directory | unknown
    location: str                  # owner/repo, a URL or a folder
    ref: str = ""
    auto_update: bool = False
    refreshed_at: str = ""
    on_disk: bool = False          # its clone was readable
    plugins: dict[str, str] = field(default_factory=dict)   # plugin name -> version it offers
    renames: dict[str, str] = field(default_factory=dict)
    repo: str = ""                 # owner/repo behind a git URL or a folder's remote, when known

    @property
    def edition(self) -> str:
        key = (self.location if self.kind == "github" else self.repo).lower()
        return ORIGINS.get(key, "unknown")


@dataclass(frozen=True)
class Step:
    argv: tuple[str, ...]
    why: str

    @property
    def command(self) -> str:
        return " ".join(self.argv)


@dataclass(frozen=True)
class Report:
    status: str                    # not-installed | action-needed | update-available | current | unknown
    summary: str
    installed_version: str | None
    current_version: str | None
    next_step: Step | None
    then: tuple[str, ...] = ()
    offers: tuple[str, ...] = ()   # catalogues automatic updates could be turned on for
    notes: tuple[str, ...] = ()


def repo_from_url(url: str) -> str:
    """`owner/repo` from a GitHub URL (https or ssh), else ''."""
    found = GITHUB_REPO_RE.search(url.strip())
    return found.group(1) if found else ""


def version_key(version: str) -> tuple[int, ...] | None:
    """A dotted numeric version as a tuple; None for a commit hash, 'unknown' or anything else."""
    parts = version.split(".")
    return tuple(int(p) for p in parts) if parts and all(p.isdigit() for p in parts) else None


def newer(offered: str, installed: str) -> bool:
    """Whether the catalogue offers something other than (and, when both are numbered, later
    than) what is installed. A hash-versioned plugin is newer whenever the hash differs."""
    a, b = version_key(offered), version_key(installed)
    if a is not None and b is not None:
        return a > b
    return offered != installed


def describe(cat: Catalogue | None, name: str) -> str:
    if cat is None:
        return f"catalogue {name}, which Claude Code no longer lists"
    where = cat.location if cat.kind == "github" else (cat.repo or cat.location)
    pinned = f" pinned to {cat.ref}" if cat.ref else ""
    return f"catalogue {name}, from {EDITION_NAMES[cat.edition]} ({where}{pinned})"


def _scope_args(install: Install) -> tuple[str, ...]:
    return () if install.scope == "user" else ("--scope", install.scope)


def _both_editions(installs: list[Install], cats: dict[str, Catalogue], enabled: dict[str, bool]) -> Step | None:
    """Pro replaces Free; with both enabled every shared command loads twice under one name."""
    live = [i for i in installs if not i.legacy and enabled.get(i.id, True)]
    pro = [i for i in live if cats.get(i.catalogue) and cats[i.catalogue].edition == "pro"]
    other = [i for i in live if i not in pro]
    if pro and other:
        drop = other[0]
        return Step(("claude", "plugin", "disable", drop.id, *_scope_args(drop)),
                    f"{drop.id} and {pro[0].id} are both enabled, so every command they share loads "
                    "twice under the name shepherd. Shepherd Pro replaces the others: keep Pro.")
    return None


def _legacy_step(old: Install, cat: Catalogue | None, installs: list[Install]) -> Step:
    """1.x: refresh the catalogue (its `renames` entry moves the enabled id), install `shepherd`,
    then remove any old record Claude Code kept."""
    # Any edition counts: a 1.x user who installed Pro needs the 1.x plugin removed, not a second Shepherd.
    new = next((i for i in installs if i.plugin == PLUGIN), None)
    if new is not None:
        return Step(("claude", "plugin", "uninstall", old.id, *_scope_args(old)),
                    f"{new.id} is installed; the 1.x plugin beside it still loads its /sdlc-* "
                    "commands and session-start hook.")
    if cat is not None and PLUGIN in cat.plugins:
        return Step(("claude", "plugin", "install", f"{PLUGIN}@{old.catalogue}", *_scope_args(old)),
                    f"Shepherd 1.x ({old.version}) was renamed {PLUGIN} in 2.0. The catalogue "
                    f"offers {PLUGIN} {cat.plugins[PLUGIN]}.")
    return Step(("claude", "plugin", "marketplace", "update", old.catalogue),
                f"Your copy of catalogue {old.catalogue} predates 2.0, so it does not list "
                f"{PLUGIN} yet. Refreshing it also moves the enabled id from {old.plugin} to "
                f"{PLUGIN}.")


def _not_installed(cats: dict[str, Catalogue], enabled: dict[str, bool], notes: list[str]) -> Report:
    # A refreshed 1.x catalogue renames the enabled id and drops the old install record before
    # anything is installed under the new id: enabled, but not installed.
    waiting = sorted(k for k, on in enabled.items() if on and k.split("@")[0] == PLUGIN and "@" in k)
    if not waiting:
        return Report("not-installed", "Shepherd is not installed in this Claude Code.", None, None, None,
                      notes=tuple(notes))
    name = waiting[0].split("@", 1)[1]
    cat = cats.get(name)
    return Report("action-needed", f"{waiting[0]} is enabled but not installed (the 1.x plugin was "
                  "renamed and removed when its catalogue was refreshed).", None,
                  cat.plugins.get(PLUGIN) if cat else None,
                  Step(("claude", "plugin", "install", waiting[0]), f"Installs Shepherd from {describe(cat, name)}."),
                  (APP_FIRST, RESTART, PER_PROJECT), notes=tuple(notes))


def _two_editions(ours: list[Install], cats: dict[str, Catalogue], enabled: dict[str, bool],
                  notes: list[str]) -> Report | None:
    # An id enabled but not installed still loads at the next start (Claude Code installs it), so
    # it counts as a second Shepherd beside Pro.
    installed_ids = {i.id for i in ours}
    pending = [Install(PLUGIN, k.split("@", 1)[1], "not installed") for k, on in sorted(enabled.items())
               if on and "@" in k and k.split("@")[0] == PLUGIN and k not in installed_ids]
    step = _both_editions(ours + pending, cats, enabled)
    if step is None:
        return None
    other = cats.get(step.argv[3].split("@", 1)[1])
    name = EDITION_NAMES[other.edition] if other else "another Shepherd"
    return Report("action-needed", f"{name[0].upper()}{name[1:]} and Shepherd Pro are both enabled.",
                  None, None, step, (RESTART,), notes=tuple(notes))


def _legacy(old: Install, ours: list[Install], cats: dict[str, Catalogue], notes: list[str]) -> Report:
    cat = cats.get(old.catalogue)
    step = _legacy_step(old, cat, ours)
    then = (RESTART, PER_PROJECT) if step.argv[2] == "uninstall" else (APP_FIRST, RESTART, PER_PROJECT)
    return Report("action-needed", f"Shepherd 1.x ({old.version}) is installed as {old.id}, from "
                  f"{describe(cat, old.catalogue)}.", old.version, cat.plugins.get(PLUGIN) if cat else None,
                  step, then, notes=tuple(notes))


def _current_or_behind(ours: list[Install], cats: dict[str, Catalogue], enabled: dict[str, bool],
                       notes: list[str]) -> Report:
    # A disabled install (Free kept beside Pro) is not the one this machine runs.
    ours = [i for i in ours if enabled.get(i.id, True)] or ours
    primary = ours[0]
    cat = cats.get(primary.catalogue)
    where = describe(cat, primary.catalogue)
    offers = tuple(dict.fromkeys(c.name for c in (cats.get(i.catalogue) for i in ours) if c and not c.auto_update))
    if any(cats[n].edition in PRIVATE_EDITIONS for n in offers):
        notes.append("Automatic updates of a private catalogue need git to reach GitHub without a "
                     "prompt. If they never arrive, run: gh auth setup-git")
    if cat is None or not cat.on_disk:
        step = Step(("claude", "plugin", "marketplace", "update", primary.catalogue),
                    f"Claude Code has no readable copy of catalogue {primary.catalogue}.")
        return Report("unknown", f"Shepherd {primary.version} is installed from {where}.",
                      primary.version, None, step, (), offers, tuple(notes))
    if cat.ref:
        notes.append(f"Catalogue {cat.name} follows {cat.ref}, not the repository's default branch; "
                     "if that is a release tag it never moves. To follow new releases, delete "
                     f"\"ref\" from {cat.name}'s entry under extraKnownMarketplaces in your Claude "
                     f"Code settings, then run: claude plugin marketplace add {cat.location}")
    offered = cat.plugins.get(PLUGIN)
    for install in (i for i in ours if i.catalogue == cat.name):
        if offered and newer(offered, install.version):
            step = Step(("claude", "plugin", "update", install.id, *_scope_args(install)),
                        f"Shepherd {offered} is available; this install has {install.version}.")
            return Report("update-available", f"Shepherd {install.version} is installed from {where}.",
                          install.version, offered, step, (RESTART,), offers, tuple(notes))
    as_of = f" (catalogue refreshed {cat.refreshed_at})" if cat.refreshed_at else ""
    return Report("current", f"Shepherd {primary.version} is installed from {where}: up to date{as_of}.",
                  primary.version, offered, None, (), offers, tuple(notes))


def plan(installs: list[Install], catalogues: list[Catalogue], enabled: dict[str, bool],
         project_legacy: tuple[str, ...] = ()) -> Report:
    """The report for a machine's Shepherd installs, in the order the situations must be settled:
    nothing installed, two editions loaded at once, a 1.x install, then current or behind.
    `project_legacy` lists project settings files that still enable the 1.x id."""
    cats = {c.name: c for c in catalogues}
    ours = [i for i in installs if i.plugin == PLUGIN or i.legacy]
    notes = [f"{f} still enables the 1.x id; the next catalogue refresh rewrites it. Commit "
             "that change so the team gets it." for f in project_legacy]
    if not ours:
        return _not_installed(cats, enabled, notes)
    two = _two_editions(ours, cats, enabled, notes)
    if two is not None:
        return two
    old = next((i for i in ours if i.legacy), None)
    if old is not None:
        return _legacy(old, ours, cats, notes)
    return _current_or_behind(ours, cats, enabled, notes)
