# Code-host providers — chosen by the repository

The plugin talks to the repository's code host for a handful of things: find a spec's pull
request, read its checks and the grader's verdict, open a draft PR at hand-off, read branch
protection, read pipeline runs, list the secrets the gates sign in with. On GitHub every one of
those goes through the GitHub CLI (`gh`).


This is a **Tier-3 reference**: loaded on demand, read by nothing at runtime. Its executable code is
`scripts/code_host.py` (detection, CLI state, identity resolution, the documented contract).


---

## Two axes, never merged

| Axis | Question | Source of truth | Values |
|---|---|---|---|
| **Code host** | Which CLI talks to the *repository* (PRs, reviewers, identity, branch policies) | `git remote get-url origin` + the overrides below | `github` / `azure-devops` / `none` |
| **CI platform** | Where the *pipelines* live (runs, secrets, pipeline dirs) | `.claude/harness-manifest.json` → `packs ∋ cicd/azure-devops` | `github` / `azure-devops` |

`code_host.detect_host()` owns the first; `code_host.installed_ci_platform()` owns the second (a
ten-line twin of `doctor.installed_platform()`, pinned by a test to agree with it on doctor's six
manifest cases — `doctor.py` itself is not imported). GitHub + Azure Pipelines is a legitimate
combination; a reader that sees the two disagree gets an informational note, never a failure.

## Host detection — override precedence

| # | Source | `source` tag | Works with no `.sdlc/`? | Notes |
|---|---|---|---|---|
| 1 | `--host github\|azure-devops\|none` on every host-touching script | `flag` | yes | one invocation |
| 2 | env `SHEPHERD_CODE_HOST`, then `SDLC_CODE_HOST` (the pre-2.0 name, still read) | `env` | yes | process tree; the new name wins when both are set and `detail` names whichever supplied the value; an unrecognised value is ignored and named in `detail` |
| 3 | `.sdlc/code-host.yaml` → `host:` | `file` | no | travels with the clone; written by `set_setting.py code-host` |
| 4 | `git remote get-url origin` → `parse_remote` | `remote` | yes | **the default path** |
| 5 | harness manifest, CI axis | `manifest` | no | **tie-breaker only** when there is no usable remote; never overrides a parsed remote |
| 6 | nothing matched | `default` | — | `host: none` |

`host == none` falls through to `gh` (`cli_for("none") == "gh"`): zero behaviour change for every
repository that exists today, and the gh error becomes the familiar `code_host_available: false`.
Studio labels it "unrecognised remote — tried gh".

### `.sdlc/code-host.yaml`

```yaml
host: azure-devops            # github | azure-devops | none   (required)
organization: contoso         # optional — only for a remote parse_remote cannot read
project: Claims               # optional
repository: claims-api        # optional
```

Validated like the other `.sdlc/*.yaml` singletons; never written into `state.yaml`
(`advance_phase.py` is protected).


### Remote → host rule (`code_host.parse_remote`)

The shared fixture is `scripts/tests/fixtures/code_host/remote-urls.json`
(`[{url, host, org, project, repo, slug, org_url}]`), consumed by pytest **and** by Studio's
vitest port so the Python and TypeScript rules cannot drift. GHES, GitLab and ADO Server parse
as `none`; `.sdlc/code-host.yaml` is the escape hatch.

## The provider contract

No class hierarchy and no registry. The "interface" is a documented set of names, signatures
and return shapes — `code_host.PROVIDER_FUNCTIONS`.


### Error type

`code_host.CodeHostError` is an alias of `github_import.GitHubImportError` for new code to read
naturally.

### Normalised shapes (gh vocabulary, by design)

The gh JSON shapes **are** the normalised shapes, written down as TypedDicts in
`scripts/code_host_shapes.py` and re-exported by `code_host`: `Identity`, `PullRequest`, `Check`,
`Review`, `ReviewRequest`, `Run`, `Job`, `Ruleset`, `RepoView`.


## Identity — one roster key, one optional host key

| Item | Rule |
|---|---|
| Roster key | `people[].handle` stays `^@[A-Za-z0-9-]+$` on both hosts; spec frontmatter and `check_spec.py` unchanged |
| Host key (optional) | `people[].email` — the sign-in identity on Azure DevOps (UPN or mail); unique, case-insensitive (Wave 2, `validate_team.py`) |
| Resolution | `code_host.resolve_person(roster, identity)`: GitHub → `@` + `login` if that handle is in the roster, else `None`; ADO → the handle whose `email` equals `identity.login` case-insensitively, else `None` |
| Never | a provider guesses a handle from a display name or a UPN prefix |


## CLI state (`code_host.cli_state(host)`)

| State | Meaning | Detail names the fix |
|---|---|---|
| `available` | CLI found, extension present (az), signed in | — |
| `not_installed` | `shutil.which` found nothing | "the Azure CLI is not installed" / "the GitHub CLI is not installed" |
| `extension_missing` | az found, `az extension show --name azure-devops` failed | "run `az extension add --name azure-devops`" |
| `signed_out` | `az account show` / `gh auth status` failed | "run `az login`" / "run `gh auth login`" |
| `unknown` | the probe itself failed or was skipped | never read as "no" |

Every host-touching `--json` carries a top-level `host` block `{name, source, cli, cli_state,
detail}` so a reader can see *why* a host was chosen. "Unavailable" rides that block; it is never a
fourth check state and never a false `no`.

## Studio contract (`ConnectionInfo` additions, Waves 6–7)

`host: 'github'|'azure-devops'|'none'`, `hostSource`, `cli: { name: 'gh'|'az'|null, found,
extension: boolean|null, signedIn: 'yes'|'no'|'unknown', reason? }`, `accountSource:
'roster'|'host'|'typed'|null`, `rosterHandle: string|null`. `hostFeatureReason(connection,
feature)` returns one of: "Live pull-request status needs the Azure CLI", "The hand-off completes
locally; assigning on Azure DevOps needs az", "This project's repository is on Azure DevOps. The
Azure CLI (az) wasn't found; the GitHub CLI isn't needed for this project.", "…found, but the
azure-devops extension isn't: run `az extension add --name azure-devops`.", "Not signed in — run
`az login`.", "Signed in with a PAT only; Azure DevOps cannot say who you are.", "This folder's
origin is not GitHub or Azure DevOps; pull-request features are off (gh was tried, as before)."


## Protected — byte-for-byte unchanged

`scripts/scorecard.py`, `generate_status.py`, `check_gates.py`, `check_spec.py`,
`advance_phase.py`, `phase_model.py`, `new_spec.py`, `harness/**`, `phases/phase-registry.yaml`,
`agents/section-evaluator.md`, `commands/sprd-coach.md`, `commands/sprd-spec.md`,
`templates/state-init.yaml`; `doctor.py`; `github_import.py`.


No existing test file is edited — new coverage is new files or new additive classes.
`scripts/tests/test_gh_argv_golden.py` is the mechanical proof: it records the `gh` argv each
script issues on gh-shaped fixtures and compares against a golden captured from the pre-change
scripts.
