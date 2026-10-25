# Slash Commands Reference

Comprehensive documentation for all slash commands provided by the Shepherd plugin. These commands orchestrate the full Software Development Lifecycle within Claude Code, managing phase transitions, gate validation, reporting, and process auditing.

---

## Table of Contents

- [Command Overview Table](#command-overview-table)
- [/sprd-setup -- Interactive Setup Wizard](#sprd-setup----interactive-setup-wizard)
- [/sprd -- Phase Guidance](#sprd----phase-guidance)
- [/sprd-status -- Progress Dashboard](#sprd-status----progress-dashboard)
- [/sprd-gate -- Exit Criteria Check](#sprd-gate----exit-criteria-check)
- [/sprd-next -- Advance to Next Phase](#sprd-next----advance-to-next-phase)
- [/sprd-phase-report -- Generate Phase HTML Report](#sprd-phase-report----generate-phase-html-report)
- [/sprd-enhance -- Narrative Companions](#sprd-enhance----narrative-companions)
- [/sprd-coach -- Interactive Phase Coaching](#sprd-coach----interactive-phase-coaching)
- [/sprd-review -- Multi-Perspective Review](#sprd-review----multi-perspective-review)
- [/sprd-spec -- Author a Ready Spec](#sprd-spec----author-a-ready-spec)
- [Additional Commands (summaries)](#additional-commands-summaries)
- [Command Interaction Flow](#command-interaction-flow)
- [Python Script Invocation](#python-script-invocation)
- [Cross-References](#cross-references)

---

## Command Overview Table

| Command | Purpose | Modifies State | Typical Usage |
|---------|---------|:--------------:|---------------|
| `/sprd-setup` | Initialize SDLC for a project | Yes -- creates `.sdlc/` | Once per project, at the very start |
| `/sprd` | Show current phase guidance | No | Start of each work session |
| `/sprd-status` | Display progress dashboard | No | Anytime -- quick status check |
| `/sprd-gate` | Run 7-gate exit criteria check | Yes -- records `gate_results` | Before attempting to advance phases |
| `/sprd-next` | Run gates + advance phase | Yes -- advances `current_phase` | When ready to move to the next phase |
| `/sprd-phase-report` | Generate HTML report | No | Stakeholder reviews, documentation |
| `/sprd-enhance` | Generate stakeholder narrative companions | No | Before stakeholder reviews and phase transitions |
| `/sprd-coach` | Adaptive coaching dialogue for the current phase | No | When you want guided conversation instead of the step list |
| `/sprd-review` | Multi-perspective artifact review (council / adversarial / edge-cases) | No | Before `/sprd-gate` on design-heavy phases (2, 3, build) |
| `/sprd-spec` | Author a ready spec (scaffold → DoR → human risk tier) | Writes `specs/NNNN-name.md`; logs spec metrics | The Build-loop Intent beat, before building any change; also runs standalone via `--repo` |
| `/sprd-handoff` | Hand a ready spec to a developer in one step | Writes the branch + `status`/`developer` frontmatter commit; assigns on the code host (GitHub via `gh`, chosen by the `origin` remote) | The Build-loop Delegate beat, right after `/sprd-spec`; also runs standalone via `--repo` |
| `/sprd-spec-status` | Report a spec's status read from its pull request | Writes `status: merged` on the default branch, once, when the PR has actually merged (`--all` never writes) | The Build-loop Discern beat, to see where a change is and who it's waiting on; also runs standalone via `--repo` |
| `/sprd-spike` | Open a bounded spike for a question nobody can answer yet | Writes `spikes/NNNN-name.md` | When a story fails the Definition of Ready because the ground truth is unknown, not because the spec is badly written |
| `/sprd-doctor` | Day-1 environment check — proves the installed harness can actually run here; pack-aware, checks `gh` on GitHub installs and `az` on Azure DevOps installs, never the other (the PR-facing commands pick their CLI from the `origin` remote instead) | No | After `/sprd-setup`, when onboarding a second developer, and any time a gate behaves inexplicably |


---

## /sprd-setup -- Interactive Setup Wizard

### What It Does

Initializes the SDLC lifecycle management structure for a target project. This is the first command to run and is required before any other `/sprd-*` command will function. It creates the `.sdlc/` directory, selects and validates a profile, and configures the project's `CLAUDE.md` with SDLC context.

### Arguments

None. The command is fully interactive.

### Internal Flow

**Step 1: Check Existing Setup**
The command looks for `.sdlc/state.yaml` in the current directory. If it already exists, the user is warned that SDLC is already initialized and presented with two options: view status via `/sprd-status`, or re-initialize (destructive, requires explicit confirmation).

**Step 2: Profile Selection**
Available profiles are listed from the plugin's `profiles/` directory (excluding `_schema.yaml`). Current built-in profiles:

- **starter** -- Minimal profile with no compliance gates; a quick start suitable for any stack.


**Step 3: Project Configuration**
The user is prompted for:
- **Project name** (defaults to the current directory name).
- Confirmation that the selected profile settings are appropriate.

**Step 4: Initialize .sdlc/ Directory**
The init script is invoked:
```bash
uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/init_project.py \
  --profile ${CLAUDE_PLUGIN_ROOT}/profiles/<selected-profile>/profile.yaml \
  --target . \
  --name "<project-name>"
```

This creates the following structure:
```
.sdlc/
  state.yaml          # Phase tracking (Phase 0: Discovery active)
  profile.yaml        # Frozen copy of the selected profile
  constitution.md     # Project constitution
  artifacts/          # Per-phase artifact directories (one per phase slug: 00-discovery, 01-requirements, 02-design, 03-foundation, build, 07-documentation, 08-deployment, 09-monitoring, close)
```

**Step 5: Update CLAUDE.md**
The profile's `claude-md-template.md` contents are appended to the project's `CLAUDE.md`. If `CLAUDE.md` does not exist, it is created.

**Step 6: Confirmation Display**
A summary is shown:
```
SDLC initialized successfully!

Profile: <profile-id>
Phase: 0 -- Discovery (active)
Artifacts: .sdlc/artifacts/00-discovery/

Next steps:
1. Run /sprd to see Phase 0 guidance
2. Create your problem statement in .sdlc/artifacts/00-discovery/problem-statement.md
3. Run /sprd-gate when ready to check exit criteria
4. Run /sprd-next to advance to Phase 1
```

**Step 7: Post-Init Validation**
The profile validator runs against the frozen copy to confirm setup health:
```bash
uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/validate_profile.py .sdlc/profile.yaml
```

### State Changes

- Creates `.sdlc/state.yaml` with `current_phase: 0` and Phase 0 status set to `active`.
- Creates `.sdlc/profile.yaml` (frozen profile copy).
- Creates `.sdlc/constitution.md`.
- Creates `.sdlc/artifacts/` with one subdirectory per phase slug (`00-discovery`, `01-requirements`, `02-design`, `03-foundation`, `build`, `07-documentation`, `08-deployment`, `09-monitoring`, `close`).
- Appends SDLC context to the target project's `CLAUDE.md`.

### Python Scripts Called

| Script | Purpose |
|--------|---------|
| `init_project.py` | Creates the `.sdlc/` directory structure and initial `state.yaml` |
| `validate_profile.py` | Validates the frozen profile against `_schema.yaml` |

### Error Scenarios

| Scenario | Behavior |
|----------|----------|
| `uv` not installed | Instructs user to install via `pip install uv` or `brew install uv` |
| Profile validation fails | Displays specific validation errors and suggests fixes |
| Directory permissions error | Reports the OS-level error clearly |
| Already initialized | Warns user; offers view-status or destructive re-init with confirmation |

---

## /sprd -- Phase Guidance

### What It Does

Displays actionable guidance for the current (or specified) SDLC phase. This is the primary orientation command -- it tells you what to do, which skills to use, which artifacts to produce, and what the exit criteria are. It is read-only and never modifies state.

### Arguments

| Argument | Description |
|----------|-------------|
| *(none)* | Show guidance for the current phase |
| `<phase-number>` | Show guidance for a specific phase (e.g., `/sprd 3`) |

### Internal Flow

1. **Locate state:** Read `.sdlc/state.yaml`. If missing, instruct user to run `/sprd-setup`.
2. **Read state:** Extract `current_phase` (or use the argument-specified phase).
3. **Load phase definition:** Read the corresponding `phases/XX-phasename.md` file from the plugin.
4. **Load profile:** Read `.sdlc/profile.yaml` for stack and quality configuration.
5. **Display phase context** with the following sections:

### Output Sections

**Header** -- Phase number, name, and active profile ID.

**Purpose** -- One-line description of the phase's goal.

**Resolved Questions from Previous Phase** -- Checks the previous phase's handoff document for a "Resolved Questions" section. If present, lists them as confirmed inputs that MUST inform the current phase's artifacts. If absent, notes that and continues.

**What to Do Next** -- Actionable next steps based on the phase workflow, current artifact state, and resolved questions. References specific skills and commands. Example: *"Write `requirements.md` using resolved questions RQ-1 through RQ-3 as inputs."*

**Required Artifacts** -- A checklist with existence and size status:
```
[x] artifact.md (exists, 1.2KB)
[ ] other-artifact.md (missing)
```

**Skills to Use** -- Primary and secondary skills relevant to the phase.

**Exit Criteria** -- Summary of conditions required to advance, sourced from the phase definition.

**Quick Commands** -- Reminder block:
```
/sprd-gate    -- Check if exit criteria are met
/sprd-next    -- Advance to next phase (runs gate check)
/sprd-status  -- View full progress dashboard
```

**Compliance Callout** -- If the active profile includes compliance frameworks (e.g., SOC 2), any compliance-specific requirements for the phase are highlighted.

### State Changes

None. This command is purely informational.

### When to Use

- At the start of any work session to orient yourself.
- When you need to know what artifact to produce next.
- When reviewing requirements for a phase you haven't started yet (using the phase-number argument).

---

## /sprd-status -- Progress Dashboard

### What It Does

Generates and displays a progress dashboard showing overall SDLC status: current phase, completion percentages, artifact counts, and transition history. This is the quick-glance command for understanding where the project stands.

### Arguments

None.

### Internal Flow

1. **Locate state:** Read `.sdlc/state.yaml`. If missing, instruct user to run `/sprd-setup`.
2. **Read state:** Load current phase, all phase statuses, and transition history.
3. **Generate dashboard:** Execute:
   ```bash
   uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/generate_status.py \
     --state .sdlc/state.yaml
   ```
4. **Display dashboard** with:
   - Current phase name and number.
   - Progress bar (completed phases / total phases).
   - Phase table with status indicators, artifact counts, and timestamps.
   - Recent transition history (if any phase transitions have occurred).
5. **Suggest next action** based on current status:
   - Phase is `active`: suggest `/sprd` for guidance.
   - All gates would pass: suggest `/sprd-next` to advance.
   - Artifacts are missing: list what is needed.

### Output Format

A concise markdown table designed to fit on one screen. Generated by `generate_status.py`.

### State Changes

None. This command is purely informational.

### Python Scripts Called

| Script | Purpose |
|--------|---------|
| `generate_status.py` | Reads `state.yaml` and produces the formatted dashboard |


---

## /sprd-gate -- Exit Criteria Check

### What It Does

Runs the 7-gate validation system against the current (or specified) phase to determine readiness for advancement. Generates an HTML report and opens it in the default browser. Records gate results in state but does NOT advance the phase -- that is exclusively `/sprd-next`'s responsibility.

### The 7-Gate System

| Gate | Name | What It Validates |
|------|------|-------------------|
| G1 | Integrity | Artifact structure and format correctness |
| G2 | Completeness | All required artifacts exist with sufficient content |
| G3 | Metrics | Quantitative thresholds (coverage, size, counts) |
| G4 | Compliance | Regulatory and framework-specific requirements |
| G5 | Cross-Phase Consistency | Detects drift in locked metrics across phase transitions (budget, timeline, scope, stakeholder roster, quality thresholds, compliance reqs). Warns but does not block. |
| G6 | Quality | Content quality, consistency, and cross-references |
| G7 | Exit criteria | The phase's declared `exit_gate.conditions[]` prose checks, rendered for the human who signs. Always REVIEW — never blocks. |

Each gate reports one of three statuses:
- **PASS** -- Criteria fully satisfied.
- **FAIL** -- Criteria not met; includes details on what failed.
- **MANUAL** -- Requires human review and sign-off.

Each gate also has a severity level:
- **MUST** -- Blocking. Phase cannot advance if this gate fails.
- **SHOULD** -- Warning. Phase can advance but issues are flagged.
- **MAY** -- Advisory. Informational only.

### Arguments

| Argument | Description |
|----------|-------------|
| *(none)* | Check the current phase |
| `<phase-number>` | Check a specific phase (e.g., `/sprd-gate 2`) |

### Internal Flow

1. **Locate state:** Read `.sdlc/state.yaml`. If missing, instruct user to run `/sprd-setup`.
2. **Read state:** Determine the current phase (or use the argument-specified phase).
3. **Run gate checks:**
   ```bash
   uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/check_gates.py \
     --state .sdlc/state.yaml
   ```
   Optionally with `--phase <N>` for a specific phase.
4. **Display results:** For each of the 7 gates, show: gate name, PASS/FAIL/MANUAL status, severity (MUST/SHOULD/MAY), and specific details.
5. **Generate HTML report:**
   ```bash
   uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/generate_phase_report.py \
     --state .sdlc/state.yaml --phase <phase-number>
   ```
6. **Open report** in the default browser (`start` on Windows, `open` on macOS, `xdg-open` on Linux).
7. **Summarize** with counts of passed/failed/manual checks and an overall verdict:
   - **BLOCKED** -- Any MUST gate failed. Lists specific blockers with remediation suggestions.
   - **REVIEW NEEDED** -- Only manual checks remain. Reminds user to share the HTML report for stakeholder sign-off.
   - **READY** -- All gates pass. Suggests running `/sprd-next` to advance.
8. **Update state:** Record gate results in `.sdlc/state.yaml` under the current phase's `gate_results` field.

### State Changes

- Writes `gate_results` to the current phase entry in `state.yaml`.
- Generates `.sdlc/reports/<slug>-report.html` (registry slug, e.g. `00-discovery-report.html`, `build-report.html`).
- Does NOT modify `current_phase`.

### Python Scripts Called

| Script | Purpose |
|--------|---------|
| `check_gates.py` | Runs all 7 gates and returns structured results |
| `generate_phase_report.py` | Renders artifacts and gate results into a self-contained HTML report |

### Important Distinction

This command is **read-only with respect to phase transitions**. It records gate results but never changes `current_phase`. To actually advance, use `/sprd-next`.

---

## /sprd-next -- Advance to Next Phase

### What It Does

The most consequential command in the SDLC plugin. It runs gate checks, enforces a blocking Human-in-the-Loop (HITL) gate for open questions, advances the phase if all MUST gates pass and the user confirms, and then displays guidance for the new phase.

### Arguments

None. Always operates on the current phase.

### Internal Flow

**Step 1-2: Locate and Read State**
Standard state file lookup from `.sdlc/state.yaml`.

**Step 3: Run Gate Checks**
```bash
uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/check_gates.py \
  --state .sdlc/state.yaml
```

**Step 4: Evaluate Gate Results**

*If ANY MUST gate fails:*
- Display the failure report with specific blockers and remediation suggestions.
- Generate and open the HTML phase report (to show what is missing).
- Do NOT advance the phase.

*If all MUST gates pass (SHOULD/MAY may still have warnings):*
- Display success message and any remaining warnings.
- Generate and open the HTML phase report.
- Proceed to the HITL gate (Step 5).

**Step 5: HITL Gate -- Explicit Sign-Off**
Present a phase summary (what was produced, key decisions made) and ask: *"Does this look correct? Shall I advance to Phase N?"* The `advance_phase.py` script is NOT called until the human explicitly confirms.

**Step 6: Advance Phase**
Update `.sdlc/state.yaml`:
- Set current phase status to `completed` with `completed_at` timestamp.
- Set next phase status to `active` with `entered_at` timestamp.
- Set `current_phase` to the next phase by registry order (ids may be strings: `build`, `close` -- not id+1); update `phase_name`.
- Append transition to the `history` array:
  ```yaml
  - from: <current_phase_id>
    to: <next_phase_id>
    at: "<ISO 8601 timestamp>"
    gate_results: { <summary of pass/fail> }
  ```

**Step 7: BLOCKING HITL Gate -- Resolve Open Questions**

This gate is **MANDATORY** and **BLOCKING**. It MUST be completed before any new-phase work begins. There are no exceptions.

Procedure:
1. Read the handoff document produced by the phase just completed (e.g., `phase2-handoff.md`).
2. Extract ALL Q-NN or AQ-NN items listed under "Open Questions", "What X Must Address", or similar headings.
3. Display them in a prominent block:

   ```
   ---------------------------------------------------------------
   BLOCKING: OPEN QUESTIONS MUST BE RESOLVED BEFORE PHASE N BEGINS

   The following questions were raised during the previous phase.
   You MUST answer or confirm defaults for every item below.
   No artifacts will be written until all are resolved.

   | ID    | Question       | Needed by        | Proposed default    |
   |-------|----------------|------------------|---------------------|
   | AQ-01 | [question]     | [who/what]       | [proposed default]  |
   | AQ-02 | [question]     | [who/what]       | [proposed default]  |

   For each question: confirm the default, adjust it, or provide
   your own answer.
   ---------------------------------------------------------------
   ```

4. A reasonable default is proposed for every question based on project context (state, previous handoffs, artifacts, profile). Questions are never left without a proposed default.
5. **Execution halts.** No artifacts are written, no summaries of next steps are provided. The command waits for the user to respond.
6. Once the user confirms or provides answers, resolutions are recorded in the handoff document under a "Resolved Questions" section with timestamps.
7. Only after every open question is resolved does the command proceed.

If there are no open questions in the handoff document, the command explicitly states: *"No open questions found in the handoff. Proceeding to phase guidance."*

**Step 8: Show Next Phase Guidance**
After advancement and HITL resolution, display:
- New phase name and description.
- Primary skills to use.
- Required artifacts to produce.
- Entry criteria (already met by advancing).
- Reference to the phase definition file for full details.

**Step 9: Edge Case -- Final Phase Completion**
When the terminal phase (Phase C: Close & Transfer) passes its close gate, the project is complete. The user is congratulated and informed about post-SDLC re-entry points for future work.

### State Changes

- Updates `gate_results` for the current phase.
- Sets current phase status to `completed` with timestamp.
- Sets next phase status to `active` with timestamp.
- Advances `current_phase` to the next phase by registry order and updates `phase_name`.
- Appends to the `history` array.
- Updates handoff documents with resolved questions.
- Generates `.sdlc/reports/<slug>-report.html` (registry slug, e.g. `00-discovery-report.html`, `build-report.html`).

### Python Scripts Called

| Script | Purpose |
|--------|---------|
| `check_gates.py` | Runs the 7-gate validation system |
| `advance_phase.py` | Updates `state.yaml` with phase transition (called with `--confirmed`) |
| `generate_phase_report.py` | Generates the HTML report before advancement |

### Critical Notes

- Gate checks are mandatory. There is no `--force` flag. For exceptional cases, use the override protocol documented in `references/validation-rules.md`.
- The HITL gate in Step 7 is **non-negotiable**. Open questions MUST be surfaced with proposed defaults and resolved with user confirmation before any new-phase artifact work begins. Skipping this gate undermines the entire HITL workflow.

---

## /sprd-phase-report -- Generate Phase HTML Report

### What It Does

Renders all artifacts for a specified phase (or all phases) into a self-contained HTML report suitable for stakeholder review. Reports include dark-theme styling, Mermaid.js diagram rendering, and gate status indicators. No web server is required -- reports open directly in a browser.

### Arguments

| Argument | Description |
|----------|-------------|
| *(none)* | Generate report for the current phase |
| `<phase-id>` | Generate report for a specific phase (any phase id: 0,1,2,3,build,7,8,9,close) |
| `--all` | Generate individual reports for all phases (any phase id: 0,1,2,3,build,7,8,9,close) plus an `index.html` |

### Internal Flow

1. **Locate state:** Read `.sdlc/state.yaml`. If missing, instruct user to run `/sprd-setup`.
2. **Determine target phase:** Use `current_phase` from state if no argument provided; validate the phase id against the registry.
3. **Run report generator:**

   For a single phase:
   ```bash
   uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/generate_phase_report.py \
     --state .sdlc/state.yaml \
     --phase <phase-id>
   ```

   Output defaults to `.sdlc/reports/<slug>-report.html` (registry slug, e.g. `00-discovery-report.html`).

   For all phases:
   ```bash
   uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/generate_phase_report.py \
     --state .sdlc/state.yaml \
     --all
   ```

4. **Open in browser** automatically (`start` on Windows, `open` on macOS, `xdg-open` on Linux).
5. **Show artifact inventory:** After generating, list:
   - Which required artifacts were found and rendered.
   - Which required artifacts were missing (shown as placeholder sections in the report).
   - Exit gate status (pass/fail/incomplete).

### Output Location

Reports are written to `.sdlc/reports/` in the target project:
- `<slug>-report.html` -- Individual phase report (registry slug, e.g. `00-discovery-report.html`, `build-report.html`).
- `index.html` -- Full project report (generated with `--all`).

### Report Characteristics

- **Self-contained:** All CSS and JavaScript are inlined. A single HTML file with no external dependencies.
- **Dark theme:** Styled for comfortable reading.
- **Mermaid.js diagrams:** Any Mermaid diagram blocks in artifacts are rendered as interactive SVGs.
- **Missing artifacts:** Displayed as labeled placeholder sections, not errors.
- **Gate status:** Included to show phase readiness at the time of report generation.

### State Changes

None. This command generates files but does not modify `state.yaml`.

### Python Scripts Called

| Script | Purpose |
|--------|---------|
| `generate_phase_report.py` | Converts artifacts and gate data into self-contained HTML |

---


## /sprd-enhance -- Narrative Companions

### What It Does

Generates stakeholder-friendly `.narrative.md` companions for the current phase's technical artifacts. Spawns `narrative-enhancer` agents in parallel (one per artifact); each writes `{artifact-name}.narrative.md` alongside its source following `references/narrative-patterns.md` (executive summary, detailed prose, key decisions in business terms, impact assessment).

### Arguments

- No arguments: enhance all artifacts in the current phase
- `[path]`: enhance a specific artifact
- `--force`: regenerate even if narratives exist
- `--all-phases`: enhance across all completed phases

### State Changes

None. Narratives are optional — `/sprd-gate` does not require them. The technical artifact remains the source of truth.

### When to Use

Before stakeholder reviews, steering meetings, and phase transitions.

---

## /sprd-coach -- Interactive Phase Coaching

### What It Does

Starts or continues an adaptive coaching dialogue for the current phase instead of the rigid step list. Assesses artifact state (none / partial / complete), then opens in the matching mode: diagnostic questions to begin, gap-targeted questions mid-phase, or a ready-check that points to `/sprd-gate`. After each significant exchange it updates the relevant artifact so progress survives the session — the conversation is ephemeral, the artifacts are the record.

### Arguments

None. Mode is derived from artifact state. Coaching patterns come from `references/conversational-coaching.md`.

### State Changes

None directly; artifacts in `.sdlc/artifacts/{NN}-{phase-name}/` are created or updated through the dialogue. Coaching never bypasses gates — it helps users get through them.

### When to Use

When the user prefers guided conversation, is new to the methodology, or is stuck mid-phase. For the step list, use `/sprd`.

---

## /sprd-review -- Multi-Perspective Review

### What It Does

Spawns the `multi-reviewer` agent against the current phase's artifacts in one of three modes: `--council` (default; Architecture / Product / Quality / Security viewpoints plus a consistency-and-ambiguity audit), `--adversarial` (challenge every assumption and estimate), or `--edge-cases` (walk every branch and boundary). Writes `review-report.md` into the phase's artifact directory with CRITICAL/HIGH/MEDIUM/LOW findings, each citing a specific artifact and carrying an actionable recommendation.

### Arguments

- No arguments: `--council` on the current phase
- `--adversarial` | `--edge-cases` | `--council` | `--all` (all three, combined report)
- `<phase-number>`: review a specific phase

### State Changes

None. Findings are advisory and do not block gates, but CRITICAL/HIGH findings usually predict gate failures — address them before `/sprd-gate`.

### When to Use

Phase 2 with `--council`, Phase 3 (Foundation) with `--edge-cases`, the Build Loop with `--adversarial`; any phase before its gate.

---


## /sprd-spec -- Author a Ready Spec

### What It Does

The Build-loop **Intent beat** wrapped as one command: turn a story into a *ready spec* (`specs/NNNN-name.md`) that clears the Definition of Ready before anyone builds it — scaffold → author → enforce the DoR → confirm the risk tier with a human. No spec, no build. The spec is the durable per-change record: one spec = one branch = one PR, living in the repo's `specs/` directory (in version control, not only under `.sdlc/`) because the agent re-reads it every session and the grader grades against it.

The command owns two scripts the user never calls by hand: `new_spec.py` (scaffold + id allocation) and `check_spec.py` (DoR enforcement). It drives Intent so nothing stays implicit — Goal, Why, Scope in/out, testable acceptance checks (each past the vague-line test), silent product decisions surfaced to a Decision List with named owners, and the one existing pattern the change reuses (`harness_context`).

### Arguments

- No arguments: workflow mode — author a spec in the current `.sdlc/` engagement (reads the spec backlog and `risk-tier-map.md` for context).
- `--repo <path>`: standalone mode — author a spec in any repo with no `.sdlc/` present (the missing engagement context is noted in the spec's `source` field).
- `--spec <path>`: validate (and finish authoring) an **existing** spec instead of scaffolding a new one.

### Internal Flow

1. **Resolve mode and repo root** (workflow `.sdlc/` parent, or standalone `--repo`).
2. **Gather Intent** — drive every DoR element; apply the vague-line test (*"could two people build different things from this?"*) to each acceptance check.
3. **Propose a risk tier, never assign it** — recommend HIGH/MEDIUM/LOW with one sentence of justification, then a HITL `AskUserQuestion` gate where the Pod Lead confirms or overrides. Risk challenges escalate up, never down.
4. **Scaffold** via `new_spec.py` (auto-allocated 4-digit id), then write the gathered Intent into the section bodies.
5. **Enforce the DoR** via `check_spec.py` — fix every BLOCK (MUST); judge each ADVISE (SHOULD) vague-line flag. Re-run until it reads `READY`.

### State Changes

Writes `specs/NNNN-name.md` to the repo. In workflow mode (`--state`), each `check_spec.py` run logs to `.sdlc/metrics/spec-log.jsonl`. Does not modify `state.yaml` or advance phases.

### When to Use

The Build loop's Intent beat — before building any change. A spec that `check_spec.py` reports as NOT READY must not enter the Delegate beat (that is the "skipping Intent" failure the loop exists to kill). When behavior changes later, the spec changes in the **same PR** as the code.

---


## Additional Commands (summaries)

Six commands have their full flow documented in their command files rather than here.
One line each; see `commands/<name>.md` for the complete instructions.

| Command | What it does |
|---|---|
| `/sprd-handoff` | Hand a ready spec to a developer in one step — branch, `status`/`developer` frontmatter commit, code-host assignment (+ review request to the checker), optionally starting Claude Code on the branch in plan mode. Refuses (repository untouched) unless the spec is ready, the developer is in the roster and isn't the spec's own checker, and the team is under its WIP limit |
| `/sprd-spec-status` | Report a spec's status read from its pull request — checks, whether the grader ran and its verdict, whether a required security review passed, approvals, merge, and who the change is waiting on in one line. Reads the pull request through `gh` (`--host` overrides the detected host for one run). No PR yet or no code-host access are reported plainly, not as errors; a value the host does not record reads `null`, never a false no. Once the PR merges, sets `status: merged` on the default branch, once |
| `/sprd-spike` | Open a bounded spike (`spikes/NNNN-name.md`) for a question the pod cannot yet answer. The deliverable is the written finding, not the code — the code is thrown away, the finding outlives the branch. Backed by `scripts/new_spike.py` |
| `/sprd-doctor` | Verify the installed harness will actually run in this repo — interpreters present, rails scripts executable, required secrets set, branch protection active — and print the fix for anything that will not. **Pack-aware:** reads the installed CI/CD pack from the harness manifest and checks GitHub installs with `gh` (repo secrets, ruleset), Azure DevOps installs with `az` (variable groups read from the installed pipelines, branch policies) — never asks a repo to install the other platform's CLI. The harness fails quietly; this is what makes it fail loudly |
| `/sprd-harness` | Install or refresh the delivery harness independent of a full `/sprd-setup` |
| `/sprd-upgrade` | Bring an installed harness forward safely using the install manifest — updates factory-original files, preserves adaptations, surfaces both-sides changes as `.harness-new` siblings to merge |

---

## Command Interaction Flow

The typical SDLC lifecycle follows this pattern:

```
/sprd-setup
    |
    v
/sprd          <-- Orient: what phase am I in, what do I do?
    |
    v
  [work]       <-- Produce artifacts, use skills, write code
    |
    v
/sprd-gate     <-- Check: am I ready to advance?
    |
    +-- FAIL --> fix issues --> /sprd-gate (repeat)
    |
    +-- PASS
         |
         v
/sprd-next     <-- Advance: run gates, HITL sign-off, resolve questions
    |
    v
/sprd          <-- Orient to the new phase
    |
    v
  [repeat through Phase 9, then Phase C: Close & Transfer]
```

Supporting commands used at any time:
- `/sprd-status` -- Quick progress check (no prerequisites beyond setup).
- `/sprd-phase-report` -- Generate shareable HTML report for any phase.

### Session Start Pattern

A typical work session begins with:
1. `/sprd-status` -- See where the project stands.
2. `/sprd` -- Get actionable guidance for the current phase.
3. Work on artifacts.
4. `/sprd-gate` -- Verify progress before ending the session or advancing.

---

## Python Script Invocation

### The uv Runtime

All commands invoke Python scripts through `uv`, a fast Python package manager and runner. The invocation pattern is:

```bash
uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts <script-path> [arguments]
```

`${CLAUDE_PLUGIN_ROOT}` is the environment variable Claude Code sets to the plugin's install directory. The `--project ${CLAUDE_PLUGIN_ROOT}/scripts` flag tells `uv` to use the `pyproject.toml` in the plugin's `scripts/` directory for dependency resolution. This ensures scripts have access to their required packages (PyYAML, Jinja2, etc.) without polluting the target project's environment.

### How Scripts Find state.yaml

Scripts receive the path to `state.yaml` via the `--state` argument. This is always relative to or within the target project's `.sdlc/` directory. The calling command is responsible for resolving the correct path before invocation.

### How Scripts Output Results

Scripts write structured output to stdout, which the calling command parses and displays. HTML reports are written directly to `.sdlc/reports/`. Exit codes indicate success (0) or failure (non-zero), with error details on stderr.

### Script Inventory

| Script | Called By | Purpose |
|--------|-----------|---------|
| `init_project.py` | `/sprd-setup` | Creates `.sdlc/` directory structure |
| `validate_profile.py` | `/sprd-setup` | Validates profile YAML against schema |
| `generate_status.py` | `/sprd-status` | Generates progress dashboard |
| `check_gates.py` | `/sprd-gate`, `/sprd-next` | Runs the 7-gate validation system |
| `generate_phase_report.py` | `/sprd-gate`, `/sprd-next`, `/sprd-phase-report` | Renders HTML reports |
| `advance_phase.py` | `/sprd-next` | Updates `state.yaml` with phase transition |
| `track_decisions.py` | `/sprd-status` | Open / overdue `DL-NN` decisions on their 2-business-day clock |


---

## Cross-References

- **Gate system details:** See [gate-system.md](gate-system.md) for the full 7-gate specification, severity levels, and override protocol.
- **State machine:** See [state-machine.md](state-machine.md) for the `state.yaml` schema and valid phase transitions.
- **Phase lifecycle:** See [phase-lifecycle.md](phase-lifecycle.md) for phase definitions, artifact requirements, and entry/exit criteria.
- **Script internals:** See [scripts.md](scripts.md) for Python script implementation details, dependencies, and extension points.
- **Validation rules:** See [references/validation-rules.md](../references/validation-rules.md) for gate override protocol and validation rule definitions.
