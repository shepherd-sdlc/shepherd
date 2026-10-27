# /sprd-update — Bring Shepherd itself up to date

Say which Shepherd this machine runs, what the current release is, and the one step that moves it
forward. Run that step when the person agrees, then check again, until Shepherd is current. Then offer
to turn on automatic updates so the next release arrives without anyone asking.

Claude Code does the installing (`claude plugin ...`); this command only decides which of its commands
comes next. It works from any starting point Claude Code can see: a 1.x install under the old id
`claude-code-sdlc`, a 2.x install, Shepherd Free, Shepherd Pro, or Free and Pro side by side.

This updates the **plugin**. `/sprd-upgrade` is the per-project step that brings a repository's
installed harness up to the plugin's version: run it in each project after this command.

## Modes

The plugin is installed per machine, not per project, so there is one mode and it needs no `.sdlc/`.
Run it from anywhere. When it runs inside a project, it also reads that project's `.claude/settings.json`
and `.claude/settings.local.json` and says if either still names the 1.x id (a file teams commit).

## Instructions

1. **Check, refreshing the catalogues first.** The refresh is what Claude Code's own automatic update
   does: it fetches the catalogue Shepherd comes from so the check compares against the latest release.
   ```bash
   uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/plugin_update.py check --refresh
   ```
   Add `--json` to read the same report as data (`status`, `next_step.argv`, `then`,
   `auto_update_offers`, `notes`). `--project <path>` reads another project's settings.

2. **Tell the person where they stand, in plain words.** Read them the summary line: which version,
   from which catalogue, and which edition that catalogue really is. The edition comes from where the
   catalogue points, not its name, because Claude Code re-points a catalogue name that is added a
   second time from another source.

3. **Offer the next step, and run it only on a yes.** Show the exact command and the reason the report
   gives. It changes which plugin Claude Code loads, so never run it without the person agreeing. On a
   yes, run exactly the command the report printed, then go back to step 1. Repeat until there is no
   next step. Typical sequences:
   - 1.x (`/sdlc-*` commands): `claude plugin install shepherd@mckruz`, after the refresh in step 1
     has renamed the enabled id. A leftover 1.x record is removed with `claude plugin uninstall`.
   - 2.x behind the catalogue: `claude plugin update shepherd@mckruz`.
   - Free and Pro both enabled: `claude plugin disable` on the Free one. Pro replaces Free.

   If a step fails, show Claude Code's message verbatim and stop. Do not improvise a different
   command.

4. **Offer automatic updates** for each catalogue the report lists under `auto_update_offers`. They
   are off by default for every catalogue that is not Anthropic's. With them on, Claude Code checks
   the catalogue after a session starts and installs a new release for the next launch. On a yes:
   ```bash
   uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/plugin_update.py auto-update --catalogue mckruz
   ```
   This sets `autoUpdate` on that catalogue in the person's Claude Code settings file and touches
   nothing else. If the report notes that the catalogue is private, tell them background updates need
   git to reach GitHub without a prompt, and that `gh auth setup-git` sets that up. Never run it for
   them: it changes their git configuration.

5. **Finish with the report's `then` lines.** Usually: restart Claude Code or run `/reload-plugins`
   (the running session keeps the version it loaded), update the Shepherd desktop app before the
   plugin if moving from 1.x, and run `/sprd-upgrade` in each project set up before 2.0.

## Arguments

- `check`: `--refresh` (refresh the catalogues first), `--project <path>`, `--json`.
- `auto-update`: `--catalogue <name>` (required), `--json`.

## Exit codes

`check` exits 0 on every path: it is advisory. `auto-update` exits 0 when automatic updates are on and
1 when it refused (no such catalogue, or a settings file that is not valid JSON), having written nothing.

## Where Claude Code keeps what this reads

The settings file is in `CLAUDE_CONFIG_DIR` (default `~/.claude`). The plugin registry and catalogues
are in `CLAUDE_CODE_PLUGIN_CACHE_DIR` (default `~/.claude/plugins`); `CLAUDE_CONFIG_DIR` does not move
them. To try this without touching a real install, set both to empty folders.

See `docs/updating.md` for the manual route from each starting point.
