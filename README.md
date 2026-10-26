# Shepherd

Shepherd is an SDLC orchestration plugin for Claude Code. It drives projects through a structured software development lifecycle — gated opening and closing phases around a continuous Build loop — with company-configurable profiles, compliance gates, and quality enforcement.

## Why This Exists

No existing tool combines specification-driven development + quality enforcement + compliance gates + company configurability into one executable workflow. This plugin makes the AI-SDLC methodology executable inside Claude Code.

## Features

- **9 SDLC phases** — Discovery, Requirements, Design, Foundation, the continuous **Build loop**, Documentation, Deployment, Monitoring, Close & Transfer. The gap where batch Implementation/Quality/Testing used to be is intentional — checking happens per change inside the Build loop, never as a later batch phase.
- **Project type routing** — testing, deployment, and monitoring adapt automatically based on `project_type` (service, app, library, skill, cli)
- **Company profiles** — YAML configs for stack, quality thresholds, compliance, conventions
- **7-gate validation** — Integrity, completeness, metrics, compliance, consistency, quality checks at every transition, plus the phase's own exit criteria rendered for the human who signs
- **Frozen layers** — Token-efficient phase summaries enabling cross-phase context continuity
- **3-tier context architecture** — Foundation (always), frozen layers (per-phase), references (on-demand)
- **Narrative enhancement** — Optional stakeholder-friendly `.narrative.md` companions for technical artifacts
- **Conversational coaching** — Adaptive dialogue mode for guided phase completion
- **NFR measurement basis enforcement** — Every numeric threshold must declare its measurement source; aspirational thresholds require an agreed validation plan in the Build loop
- **Test traceability** — the Build loop requires scenario-to-requirement mapping and redundancy audit before test execution
- **Compliance enforcement** — a profile's compliance gate files (SOC 2, HIPAA, GDPR, PCI-DSS) are injected into Gate 4 and block at MUST severity
- **Skill orchestration** — Maps phases to existing skills (`/deep-plan`, `/deep-implement`, `/tdd`, `/code-review`, `/security-review`, `/e2e`)
- **State machine** — Tracks progress in `.sdlc/state.yaml` with full audit trail
- **Artifact checksums + dirty tracking** — SHA-256 hashes detect changed artifacts; gate checks skip unchanged files for faster validation
- **Smart repair** — Gate failures on structural issues (missing templates, placeholders) are auto-fixed before escalating to human
- **Dependency graph enforcement** — Section dependency DAG validated in the Build loop; circular dependencies detected; implementation order enforced
- **Multi-perspective review** — `/sprd-review` with adversarial, edge-case, and council modes for thorough artifact review
- **Brainstorming techniques** — SCAMPER, reverse brainstorming, constraint removal, and 3 more structured ideation methods with anti-bias protocol
- **Brownfield detection** — Auto-detects existing codebases and generates workspace analysis before Discovery begins
- **Structured error specs** — P0/P1 requirements must define Accepts/Returns/Errors explicitly
- **Cross-artifact validation** — File-level reference checking between artifacts (SHOULD severity)
- **Question-to-file audit trail** — Open questions written to persistent markdown files for team collaboration
- **Test expansion protocol** — Healer (diagnose failures), Expander (add edge cases), bug-to-test pipeline (RED first)
- **Parallel review resolution** — Batch review findings by file, resolve in parallel, re-verify after fix
- **Advanced elicitation** — Constraint analysis, inverse thinking, pre-mortem, 5 whys, and more for coaching mode
- **Phase-aware context** — Hooks inject current phase reminders and conventions
- **Session health check** — Opt-in pre-flight build verification at session start (Build loop) catches broken builds before the agent compounds them with new work
- **Visual regression testing** — Optional screenshot capture during Build-loop E2E testing with baseline comparison (manual or pixel-diff)
- **Single-change guardrail** — Explicit constraint preventing simultaneous work on multiple specs in the Build loop unless explicitly parallelizable
- **Phase-scoped evaluation criteria** — Quality rubrics that apply to non-code artifacts (requirements, design, foundation) in addition to code
- **Empirical metrics logging** — JSONL instrumentation in gates, frozen layer validation, and section evaluation for evidence-based harness optimization


## Installation

### Via the plugin marketplace (recommended)

One marketplace add, one install — brings the orchestration commands **and** the delivery harness:

```
/plugin marketplace add MCKRUZ/shepherd
/plugin install shepherd@mckruz
```

Then, per project: `/sprd-setup` initializes `.sdlc/` **and installs the full delivery harness**
(governance `CLAUDE.md`, `.claude/{settings,hooks,agents,skills}`, 7 CI workflows in
`.github/workflows/` — 5 rail gates plus 2 eval workflows — of which five checks (build-and-test,
spec-gate, grader, correctness-review, security-review) block at merge via the
branch-protection ruleset, and `infra/` starters). To add or refresh just the
harness in an existing repo, use `/sprd-harness`. Requires Claude Code v2.1.196+ (`source: "."`).

### As a Claude Code Skill (local dev)

```bash
# Clone the repo
git clone https://github.com/MCKRUZ/shepherd.git

# Symlink to your Claude Code skills directory
# Windows
mklink /D "%USERPROFILE%\.claude\skills\shepherd" "path\to\shepherd"

# macOS/Linux
ln -s /path/to/shepherd ~/.claude/skills/shepherd
```

### Dependencies

The plugin uses Python scripts via [uv](https://github.com/astral-sh/uv):

```bash
# Install uv (if not already installed)
pip install uv
# or
brew install uv

# Install script dependencies
cd shepherd/scripts
uv sync
```

### Code hosts

The plugin talks to the repository's code host for the pull-request-facing work — a spec's
live status, the hand-off's draft PR, the connection report, branch policies, the gates'
credentials, and the scorecard import. On GitHub it uses the GitHub CLI (`gh`). `gh` is not
required to open a project, run the gates, or read the spec backlog; it is
required only for the features that read or write pull requests, and each of those says it is
missing instead of failing.

| Feature | GitHub |
|---|---|
| `/sprd-spec-status`, `/sprd-handoff` (the draft PR and reviewer request), `connection_report.py`, `gate_auth.py status` | `gh`, signed in |
| Scorecard import | `scorecard.py import` |
| `gate_auth.py set` / `clear` | `gh` |

Pipelines, secrets and `/sprd-doctor` follow the **installed CI pack**
(`.claude/harness-manifest.json`), not the remote — a GitHub repository on Azure Pipelines is a
legitimate mix and is reported, never resolved silently.

`code_host.py --repo <path>` says which host was detected, why, and whether its CLI answered.
When the remote cannot be recognised (GitHub Enterprise Server, an unusual proxy),
`.sdlc/code-host.yaml` pins the host for that clone — written with
`uv run scripts/set_setting.py --repo <path> code-host --host <host>`. A one-off override is
`--host` on any host-touching script, or the `SHEPHERD_CODE_HOST` environment variable
(`SDLC_CODE_HOST` is still read, so existing shells and CI keep working).
Full rules: `references/code-host-providers.md`.


## Quick Start

```
1. /sprd-setup          → Select profile, initialize .sdlc/ AND install the delivery harness
2. /sprd                → See Phase 0: Discovery guidance
3. Create artifacts     → Write problem-statement.md in .sdlc/artifacts/00-discovery/
4. /sprd-gate           → Check if exit criteria are met
5. /sprd-next           → Advance to Phase 1: Requirements
6. /sprd-status         → View progress dashboard
```

## Documentation

For in-depth technical documentation, see the guides in [`docs/`](docs/):

| Guide | Description |
|-------|-------------|
| [Architecture](docs/architecture.md) | Plugin anatomy, component relationships, data flow diagrams, two-directory model, progressive disclosure strategy |
| [Phase Lifecycle](docs/phase-lifecycle.md) | All 9 phases in depth — workflows, artifacts, HITL gates, skills, agents, handoff protocol, project type adaptations |
| [Gate System](docs/gate-system.md) | 7-gate validation — integrity, completeness, metrics, compliance, consistency, quality, exit criteria — severity levels, override protocol |
| [Profiles](docs/profiles.md) | Schema reference (every field), built-in profiles, custom profile creation, compliance framework integration, evaluation criteria |
| [Commands](docs/commands.md) | Every slash command — internal flow, state changes, Python scripts called, error scenarios, examples |
| [Agents](docs/agents.md) | The custom agents + built-in subagent orchestration, phase-to-agent mapping, parallel execution rules, mandatory spawns |
| [State Machine](docs/state-machine.md) | state.yaml format, transition rules, history tracking, the spec backlog |
| [Templates & Artifacts](docs/templates-artifacts.md) | Template directory structure, per-phase artifact details, handoff document protocol, artifact lifecycle |
| [Scripts](docs/scripts.md) | All Python scripts (incl. `phase_model.py`, the phase-identity source of truth) — CLI args, inputs/outputs, exit codes, gate implementation details, uv runtime |
| [Integrations](docs/integrations.md) | How /deep-plan, /deep-implement, /tdd, /code-review map into SDLC phases, artifact transformation pipeline |
| [Hooks](docs/hooks.md) | Session-start and phase-inject hooks — what they read, what they inject, convention reminders |


## Commands

| Command | Purpose |
|---------|---------|
| `/sprd-setup` | Interactive setup wizard — select profile, initialize project |
| `/sprd` | Show current phase guidance, next action, required artifacts |
| `/sprd-status` | Progress dashboard with phase table and completion % |
| `/sprd-gate` | Run 7-gate exit criteria check (does not advance) |
| `/sprd-next` | Advance to next phase if all MUST gates pass |
| `/sprd-enhance` | Generate narrative companions for stakeholder review (optional) |
| `/sprd-coach` | Interactive coaching mode — adaptive dialogue for current phase |
| `/sprd-spec` | Author a ready Build-loop spec (`specs/NNNN-name.md`) and enforce the Definition of Ready |
| `/sprd-spike` | Open a bounded spike for a question nobody can answer yet |
| `/sprd-handoff` | Hand a ready spec to a developer in one step — branch, frontmatter, draft PR, reviewer request |
| `/sprd-spec-status` | Where a spec is and who it is waiting on, read from its pull request |
| `/sprd-report-issue` | Bugs in the product, from report to fix — forced minimum (what / expected / steps / channel / environment / severity / frequency / data impact / type of user / role / a real screenshot / a privacy statement), review by someone else, P1–P3 with a target sprint, promotion to a `type: bugfix` spec slated into the sprint, `sync` on merge, filing to GitHub or Azure DevOps |
| `/sprd-phase-report` | Generate phase HTML report with artifact inventory |
| `/sprd-review` | Multi-perspective artifact review (council, adversarial, or edge-case modes) |
| `/sprd-doctor` | Day-1 environment check — proves the installed harness can actually run here |
| `/sprd-harness` | Install or refresh the delivery harness in an existing repository |
| `/sprd-upgrade` | Bring an installed harness forward to the plugin's current version without clobbering the repo's adaptations |


## Profiles


### starter
Minimal profile for quick start:
- **Stack:** Configurable (defaults to TypeScript/Node)
- **Quality:** 60% coverage minimum, no TDD requirement
- **Compliance:** None
- **Conventions:** Conventional commits


### Creating Custom Profiles
Copy `profiles/starter/profile.yaml` and modify for your stack. Validate with:
```bash
uv run scripts/validate_profile.py profiles/my-profile/profile.yaml
```
See `profiles/_schema.yaml` for the full schema.

## Project Types

Phase 0 captures `project_type`, which is stored in `state.yaml` and controls how testing (in the Build loop), Deployment, and Monitoring execute:

| Type | Description | Testing (Build loop) | Deployment (8) | Monitoring (9) |
|------|-------------|----------------------|----------------|----------------|
| `service` | Backend API / server process | Unit + integration + E2E + API contract tests | Staging server deploy + DB migrations | Full infrastructure monitoring + alerting |
| `app` | User-facing application with UI | Same as service | Same as service | Same as service |
| `library` | Shared code package / SDK | Unit tests for public API surface | Package registry publish | Download counts + issue triage |
| `skill` | Claude Code skill / AI plugin | Scenario-based testing against requirement list | File distribution + install verification | Qualitative feedback channels + issue triage |
| `cli` | Command-line tool | Unit + integration + invocation tests | Binary distribution | Same as library |

## SDLC Phases

| # | Phase | Primary Skills | Key Artifacts |
|---|-------|---------------|---------------|
| 0 | Discovery | `/plan` | problem-statement.md, constitution.md (incl. project_type) |
| 1 | Requirements | `/deep-project` | requirements.md, non-functional-requirements.md (with Measurement Basis) |
| 2 | Design | `/deep-plan` | design-doc.md, ADRs |
| 3 | Foundation | `/deep-plan` | foundation-report.md, risk-tier-map.md, cadence-plan.md, build-handoff.md |
| build | Build Loop | `/tdd`, `/code-review`, `/security-review`, `/e2e` | `specs/NNNN-*.md`, phase7-handoff.md (no batch gate — human declares feature-complete) |
| 7 | Documentation | `/update-docs` | README, RUNBOOK |
| 8 | Deployment | CI/CD | release notes (approach varies by project_type) |
| 9 | Monitoring | Manual | monitoring config (approach varies by project_type) |
| close | Close & Transfer | — | final-handoff-report.md, harness-audit.md, close-gate-evidence.md, access-revocation-checklist.md |

## 7-Gate Validation System

Every phase transition runs through seven gates:

1. **Integrity** — Required artifacts exist and are well-formed
2. **Completeness** — Artifacts contain all required sections, no placeholders
3. **Metrics** — Quantitative thresholds met (coverage, file size)
4. **Compliance** — Correct labeling (priorities, ADR status, compliance mapping)
5. **Consistency** — Locked metrics checked against frozen layers from prior phases
6. **Quality** — Phase-scoped evaluation criteria from profile (e.g., requirement testability in Phase 1, ADR completeness in Phase 2, code patterns in the Build loop)
7. **Exit criteria** — The phase's own prose exit conditions from the registry, rendered as review items for the human who signs the advance

Gates 1–6 pass or fail. Gate 7 always reports REVIEW: its conditions are judgments ("The rails are proven, not just present") that no script can settle, so it shows the approver the checklist rather than deciding for them. Phases 0–2 declare no prose conditions, so Gate 7 is silent there.

All gate results are logged to `.sdlc/metrics/gate-log.jsonl` for empirical tracking of gate effectiveness.

Gates have severity levels:
- **MUST** — Blocks transition if failed
- **SHOULD** — Generates warning
- **MAY** — Informational

## Project Structure

```
shepherd/
├── plugin.json              # Plugin manifest
├── SKILL.md                 # Main skill entry point
├── commands/                # Slash commands (/sprd, /sprd-setup, /sprd-status, /sprd-next, /sprd-gate, /sprd-enhance, /sprd-coach, /sprd-review, /sprd-spec, /sprd-spike, /sprd-handoff, /sprd-spec-status, /sprd-report-issue, /sprd-doctor, /sprd-harness, /sprd-phase-report, /sprd-upgrade)
├── agents/                  # Agents (orchestrator, requirements-analyst, compliance-checker, section-evaluator, narrative-enhancer, gate-repair, multi-reviewer)
├── profiles/                # Company/stack YAML profiles
├── phases/                  # Phase definitions (0,1,2,3,build,7,8,9,close)
├── references/              # Progressive disclosure docs
├── templates/               # Artifact templates
├── scripts/                 # Python automation (uv)
└── hooks/                   # PowerShell hooks for context injection
```

Shepherd Free ships 16 slash commands, 7 agents and the `starter` profile.


## Architecture

This plugin follows **ADR-001: Shepherd is a Claude Code plugin that executes AI-SDLC methodology.**

- **AI-SDLC** = the methodology (phases, validation, templates)
- **Shepherd** = the execution engine (commands, hooks, profiles, scripts)
- The plugin references AI-SDLC patterns but adapts them for Claude Code's command/hook/agent system

## Contributing

1. Fork the repo
2. Create a feature branch: `feat/my-feature`
3. Follow the conventional commit format: `type: description`
4. Submit a PR with a clear description

## License

See [LICENSE](LICENSE) for the terms this edition is distributed under.

