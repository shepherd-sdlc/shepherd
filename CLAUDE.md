# Shepherd — Development Instructions

## What This Is
Shepherd is a Claude Code plugin that runs a software project through its lifecycle, from
discovery to close, using a company-configurable profile. Each phase has documents to produce,
gates that check them, and a named person who signs off.

This repository is Shepherd Free, published under the Apache License 2.0. It is generated from
Shepherd's source on each release, so it has no history of its own and takes no changes directly:
a pull request opened here is closed automatically. Report a bug or ask for a change in an issue;
a fix is made in the source and appears here in the next release.

## Layout
- `.claude-plugin/plugin.json` — the plugin manifest
- `SKILL.md` — the main skill, loaded when the plugin activates
- `commands/` — the slash commands (`/sprd`, `/sprd-setup`, `/sprd-status`, `/sprd-next`, `/sprd-gate`, `/sprd-spec`, `/sprd-handoff`, `/sprd-review`, ...)
- `agents/` — the agents the commands start
- `phases/` — the phase definitions; `phases/phase-registry.yaml` owns their order
- `profiles/` — `starter` and the schema every profile is validated against
- `references/` — documents loaded on demand
- `templates/` — the documents copied into a project
- `harness/` — the delivery harness `/sprd-harness` installs: CI rails, hooks, agents and skills
- `hooks/` — session-start hooks, PowerShell and shell twins
- `scripts/` — the Python automation, run with `uv`

## Conventions
- Scripts use Python 3.12+ via `uv`. Every `--json` mode prints exactly one JSON document.
- A profile is validated against `profiles/_schema.yaml`.
- Phase definitions use RFC 2119 keywords (MUST/SHOULD/MAY).
- A project's state lives in its own `.sdlc/state.yaml`.
- Reports read "no data" where nothing was measured, never a fabricated zero.
- Every agent and command runs two ways: inside the phase workflow (reading `.sdlc/`), and
  standalone against inputs it is pointed at, saying in its output what context was missing.

## Testing
```bash
uv run --project scripts pytest scripts/tests -q
uv run scripts/validate_profile.py profiles/starter/profile.yaml
uv run scripts/init_project.py --profile profiles/starter/profile.yaml --target /tmp/test
uv run scripts/check_gates.py --state /tmp/test/.sdlc/state.yaml --phase 0
uv run scripts/new_spec.py --repo /tmp/test --name "duplicate claim 409" --risk HIGH
uv run scripts/check_spec.py --spec /tmp/test/specs/0001-duplicate-claim-409.md
uv run scripts/doctor.py --repo /tmp/test --offline --json
```
