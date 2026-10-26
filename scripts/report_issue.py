"""Bugs in the PRODUCT the team is building, from report to fix — the I/O CLI behind
`/sprd-report-issue`.

The rules live in `issue_model.py` (the questions, the minimum, the refusals, the lifecycle);
this file is the part that touches the repository. A report is written ONLY when it clears the
minimum: every gap is listed and nothing is written (exit 1). An AI-looking name or a
secret-shaped string is refused outright (exit 2) — the file is shared with a code host and
cannot be un-published.

The lifecycle (issue_model.TRANSITIONS; a report is a record, not a ticket):

  new ──triage confirmed──▶ triaged ──prioritize──▶ prioritized ──promote──▶ promoted ──sync──▶ fixed
   │        │ needs-info ──▶ needs-info ──▶ (triage again)                 (a `type: bugfix` spec; `--slate`
   │        │ duplicate / wont-fix ──▶ closed                                puts it into the target sprint)
   └── file (orthogonal: the report on GitHub / Azure DevOps, any time)      reopen ──▶ new

Verbs
  questions    The question plan, optionally for one channel of the product (`--json` for the app)
  env          The build under test: repository, branch, commit, code host, this machine (`--json`)
  new          Validate, copy the screenshots in, write `.sdlc/issues/ISS-NNNN-<slug>.md`, append the ledger;
               `--feature FE-NN` names the feature it belongs to, `--to-boards` then runs the Azure Boards
               mirror's own `plan` for this one report (never `apply`: a named person confirms that)
  features     Every feature brief with the specs whose `source:` names it, their channels and whether the
               mirror's ledger links it; `--spec NNNN` adds the chain's default (read-only)
  set-feature  Name (or clear, with "") the feature a report belongs to, by a named person, at any status
  show         One report in full, with the actions the lifecycle allows from its status — and why
               not, for the ones it refuses (`--json` for the app's buttons); `feature` and `board` (the
               work item the mirror's ledger pairs it with — read, never written here, never a board state)
  check        Re-validate an existing report against the minimum (exit 1 when it falls short)
  list         The queue — what needs a decision first (`--json` carries counts, never per-person totals)
  triage       Review: confirmed | needs-info (--question) | duplicate (--of) | wont-fix (--reason), by
               someone OTHER than the reporter (`--override --reason` for a team of one)
  prioritize   P1 | P2 | P3 and a target sprint, confirming or changing the report's proposal
  promote      Scaffold a `type: bugfix` spec through `new_spec.py` with the confirmed risk tier;
               `--slate` also slates it into the target sprint through `sprint.py slate`
  note         A dated note by a named person (the reporter's answer to needs-info, a finding)
  reopen       A closed report back to `new`, with a reason
  sync         Promoted reports whose bugfix spec is `status: merged` become `fixed`
  file         The report on the code host. GitHub: `gh issue create` (`--dry-run` prints the exact argv instead).
               Azure DevOps: a hand-over to the Azure Boards mirror — its own `plan --kind issue` for this report
               runs as a sibling and the plan's hash comes back (never `az` here, never `apply`: a named person
               confirms that); `--dry-run` names the plan command and runs nothing
  set-status   fixed | wont-fix | duplicate by a named human, under the lifecycle's rules

Standalone or Workflow (CLAUDE.md design rule):
  - Workflow:   --state .sdlc/state.yaml   (repo root = the directory containing .sdlc/)
  - Standalone: --repo <path>              (any folder; `.sdlc/issues/` is created under it)

Exit codes: reads 0; writes 0 done · 1 not done (a gap, the lifecycle, a CLI that said no) ·
2 refused (AI name, secret). `check` 1 when the report falls short.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import edition  # noqa: E402
import issue_model as im  # noqa: E402

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = PLUGIN_ROOT / "templates" / "issues" / "issue-report.md"
ISSUES_DIR = Path(".sdlc") / "issues"
LEDGER = Path(".sdlc") / "metrics" / "issue-log.jsonl"
# The Azure Boards mirror ships in Shepherd Pro. Without it a report still files on GitHub; the board
# parts say they need Pro (`edition.pro_module`), and the mirror script is run, never imported.
BOARDS_FEATURE = "Azure Boards"
FEATURES_FEATURE = "Choosing a report's feature from the feature briefs"
MIRROR_SCRIPT = PLUGIN_ROOT / "scripts" / "ado_sync.py"
# Sprints ship in Shepherd Pro too. Without `sprint.py` a target sprint is recorded as typed and a
# promotion is never slated; both say why instead of passing on the failed script's own error.
SPRINT_SCRIPT = PLUGIN_ROOT / "scripts" / "sprint.py"
SPRINTS_NEED_PRO = "Sprints need Shepherd Pro"


def _mirror_files() -> tuple[Path, Path] | None:
    """The mirror's own config and ledger (`ado_sync.py` writes both; the issue verbs only read them), as
    `boards_contract` names them; None without Shepherd Pro."""
    try:
        bc = edition.pro_module("boards_contract", BOARDS_FEATURE)
    except edition.ProRequired:
        return None
    return Path(bc.CONFIG_FILE), Path(bc.LEDGER)
SPEC_FILE_RE = re.compile(r"^(\d{4})-")
PROBE_TIMEOUT_S = 10
SIBLING_TIMEOUT_S = 90
SPRINT_ID_RE = re.compile(r"^S\d{2,}$")
# One frontmatter field, one bare word: `status` (a reader greps `^status: triaged`).
BARE_FIELDS = {"status"}


class Refused(Exception):
    """Exit 2: nothing is written, and the reason is not a gap the person can fill in."""


class NotDone(Exception):
    """Exit 1: a gap, the lifecycle, a CLI that said no. Nothing is written."""

    def __init__(self, message: str, gaps: list[str] | None = None):
        super().__init__(message)
        self.gaps = gaps or []


# --- repo and files ------------------------------------------------------------------------------

def resolve_repo_root(args) -> Path:
    if getattr(args, "state", None):
        state_path = Path(args.state)
        if not state_path.is_file():
            raise NotDone(f"state file not found: {state_path}")
        return state_path.resolve().parent.parent
    return Path(getattr(args, "repo", None) or ".").resolve()


def source_args(args) -> list[str]:
    """The `--state`/`--repo` pair to hand a sibling script."""
    if getattr(args, "state", None):
        return ["--state", str(Path(args.state).resolve())]
    return ["--repo", str(Path(getattr(args, "repo", None) or ".").resolve())]


def rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def now_ts() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def issue_files(root: Path) -> list[Path]:
    d = root / ISSUES_DIR
    if not d.is_dir():
        return []
    return sorted(p for p in d.iterdir() if p.is_file() and p.suffix == ".md" and im.ISSUE_FILE_RE.match(p.name))


def split_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    try:
        fm = yaml.safe_load(text[3:end]) or {}
    except yaml.YAMLError:
        fm = {}
    body = text[end + 4:]
    return (fm if isinstance(fm, dict) else {}), body.lstrip("\r\n")


def _is_report(root: Path, path: Path) -> bool:
    """A report is a `ISS-NNNN-*.md` file whose REAL location is the project's `.sdlc/issues/` — so a
    path to a spec, to state.yaml or to anything outside the folder is never written to as one."""
    try:
        real = path.resolve(strict=True)
        issues = (root / ISSUES_DIR).resolve(strict=True)
    except (OSError, RuntimeError):
        return False
    return real.parent == issues and real.suffix == ".md" and bool(im.ISSUE_FILE_RE.match(real.name))


def find_issue(root: Path, ref: str) -> Path:
    """`ISS-0007`, `0007`, a filename, or a path — resolved to the report file or NotDone. A path
    that is not a report under `.sdlc/issues/` is refused, whatever it points at."""
    ref = (ref or "").strip()
    if not ref:
        raise NotDone("--issue is required (an id such as ISS-0007, or the report's path)")
    p = Path(ref)
    for candidate in (p, root / p):
        if candidate.is_file():
            if not _is_report(root, candidate):
                raise NotDone(f"'{ref}' is not an issue report — reports live under {ISSUES_DIR.as_posix()}/ as ISS-NNNN-<slug>.md")
            return candidate.resolve()
    m = re.match(r"^(?:ISS-)?(\d{4})$", ref, re.IGNORECASE)
    if m:
        for f in issue_files(root):
            if f.name.startswith(f"ISS-{m.group(1)}-"):
                return f
        raise NotDone(f"no report ISS-{m.group(1)} under {ISSUES_DIR.as_posix()}/")
    raise NotDone(f"'{ref}' is neither a report id nor a file")


def sections(body: str) -> dict[str, str]:
    """`## Heading` -> its text, for the verbs that read what `new` wrote."""
    out: dict[str, str] = {}
    current: str | None = None
    lines: list[str] = []
    for line in body.splitlines():
        m = re.match(r"^## +(.+?)\s*$", line)
        if m:
            if current is not None:
                out[current] = "\n".join(lines).strip()
            current, lines = m.group(1), []
        elif current is not None:
            lines.append(line)
    if current is not None:
        out[current] = "\n".join(lines).strip()
    return out


def _q(value) -> str:
    """A one-line YAML double-quoted scalar: JSON strings are valid YAML, escapes included. DEL and the C1 controls are
    the one thing `json.dumps(ensure_ascii=False)` leaves raw that PyYAML rejects, so each is written as its own
    `\\u00XX` escape; every other character (an em dash, an emoji) stays as it is, so no existing report changes."""
    quoted = json.dumps("" if value is None else str(value), ensure_ascii=False)
    return im.UNCARRIABLE_RE.sub(lambda m: f"\\u{ord(m.group()):04x}", quoted)


def _ledger_issue_names(root: Path) -> list[str]:
    """`ISS-NNNN-` for every issue the ledger has seen, so a deleted report's id is never given
    out again (its screenshots folder and its events would be another report's)."""
    path = root / LEDGER
    if not path.is_file():
        return []
    names: list[str] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            issue = json.loads(line).get("issue")
        except (ValueError, AttributeError):
            continue
        if isinstance(issue, str) and im.ISSUE_ID_RE.match(issue):
            names.append(f"{issue}-")
    return names


def write_ledger(root: Path, event: dict) -> Path:
    path = root / LEDGER
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    return path


def set_field(text: str, field: str, value: str) -> str:
    """Replace one frontmatter line, every other byte untouched; a field the file lacks is added
    at the end of the block. `status` stays a bare word; everything else is quoted."""
    fm_end = text.find("\n---", 3)
    head, rest = text[:fm_end], text[fm_end:]
    rendered = value if field in BARE_FIELDS else _q(value)
    pattern = rf"^{re.escape(field)}:[^\r\n]*"
    if re.search(pattern, head, flags=re.MULTILINE):
        head = re.sub(pattern, lambda _m: f"{field}: {rendered}", head, count=1, flags=re.MULTILINE)
    else:
        head = head.rstrip("\r\n") + f"\n{field}: {rendered}"
    return head + rest


def _escape_headings(text: str) -> str:
    """Text whose lines cannot start a Markdown heading: a line that begins with `#` gets a backslash, and `\\r`
    (and every other line break `splitlines` knows) becomes `\\n`. A line of `## Where` inside a note would otherwise
    open a second section of that name, and `sections()` keeps the last one."""
    return "\n".join(("\\" + line) if line.lstrip().startswith("#") else line for line in text.splitlines())


def append_history(text: str, line: str) -> str:
    line = _escape_headings(line)
    marker = "<!-- {{history}} -->"
    if marker in text:
        return text.replace(marker, f"- {line}")
    return text.rstrip("\n") + f"\n- {line}\n"


def _refuse_secrets(*texts: str | None) -> None:
    """A token-shaped string in a reason, a question or a note is refused as it is in the report."""
    found = im.secrets_in("\n".join(t for t in texts if t))
    if found:
        raise Refused(f"the text contains what looks like {', '.join(found)} — remove it; this record is shared with the code host")


def _require_person(name: str | None, what: str) -> str:
    clean = (name or "").strip()
    if not clean:
        raise Refused(f"--by is required: the person {what}, by name")
    if im.is_ai_actor(clean):
        raise Refused(f"--by '{clean}' reads as an AI/automation, not a person")
    return clean


def _same_person(a: str | None, b: str | None) -> bool:
    norm = lambda s: re.sub(r"[^a-z0-9]", "", str(s or "").lower().lstrip("@"))  # noqa: E731
    return bool(norm(a)) and norm(a) == norm(b)


def _sibling(root: Path, script: str, args: list[str]) -> subprocess.CompletedProcess:
    """Run another plugin script the way a person would — never by importing its internals."""
    cmd = [sys.executable, str(PLUGIN_ROOT / "scripts" / script), *args]
    try:
        return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=SIBLING_TIMEOUT_S, check=False, cwd=str(root), env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise NotDone(f"{script} did not run: {exc}")


# --- the Azure Boards mirror, read and never written ---------------------------------------------

def issue_ref(issue_id: str) -> str:
    """`ISS-0001` -> `sdlc:issue:0001`: the mirror's ref for a report (the family prefix dropped, as for every kind)."""
    return f"sdlc:issue:{issue_id.split('-', 1)[1] if '-' in issue_id else issue_id}"


def _code_host(root: Path) -> str | None:
    """`github` / `azure-devops` / `none` from the repository (a git read, no CLI); None when it could not be read."""
    try:
        import code_host as ch
        return ch.detect_host(root, None).host
    except Exception:  # the host is what an action's reason says, never a reason for `show` to fail
        return None


def _mirror_lines(root: Path) -> list[dict] | None:
    """The mirror's ledger lines in append order; None when the file is absent or unreadable — a line that is not a
    JSON object makes the whole ledger unreadable, as it does for `ado_sync.py` (a line skipped in silence undercounts).
    None too without Shepherd Pro, which owns the ledger."""
    files = _mirror_files()
    if files is None:
        return None
    try:
        text = (root / files[1]).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    lines: list[dict] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            return None
        if not isinstance(entry, dict):
            return None
        lines.append(entry)
    return lines


def _mirror_links(root: Path) -> dict[str, dict]:
    """ref -> the mirror's last linking line for it (`ado_sync_model.linked_work_items`, the one reading); `{}` when
    the ledger is absent or unreadable."""
    lines = _mirror_lines(root)
    if not lines:
        return {}
    asm = edition.pro_module("ado_sync_model", BOARDS_FEATURE)  # a ledger is read only when Pro is present
    return asm.linked_work_items(lines)


def _ado_remote(root: Path):
    """The parsed Azure DevOps remote (a git read, never `az`), or None when there is no usable one."""
    try:
        return edition.pro_module("ado_transport", BOARDS_FEATURE).remote(root)
    except Exception:  # no remote, a GitHub origin, a refused name, no Pro: no link, never a guessed one
        return None


def _web_url(remote, work_item: int) -> str | None:
    if remote is None:
        return None
    try:
        return edition.pro_module("ado_wit_map", BOARDS_FEATURE).work_item_web_url(remote, work_item)
    except Exception:
        return None


def _board_links(root: Path) -> dict[str, dict]:
    """ref -> `{work_item, url, how, as_of}` for every ref the mirror's ledger pairs with a work item. `how` is the
    ledger event that paired it, `as_of` that line's time. No `state`: the ledger records a pairing, not what the
    board says now, and nobody read the board here. `{}` when the ledger is absent or unreadable. Read once per
    `list`; the remote is resolved once, and only when something is linked."""
    links = _mirror_links(root)
    if not links:
        return {}
    remote = _ado_remote(root)
    return {ref: {"work_item": line["work_item"], "url": _web_url(remote, line["work_item"]), "how": line.get("event"),
                  "as_of": line.get("ts")} for ref, line in links.items()}


def _feature_rows(root: Path) -> list[dict]:
    """The repository's feature briefs as the mirror reads them (`ado_sync_sources.load_features`: one per real
    header, an id named twice refused). Raises `edition.ProRequired` without Shepherd Pro."""
    src = edition.pro_module("ado_sync_sources", FEATURES_FEATURE)
    try:
        return src.load_features(root, {}, {})
    except (OSError, ValueError) as exc:
        raise NotDone(f"the feature briefs could not be read: {exc}")


def _spec_parents(root: Path) -> list[dict]:
    """`{id, ref, note, channel}` for every spec under `specs/`: the feature its `source:` names
    (`ado_sync_sources.spec_parent`, never a guess) and its `channel:` as written."""
    src = edition.pro_module("ado_sync_sources", FEATURES_FEATURE)
    from check_spec import parse_frontmatter
    from track_specs import scan_specs
    out: list[dict] = []
    for scanned in scan_specs(root / "specs"):
        path = Path(scanned["path"])
        if not path.resolve().is_relative_to(root.resolve()):
            continue
        ident = str(scanned["id"]).strip()
        if not ident.isdigit():
            m = SPEC_FILE_RE.match(path.name)
            if not m:
                continue
            ident = m.group(1)
        try:
            fm = parse_frontmatter(path.read_text(encoding="utf-8", errors="replace"))[0]
        except OSError:
            continue
        ref, note = src.spec_parent(root, {"kind": "spec", "source_path": rel(path, root), "source_row": fm})
        channel = str(fm.get("channel") or "").strip()
        out.append({"id": ident, "ref": ref, "note": note, "channel": "" if channel in ("—", "-") else channel})
    return out


def _feature_id(value) -> str:
    """A typed feature id upper-cased when it is one (`fe-03` -> `FE-03`); anything else stays as typed, so a gap
    quotes what the person wrote."""
    clean = str(value or "").strip()
    return clean.upper() if im.FEATURE_ID_RE.match(clean) else clean


# --- questions ----------------------------------------------------------------------------------

def verb_questions(args, _root: Path | None) -> int:
    channel = im.normalize_channel(args.channel) if args.channel else None
    if args.channel and channel is None:
        raise NotDone(f"'{args.channel}' is not a channel — one of {', '.join(im.CHANNELS)}")
    plan = im.question_plan(channel)
    if args.json:
        print(json.dumps({"channel": channel, "questions": plan,
                          "lifecycle": {"statuses": list(im.STATUSES), "triage_verdicts": list(im.TRIAGE_VERDICTS),
                                        "priorities": list(im.PRIORITIES), "priority_labels": im.PRIORITY_LABELS,
                                        "status_labels": im.STATUS_LABELS, "triage_verdict_labels": im.TRIAGE_VERDICT_LABELS},
                          "minimum": {"title_chars": [im.MIN_TITLE_CHARS, im.MAX_TITLE_CHARS],
                                      "what_happened_chars": im.MIN_WHAT_CHARS, "expected_chars": im.MIN_EXPECTED_CHARS,
                                      "screenshots": 1, "screenshot_bytes": im.MAX_SCREENSHOT_BYTES}}, indent=2, ensure_ascii=False))
        return 0
    print(f"Questions for a bug report{f' seen on the {channel} channel' if channel else ''}:")
    for q in plan:
        req = "required" if q["required"] else "optional"
        only = f" [{', '.join(q['channels'])} only]" if q.get("channels") and channel is None else ""
        print(f"  {q['id']:<20} {q['kind']:<9} {req:<8} {q['prompt']}{only}")
        if q.get("options"):
            print(f"  {'':<20} {'':<9} {'':<8} " + " | ".join(f"{o['value']} — {o['label']}" for o in q["options"]))
        if q.get("hint"):
            print(f"  {'':<20} {'':<9} {'':<8} ({q['hint']})")
    return 0


# --- env ----------------------------------------------------------------------------------------

def _git(root: Path, *args: str) -> str | None:
    if shutil.which("git") is None:
        return None
    try:
        proc = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=PROBE_TIMEOUT_S, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout.strip() or None if proc.returncode == 0 else None


def plugin_version() -> str | None:
    try:
        manifest = json.loads((PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        v = manifest.get("version")
        return str(v) if v else None
    except (OSError, ValueError):
        return None


def gather_env(root: Path, app_version: str | None = None) -> dict:
    """What a reporter rarely knows how to find about the build under test. Never a guess: a fact
    that is not there reads null. The product's repository is the subject; the tooling that wrote
    the report is recorded for the record only."""
    try:
        import code_host as ch
        detection = ch.detect_host(root)
        remote = detection.remote
        repo = {"host": detection.host, "slug": remote.slug if remote else None, "web_url": remote.web_url if remote else None,
                "branch": _git(root, "rev-parse", "--abbrev-ref", "HEAD"), "commit": _git(root, "rev-parse", "--short", "HEAD"),
                "describe": _git(root, "describe", "--tags", "--always")}
    except Exception as exc:  # pragma: no cover — the host is a nice-to-have, never a blocker
        repo = {"host": "unknown", "slug": None, "web_url": None, "branch": None, "commit": None, "describe": None, "detail": str(exc)}
    return {
        "repo": repo,
        "machine": {"os": platform.platform(), "python": platform.python_version()},
        "tooling": {"plugin_version": plugin_version(), "app_version": app_version or None},
        "captured_at": now_ts(),
    }


def verb_env(args, root: Path) -> int:
    env = gather_env(root, args.app_version)
    if args.json:
        print(json.dumps(env, indent=2, ensure_ascii=False))
        return 0
    r = env["repo"]
    print("The build under test, as far as this machine can tell:")
    print(f"  {'repository':<14} {r.get('slug') or 'no origin remote'} ({r.get('host')})")
    print(f"  {'branch':<14} {r.get('branch') or 'no repository'}")
    print(f"  {'commit':<14} {r.get('commit') or '—'}" + (f"  ({r.get('describe')})" if r.get("describe") and r.get("describe") != r.get("commit") else ""))
    print(f"  {'this machine':<14} {env['machine']['os']}")
    print(f"  {'written with':<14} plugin {env['tooling']['plugin_version'] or 'unknown'}" + (f", app {env['tooling']['app_version']}" if env["tooling"]["app_version"] else ""))
    return 0


# --- new ----------------------------------------------------------------------------------------

# The fields `new`'s own flags set. An `--answer` may add a channel follow-up or an extra fact, never
# re-set one of these — `--answer no_client_data=1` must not stand in for the person's confirmation.
RESERVED_ANSWER_KEYS = frozenset(im.CORE_FIELDS) | {"environment", "escaped_from", "no_client_data", "product_version"}


def _kv_pairs(values: list[str], flag: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in values or []:
        if "=" not in item:
            raise NotDone(f"{flag} expects KEY=VALUE, got '{item}'")
        k, v = item.split("=", 1)
        k = k.strip()
        if not re.match(r"^[a-z][a-z0-9_]*$", k):
            raise NotDone(f"{flag}: '{k}' is not a field name (lower-case letters, digits, underscores)")
        if k in RESERVED_ANSWER_KEYS:
            raise NotDone(f"{flag}: '{k}' is one of new's own fields — give it with its flag, not as an answer")
        out[k] = v
    return out


def build_report(args) -> tuple[dict, list[Path], dict]:
    """The report dict `issue_model.validate` reads, the screenshot paths, and the environment facts."""
    answers = _kv_pairs(args.answer, "--answer")
    facts: dict = {}
    if args.env_json:
        try:
            facts = json.loads(Path(args.env_json).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise NotDone(f"--env-json: {exc}")
        if not isinstance(facts, dict):
            raise NotDone("--env-json must hold one JSON object")
    product_version = (args.product_version or "").strip()
    if not product_version and (args.environment or "") == "local":
        repo = facts.get("repo") if isinstance(facts.get("repo"), dict) else {}
        if repo.get("branch") or repo.get("commit"):
            product_version = f"{repo.get('branch') or '?'} @ {repo.get('commit') or '?'}"
    report = {
        "channel": im.normalize_channel(args.channel) or (args.channel or ""), "title": args.title or "", "what_happened": args.what or "", "expected": args.expected or "",
        "steps": "\n".join(args.steps or []), "environment": args.environment or "", "product_version": product_version,
        "severity": args.severity or "", "frequency": args.frequency or "", "data_impact": args.data_impact or "",
        "persona": args.persona or "", "reporter_role": args.reporter_role or "", "spec": args.spec or "",
        "feature": _feature_id(args.feature),
        "no_client_data": bool(args.no_client_data), "escaped_from": args.escaped_from or "", **answers,
    }
    return report, [Path(p) for p in (args.screenshot or [])], facts


def _cell(value) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def _prose(text: str) -> str:
    """A reporter's words as a Markdown paragraph that cannot start a section: a leading `#` is
    escaped, so `## Steps` typed inside "what happened" stays their sentence and `check` still finds
    the sections `new` wrote."""
    return _escape_headings(str(text).strip())


def render_report(issue_id: str, report: dict, facts: dict, shots_rel: list[str], by: str, ts: str) -> str:
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    channel = report["channel"]
    fm_lines = [
        "---",
        f"issue: {_q(issue_id)}",
        f"title: {_q(report['title'].strip())}",
        "status: new",
        f"channel: {_q(channel)}",
        f"environment: {_q(report['environment'])}",
        f"product_version: {_q(report.get('product_version') or '')}",
        f"severity: {_q(report['severity'])}",
        f"frequency: {_q(report['frequency'])}",
        f"data_impact: {_q(report['data_impact'])}",
        f"persona: {_q(report['persona'].strip())}",
        f"reporter_role: {_q(report['reporter_role'])}",
        f"spec: {_q(report.get('spec') or '')}",
        f"feature: {_q(report.get('feature') or '')}",
        f"reported_by: {_q(by)}",
        f"reported_at: {_q(ts)}",
        f"screenshots: {len(shots_rel)}",
        'priority: ""',
        'target_sprint: ""',
        'triaged_by: ""',
        'triage_verdict: ""',
        'prioritized_by: ""',
        'duplicate_of: ""',
        'bugfix_spec: ""',
        'filed_host: ""',
        'filed_url: ""',
        'filed_id: ""',
        f"escaped_from: {_q(report.get('escaped_from') or '')}",
        "---",
    ]
    _, body = split_frontmatter(template)
    body = body.replace("# ISS-NNNN — <title>", f"# {issue_id} — {report['title'].strip()}")

    steps = [s.strip() for s in str(report.get("steps") or "").splitlines() if s.strip()]
    steps_md = "\n".join(f"{i}. {_prose(s)}" for i, s in enumerate(steps, 1))

    where_rows = [("Channel", im.CHANNEL_LABELS.get(channel, channel))]
    if im.CHANNEL_DESCRIPTOR.get(channel):
        where_rows.append(("Channel descriptor", f"channels/{im.CHANNEL_DESCRIPTOR[channel]}.yaml"))
    prompts = {q["id"]: q["prompt"].rstrip("?") for q in im.CHANNEL_QUESTIONS}
    known = set(im.CORE_FIELDS) | {"escaped_from"}
    for q in im.CHANNEL_QUESTIONS:
        if channel in (q["channels"] or []) and str(report.get(q["id"]) or "").strip():
            where_rows.append((prompts[q["id"]], str(report[q["id"]]).strip()))
    for k, v in report.items():
        if k not in known and k not in im.CHANNEL_FIELD_IDS and str(v or "").strip():
            where_rows.append((k, str(v).strip()))
    where_md = "| Question | Answer |\n|---|---|\n" + "\n".join(f"| {k} | {_cell(v)} |" for k, v in where_rows)

    repo = facts.get("repo") if isinstance(facts.get("repo"), dict) else {}
    machine = facts.get("machine") if isinstance(facts.get("machine"), dict) else {}
    tooling = facts.get("tooling") if isinstance(facts.get("tooling"), dict) else {}
    env_rows = [
        ("environment", im.ENVIRONMENT_LABELS.get(report["environment"], report["environment"])),
        ("product_version", report.get("product_version") or None),
        ("repository", repo.get("slug")),
        ("branch", repo.get("branch")),
        ("commit", repo.get("commit")),
        ("code_host", repo.get("host")),
        ("reporter_machine", machine.get("os")),
        ("written_with", f"plugin {tooling.get('plugin_version')}" + (f", app {tooling.get('app_version')}" if tooling.get("app_version") else "") if tooling.get("plugin_version") else None),
    ]
    env_md = "| Fact | Value |\n|---|---|\n" + "\n".join(
        f"| {k} | {_cell(v) if v not in (None, '') else 'not recorded'} |" for k, v in env_rows)

    shots_md = "\n".join(f"![screenshot {i}]({p})" for i, p in enumerate(shots_rel, 1))
    privacy = f"{by} confirmed on {ts[:10]}: nothing in the screenshots or this report is client data, personal data or a secret."
    history = f"- {ts} — reported by {by}"

    body = body.replace("<!-- {{what_happened}} -->", _prose(report["what_happened"]))
    body = body.replace("<!-- {{expected}} -->", _prose(report["expected"]))
    body = body.replace("<!-- {{steps}} -->", steps_md)
    body = body.replace("<!-- {{where}} -->", where_md)
    body = body.replace("<!-- {{environment}} -->", env_md)
    body = body.replace("<!-- {{screenshots}} -->", shots_md)
    body = body.replace("<!-- {{privacy}} -->", privacy)
    body = body.replace("<!-- {{history}} -->", history)
    return "\n".join(fm_lines) + "\n\n" + body


def record_escaped_bug(args, root: Path, issue_id: str, check: str) -> str | None:
    """The scorecard's `escaped_bug` event, through scorecard.py itself (never a hand-written line
    in its ledger). A failure is a warning on the report, never a reason not to write it."""
    try:
        proc = _sibling(root, "scorecard.py", ["record", *source_args(args), "--type", "escaped_bug",
                                               "--field", f"which_check={check}", "--field", f"issue={issue_id}"])
    except NotDone as exc:
        return str(exc)
    if proc.returncode != 0:
        return f"scorecard.py record escaped_bug exited {proc.returncode}: {(proc.stderr or proc.stdout).strip()}"
    return None


BOARDS_NOT_PLANNED = {"planned": False, "plan": None, "path": None, "row": None, "posture": None,
                      "apply_offered": False, "apply_command": None, "reason": None}


def boards_plan(args, root: Path, issue_id: str) -> dict:
    """The Azure Boards mirror's own `plan` for this one report, run as a sibling (`ado_sync.py plan --kind issue
    --id ISS-NNNN --no-comments --json`) — never imported, never applied: the plan's hash and its own `next` line
    are handed back for a named person to confirm. Every key is always present. `planned` only when the plan is a
    real read (`ok`, not `unavailable`) holding a row for this report; otherwise `reason` is the plan's own sentence,
    or the sibling's failure (its first stderr line, else its exit code)."""
    if not MIRROR_SCRIPT.is_file():
        return {**BOARDS_NOT_PLANNED, "reason": f"{BOARDS_FEATURE} needs Shepherd Pro"}
    try:
        proc = _sibling(root, "ado_sync.py", ["plan", *source_args(args), "--kind", "issue", "--id", issue_id,
                                              "--no-comments", "--json"])
    except NotDone as exc:
        return {**BOARDS_NOT_PLANNED, "reason": str(exc)}
    try:
        doc = json.loads(proc.stdout)
    except ValueError:
        doc = None
    if proc.returncode != 0 or not isinstance(doc, dict):
        first = next((line.strip() for line in (proc.stderr or "").splitlines() if line.strip()), "")
        return {**BOARDS_NOT_PLANNED, "reason": first or f"ado_sync.py exited {proc.returncode}"
                + ("" if proc.returncode else " without a JSON document")}
    ref = issue_ref(issue_id)
    row = next((r for r in doc.get("rows") or [] if isinstance(r, dict) and r.get("ref") == ref), None)
    if doc.get("ok") is True and doc.get("unavailable") is False and row is not None:
        return {"planned": True, "plan": doc.get("plan"), "path": doc.get("path"),
                "row": {k: row.get(k) for k in ("action", "type", "parent", "notes", "reason")}, "posture": doc.get("posture"),
                "apply_offered": doc.get("apply_offered") is True, "apply_command": doc.get("next"), "reason": None}
    reason = doc.get("reason")
    if not reason:
        skipped = next((s.get("reason") for s in doc.get("skipped") or [] if isinstance(s, dict) and s.get("kind") == "issue"), None)
        reason = skipped or (f"the mirror's plan matched nothing for {issue_id}" if issue_id in (doc.get("unmatched_ids") or [])
                             else f"the mirror's plan has nothing to send for {ref}")
    return {**BOARDS_NOT_PLANNED, "posture": doc.get("posture"), "reason": reason}


def record_boards_planned(root: Path, issue_id: str, boards: dict, by: str) -> None:
    """One `boards_planned` line in the issue's own ledger: who asked the mirror for which plan. The pairing itself is
    the mirror's (`.sdlc/metrics/ado-sync-log.jsonl`), read and never written here."""
    write_ledger(root, {"timestamp": now_ts(), "event": "boards_planned", "issue": issue_id, "plan": boards["plan"], "by": by})


def boards_lines(boards: dict) -> list[str]:
    """A planned `boards` block in words: the plan, its row, its notes, then the plan's own `next` line verbatim — or
    why there is none (a plan-only clone, a plan with nothing an apply sends). Never an apply run here."""
    row = boards["row"] or {}
    parent = row.get("parent") or {}
    lines = [f"Azure Boards: plan {boards['plan']} — {row.get('action')} {row.get('type') or '(no type)'}"
             + (f" under {parent.get('ref')}" + (f" (#{parent['work_item']})" if parent.get("work_item") else "") if parent else ", no parent")]
    lines += [f"  note: {note}" for note in row.get("notes") or []]
    reason = row_reason(boards)
    if boards["apply_command"]:
        lines.append(boards["apply_command"])
    elif boards["posture"] != "assisted":
        lines.append(f"No apply is offered: this clone's posture is {boards['posture'] or 'not recorded'}, so the plan stops here")
    elif not reason:
        lines.append("Nothing in this plan is sent by an apply; the row's notes say what a person does instead")
    if reason:
        lines.append(f"  {reason}")  # the plan row's own words, as --json carries them in boards.row.reason
    return lines


def row_reason(boards: dict) -> str | None:
    """The plan row's own `reason` when it is a non-empty string, else None: the one sentence the mirror says about a
    row no apply sends (a `link` a person maps). Text mode prints it verbatim instead of a sentence of its own."""
    reason = (boards.get("row") or {}).get("reason")
    return reason if isinstance(reason, str) and reason.strip() else None


def verb_new(args, root: Path) -> int:
    report, shots, facts = build_report(args)
    refused = im.refusals(report, args.by)
    if refused:
        raise Refused("\n".join(refused))
    blocking, advisory = im.validate(report, shots)
    if blocking:
        raise NotDone("not written — the report falls short of the minimum", blocking)

    by = args.by.strip()
    ts = now_ts()
    issues_dir = root / ISSUES_DIR
    issues_dir.mkdir(parents=True, exist_ok=True)
    try:
        issue_id = im.next_issue_id([*(p.name for p in issues_dir.iterdir()), *_ledger_issue_names(root)])
    except ValueError as exc:   # past ISS-9999 no file would be listed and every later `new` would reuse the id
        raise NotDone(f"not written — {exc}") from None
    slug = im.slugify(report["title"])
    report_path = issues_dir / f"{issue_id}-{slug}.md"
    shots_dir = issues_dir / issue_id
    shots_dir.mkdir(exist_ok=True)
    shots_rel: list[str] = []
    for i, shot in enumerate(shots, 1):
        kind = im.image_kind(shot) or "png"
        ext = {"jpeg": "jpg"}.get(kind, kind)
        target = shots_dir / f"screenshot-{i}.{ext}"
        shutil.copyfile(shot, target)
        shots_rel.append(f"{issue_id}/{target.name}")

    report_path.write_text(render_report(issue_id, report, facts, shots_rel, by, ts), encoding="utf-8", newline="\n")
    ledger = write_ledger(root, {
        "timestamp": ts, "event": "reported", "issue": issue_id, "title": report["title"].strip(), "channel": report["channel"],
        "environment": report["environment"], "severity": report["severity"], "frequency": report["frequency"],
        "data_impact": report["data_impact"], "reporter_role": report["reporter_role"], "spec": report.get("spec") or None,
        "feature": report.get("feature") or None,
        "by": by, "screenshots": len(shots_rel), "escaped_from": report.get("escaped_from") or None, "path": rel(report_path, root),
    })
    warnings: list[str] = []
    if report.get("escaped_from"):
        w = record_escaped_bug(args, root, issue_id, report["escaped_from"])
        if w:
            warnings.append(w)
    # The report is written before the board is asked anything: a plan that cannot be made is a warning on a
    # report that exists, never a reason for it not to.
    boards = boards_plan(args, root, issue_id) if args.to_boards else None
    if boards and boards["reason"]:
        warnings.append(boards["reason"])
    if boards and boards["planned"]:
        record_boards_planned(root, issue_id, boards, by)

    result = {"ok": True, "issue": issue_id, "status": "new", "path": rel(report_path, root),
              "screenshots": [f"{ISSUES_DIR.as_posix()}/{s}" for s in shots_rel], "ledger": rel(ledger, root),
              "feature": report.get("feature") or None,
              "proposed_risk": im.proposed_risk(report), "proposed_priority": im.proposed_priority(report),
              "advisory": advisory, "warnings": warnings, "boards": boards}
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    n = len(shots_rel)
    print(f"Written: {result['path']} ({n} screenshot{'s' if n != 1 else ''}) — status new, awaiting review"
          + (f"; feature {result['feature']}" if result["feature"] else ""))
    for a in advisory:
        print(f"  advisory: {a}")
    for w in warnings:
        print(f"  warning: {w}")
    if boards and boards["planned"]:
        for line in boards_lines(boards):
            print(line)
    print(f"Proposal: priority {result['proposed_priority']}, bugfix tier {result['proposed_risk']} — a reviewer confirms or changes both")
    print(f"Next: someone other than {by} reviews it — `report_issue.py triage --issue {issue_id} --verdict confirmed --by \"<reviewer>\"`")
    return 0


# --- reading a report back -----------------------------------------------------------------------

def read_report(path: Path) -> tuple[dict, dict[str, str], str]:
    text = path.read_text(encoding="utf-8")
    fm, body = split_frontmatter(text)
    return fm, sections(body), text


def report_from_file(fm: dict, secs: dict[str, str], path: Path) -> tuple[dict, list[Path]]:
    where: dict[str, str] = {}
    prompts = {q["prompt"].rstrip("?"): q["id"] for q in im.CHANNEL_QUESTIONS}
    for line in secs.get("Where", "").splitlines():
        m = re.match(r"^\|\s*([^|]+?)\s*\|\s*(.*?)\s*\|$", line)
        if m and m.group(1) in prompts:
            where[prompts[m.group(1)]] = m.group(2)
    steps = "\n".join(re.sub(r"^\d+\.\s*", "", s) for s in secs.get("Steps to reproduce", "").splitlines() if s.strip())
    report = {
        "channel": fm.get("channel"), "title": fm.get("title") or "", "what_happened": secs.get("What happened", ""),
        "expected": secs.get("What you expected", ""), "steps": steps, "environment": fm.get("environment") or "",
        "product_version": fm.get("product_version") or "", "severity": fm.get("severity") or "", "frequency": fm.get("frequency") or "",
        "data_impact": fm.get("data_impact") or "", "persona": fm.get("persona") or "", "reporter_role": fm.get("reporter_role") or "",
        "spec": fm.get("spec") or "", "feature": str(fm.get("feature") or "").strip(), "escaped_from": fm.get("escaped_from") or "",
        "no_client_data": "confirmed" in secs.get("Privacy check", ""), **where,
    }
    shots = [path.parent / m.group(1) for m in re.finditer(r"!\[[^\]]*\]\(([^)]+)\)", secs.get("Screenshots", ""))]
    return report, shots


def _status(fm: dict) -> str:
    s = str(fm.get("status") or "new").strip()
    return s if s in im.STATUSES else "new"


def _bugfix_spec(fm: dict) -> str | None:
    """The bugfix spec id the report names, for a refusal that points at it; None when it names none."""
    return str(fm.get("bugfix_spec") or "").strip() or None


def _boards_refusal(host: str | None) -> str | None:
    if host == "azure-devops":
        return None if MIRROR_SCRIPT.is_file() else f"{BOARDS_FEATURE} needs Shepherd Pro"
    if host is None:  # the detection itself failed: never reported as "no host"
        return "the repository's code host could not be read"
    return "no code host for this repository" if host == "none" else f"the repository's host is {host}"


def allowed_actions(fm: dict, issue_id: str, host: str | None = None) -> dict[str, dict]:
    """What the lifecycle allows from this status, and why not where it refuses — the plugin's own
    sentences, so the app's buttons disable with them verbatim. `host` is the repository's code host
    (`code_host.detect_host`, read once by the caller): on Azure DevOps a report reaches the board
    through the mirror's plan, which a named person confirms, so `file` there names that way instead."""
    status = _status(fm)
    out: dict[str, dict] = {}
    for action in ("triage", "prioritize", "promote", "fixed", "wont-fix", "duplicate", "reopen"):
        key = "triage:confirmed" if action == "triage" else action
        nxt = im.next_status(key, status)
        out[action] = {"ok": nxt is not None,
                       "reason": None if nxt is not None else im.transition_refusal(key, status, issue_id, spec=_bugfix_spec(fm)),
                       "to": nxt}
    if host == "azure-devops":
        out["file"] = {"ok": False, "reason": f"{issue_id} reaches Azure Boards through the mirror — plan it "
                                              f"(`report_issue.py file --issue {issue_id} --by <you>`), then a named person "
                                              "confirms the apply", "to": None}
    else:
        filed = bool(fm.get("filed_url"))
        out["file"] = {"ok": not filed, "reason": f"{issue_id} is already filed: {fm.get('filed_url')}" if filed else None, "to": None}
    out["note"] = {"ok": True, "reason": None, "to": None}
    out["boards"] = {"ok": host == "azure-devops", "reason": _boards_refusal(host), "to": None}
    out["set-feature"] = {"ok": True, "reason": None, "to": None}
    return out


def row_of(fm: dict, path: Path, root: Path, links: dict[str, dict] | None = None) -> dict:
    """One report as a row. `links` is `_board_links(root)`, passed in by a caller that reads many rows so the
    mirror's ledger is read once; without it the ledger is read here."""
    report, _ = report_from_file(fm, sections(split_frontmatter(path.read_text(encoding="utf-8"))[1]), path)
    issue_id = str(fm.get("issue") or path.name[:8])
    board = (_board_links(root) if links is None else links).get(issue_ref(issue_id))
    return {
        "issue": fm.get("issue") or path.name[:8], "title": fm.get("title") or "", "status": _status(fm),
        "channel": fm.get("channel") or "", "environment": fm.get("environment") or "", "product_version": fm.get("product_version") or None,
        "severity": fm.get("severity") or "", "frequency": fm.get("frequency") or "", "data_impact": fm.get("data_impact") or "",
        "persona": fm.get("persona") or "", "reporter_role": fm.get("reporter_role") or "", "spec": fm.get("spec") or None,
        "feature": str(fm.get("feature") or "").strip() or None,
        "priority": fm.get("priority") or None, "target_sprint": fm.get("target_sprint") or None,
        "triaged_by": fm.get("triaged_by") or None, "triage_verdict": fm.get("triage_verdict") or None,
        "prioritized_by": fm.get("prioritized_by") or None, "duplicate_of": fm.get("duplicate_of") or None,
        "bugfix_spec": fm.get("bugfix_spec") or None, "reported_by": fm.get("reported_by") or "", "reported_at": fm.get("reported_at") or "",
        "screenshots": int(fm.get("screenshots") or 0), "filed_host": fm.get("filed_host") or None, "filed_url": fm.get("filed_url") or None,
        "board": dict(board) if board else None,
        "escaped_from": fm.get("escaped_from") or None, "path": rel(path, root),
        "proposed_risk": im.proposed_risk(report), "proposed_priority": im.proposed_priority(report),
    }


def verb_show(args, root: Path) -> int:
    path = find_issue(root, args.issue)
    fm, secs, _ = read_report(path)
    issue_id = str(fm.get("issue") or path.name[:8])
    row = row_of(fm, path, root)
    screenshots = [f"{ISSUES_DIR.as_posix()}/{m.group(1)}" for m in re.finditer(r"!\[[^\]]*\]\(([^)]+)\)", secs.get("Screenshots", ""))]
    doc = {**row, "sections": {k: v for k, v in secs.items() if k != "Screenshots"}, "screenshot_paths": screenshots,
           "actions": allowed_actions(fm, issue_id, _code_host(root))}
    if args.json:
        print(json.dumps(doc, indent=2, ensure_ascii=False))
        return 0
    print(f"{issue_id} — {row['title']}")
    print(f"  {row['status']} · {row['environment']} · {row['channel']} · severity {row['severity']} · {row['frequency']} · data {row['data_impact']}"
          + (f" · {row['priority']}" if row["priority"] else "") + (f" → {row['target_sprint']}" if row["target_sprint"] else "")
          + (f" · spec {row['bugfix_spec']}" if row["bugfix_spec"] else ""))
    print(f"  reported by {row['reported_by']} as {row['persona']} ({row['reporter_role']}) on {row['reported_at'][:10]}")
    board = row["board"]
    print(f"  feature {row['feature'] or 'not named'} · "
          + (f"on the board #{board['work_item']} ({board['how']})" + (f" {board['url']}" if board["url"] else "") if board else "not on the board"))
    print(f"  proposal: priority {row['proposed_priority']}, tier {row['proposed_risk']}")
    for heading in ("What happened", "What you expected", "Steps to reproduce"):
        if secs.get(heading):
            print(f"  {heading}: {secs[heading].splitlines()[0]}" + (" …" if len(secs[heading].splitlines()) > 1 else ""))
    print("  can: " + ", ".join(k for k, v in doc["actions"].items() if v["ok"]))
    for k, v in doc["actions"].items():
        if not v["ok"]:
            print(f"  not {k}: {v['reason']}")
    return 0


def verb_check(args, root: Path) -> int:
    path = find_issue(root, args.issue)
    fm, secs, _ = read_report(path)
    report, shots = report_from_file(fm, secs, path)
    blocking, advisory = im.validate(report, shots)
    verdict = "COMPLETE" if not blocking else "INCOMPLETE"
    if args.json:
        print(json.dumps({"issue": fm.get("issue"), "path": rel(path, root), "verdict": verdict, "blocking": blocking, "advisory": advisory,
                          "proposed_risk": im.proposed_risk(report), "proposed_priority": im.proposed_priority(report)}, indent=2, ensure_ascii=False))
    else:
        print(f"{fm.get('issue', path.name)}: {verdict}")
        for b in blocking:
            print(f"  blocking: {b}")
        for a in advisory:
            print(f"  advisory: {a}")
    return 1 if blocking else 0


# --- list ---------------------------------------------------------------------------------------

PRIORITY_ORDER = {"P1": 0, "P2": 1, "P3": 2, None: 3}


def list_rows(root: Path) -> list[dict]:
    rows = []
    links = _board_links(root)  # the mirror's ledger, read once for the whole list
    for path in issue_files(root):
        fm, _ = split_frontmatter(path.read_text(encoding="utf-8"))
        rows.append(row_of(fm, path, root, links))
    rows.sort(key=lambda r: (im.QUEUE_ORDER.get(r["status"], 99), PRIORITY_ORDER.get(r["priority"], 3), r["issue"]), )
    # Within a status group the newest report first; the sort above is stable, so reverse the id
    # inside each (status, priority) run.
    out: list[dict] = []
    i = 0
    while i < len(rows):
        j = i
        while j < len(rows) and (rows[j]["status"], rows[j]["priority"]) == (rows[i]["status"], rows[i]["priority"]):
            j += 1
        out.extend(sorted(rows[i:j], key=lambda r: r["issue"], reverse=True))
        i = j
    return out


def verb_list(args, root: Path) -> int:
    rows = list_rows(root)
    counts = {s: sum(1 for r in rows if r["status"] == s) for s in im.STATUSES}
    queue = [r["issue"] for r in rows if r["status"] in ("new", "needs-info")]
    if args.queue:
        rows = [r for r in rows if r["status"] in ("new", "needs-info")]
    if args.status:
        if args.status not in im.STATUSES:
            raise NotDone(f"--status must be one of {', '.join(im.STATUSES)}")
        rows = [r for r in rows if r["status"] == args.status]
    if args.json:
        print(json.dumps({"issues": rows, "count": len(rows), "counts": counts, "queue": queue, "dir": ISSUES_DIR.as_posix()}, indent=2, ensure_ascii=False))
        return 0
    if not rows:
        print("no data — no issue reports" + (" in the queue" if args.queue else " yet (/sprd-report-issue writes the first)"))
        return 0
    print(f"{'issue':<9} {'status':<12} {'prio':<5} {'severity':<9} {'env':<11} {'channel':<8} title")
    for r in rows:
        print(f"{r['issue']:<9} {r['status']:<12} {r['priority'] or '—':<5} {r['severity']:<9} {r['environment']:<11} {r['channel']:<8} {r['title']}"
              + (f"  → {r['target_sprint']}" if r["target_sprint"] else "") + (f"  → spec {r['bugfix_spec']}" if r["bugfix_spec"] else "")
              + (f"  → {r['filed_url']}" if r["filed_url"] else ""))
    if queue:
        print(f"Queue: {len(queue)} awaiting review ({', '.join(queue)})")
    return 0


# --- features: the parent a report is filed under -------------------------------------------------

def _default_feature(spec_arg: str, specs: list[dict], rows: list[dict]) -> tuple[str | None, str]:
    """`(default, why)` for `--spec`: the feature that spec's `source:` names (`spec_parent`), when a brief names it.
    Never a guess: a spec that names none, several or one no brief knows is no default, with the reason."""
    spec = spec_arg.strip()
    if not im.SPEC_ID_RE.match(spec):
        return None, f"spec '{spec}' is not a spec id (four digits)"
    found = next((s for s in specs if s["id"] == spec), None)
    if found is None:
        return None, f"no parent: spec {spec} is not in specs/"
    if found["ref"] is None:
        return None, found["note"] or f"no parent: spec {spec} names no feature"
    brief = next((r for r in rows if r["ref"] == found["ref"]), None)
    if brief is None:
        named = "FE-" + found["ref"].rsplit(":", 1)[-1]
        return None, f"spec {spec}'s source names {named}, but no feature brief in this repository names it"
    return brief["id"], f"spec {spec}'s source names {brief['id']}"


def features_doc(root: Path, spec_arg: str | None) -> dict:
    """The `features --json` document: every feature brief with the specs whose `source:` names it, their channels,
    and whether the mirror's ledger links it — what the agent recommends from and the app's picker lists."""
    files = _mirror_files()
    mirror = {"configured": files is not None and (root / files[0]).is_file(),
              "ledger": files is not None and (root / files[1]).is_file()}
    try:
        rows = _feature_rows(root)
    except edition.ProRequired as exc:
        raise NotDone(str(exc))
    if not rows:
        return {"has_data": False, "features": [], "default": None, "default_reason": None, "mirror": mirror}
    specs = _spec_parents(root)
    links = _mirror_links(root)
    features = []
    for r in rows:
        mine = [s for s in specs if s["ref"] == r["ref"]]
        link = links.get(r["ref"])
        features.append({"id": r["id"], "title": r["title"], "epic": (r.get("source_row") or {}).get("epic") or None,
                         "path": r["source_path"], "specs": list(dict.fromkeys(s["id"] for s in mine)),
                         "channels": list(dict.fromkeys(s["channel"] for s in mine if s["channel"])),
                         "linked": {"work_item": link["work_item"], "how": link.get("event")} if link else None})
    default, why = _default_feature(spec_arg, specs, rows) if (spec_arg or "").strip() else (None, None)
    return {"has_data": True, "features": features, "default": default, "default_reason": why, "mirror": mirror}


def verb_features(args, root: Path) -> int:
    doc = features_doc(root, args.spec)
    if args.json:
        print(json.dumps(doc, indent=2, ensure_ascii=False))
        return 0
    if not doc["has_data"]:
        print("no data — no feature briefs in this repository (Phase 1 writes them as feature-brief-FE-NN.md)")
        return 0
    for f in doc["features"]:
        parts = ([f"epic {f['epic']}"] if f["epic"] else []) + ([f"specs {', '.join(f['specs'])}"] if f["specs"] else [])
        parts.append(f"on the board #{f['linked']['work_item']}" if f["linked"] else "not linked")
        print(f"{f['id']}  {f['title']}  ({'; '.join(parts)})")
    if (args.spec or "").strip():
        print(f"Default: {doc['default']} — {doc['default_reason']}" if doc["default"] else f"No default: {doc['default_reason']}")
    return 0


def verb_set_feature(args, root: Path) -> int:
    by = _require_person(args.by, "naming the feature")
    _refuse_secrets(args.reason)
    raw = (args.feature or "").strip()
    if raw and not im.FEATURE_ID_RE.match(raw):
        raise NotDone(f"feature: '{raw}' is not a feature id (FE-NN)")
    feature = raw.upper()
    reason = (args.reason or "").strip()
    path = find_issue(root, args.issue)
    fm, _, text = read_report(path)
    issue_id = str(fm.get("issue") or path.name[:8])
    warnings: list[str] = []
    if feature:
        try:
            known = [r["id"] for r in _feature_rows(root)]
        except edition.ProRequired as exc:
            known = None
            warnings.append(f"{exc}; {feature} recorded as typed")
        if known and feature not in known:
            raise NotDone(f"no feature brief names {feature} — the briefs name {', '.join(known)}; `features` lists them")
        if known == []:
            warnings.append(f"no feature briefs in this repository; {feature} recorded as typed")
    current = str(fm.get("feature") or "").strip().upper()
    result = {"ok": True, "issue": issue_id, "status": _status(fm), "feature": feature or None, "previous": current or None,
              "changed": current != feature, "warnings": warnings}
    if current != feature:
        ts = now_ts()
        text = set_field(text, "feature", feature)
        what = f"feature set to {feature}" if feature else "feature cleared"
        text = append_history(text, f"{ts} — {what} by {by}" + (f" — {reason}" if reason else ""))
        path.write_text(text, encoding="utf-8", newline="\n")
        write_ledger(root, {"timestamp": ts, "event": "feature", "issue": issue_id, "feature": feature or None, "by": by,
                            "reason": reason or None})
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    if not result["changed"]:
        print(f"{issue_id}: the feature is already {feature or 'not named'}. Nothing changed.")
    else:
        print(f"{issue_id}: " + (f"feature set to {feature}" if feature else "feature cleared") + f" by {by}")
    for w in warnings:
        print(f"  warning: {w}")
    return 0


# --- the lifecycle verbs ----------------------------------------------------------------------------

def _move(root: Path, path: Path, text: str, fm: dict, action: str, by: str, history_line: str, ledger: dict, fields: dict[str, str]) -> tuple[str, str]:
    """Apply a lifecycle action: the transition, the fields, the history line, the ledger. Returns
    (new_status, written text). Refuses (NotDone) with the model's own sentence."""
    issue_id = str(fm.get("issue") or path.name[:8])
    current = _status(fm)
    nxt = im.next_status(action, current)
    if nxt is None:
        raise NotDone(im.transition_refusal(action, current, issue_id, spec=_bugfix_spec(fm)))
    ts = now_ts()
    text = set_field(text, "status", nxt)
    for k, v in fields.items():
        text = set_field(text, k, v)
    text = append_history(text, f"{ts} — {history_line}")
    path.write_text(text, encoding="utf-8", newline="\n")
    write_ledger(root, {"timestamp": ts, "issue": issue_id, "by": by, "from": current, "to": nxt, **ledger})
    return nxt, text


def verb_triage(args, root: Path) -> int:
    by = _require_person(args.by, "reviewing")
    path = find_issue(root, args.issue)
    fm, _, text = read_report(path)
    issue_id = str(fm.get("issue") or path.name[:8])
    verdict = (args.verdict or "").strip()
    if verdict not in im.TRIAGE_VERDICTS:
        raise NotDone(f"--verdict must be one of {', '.join(im.TRIAGE_VERDICTS)}")
    _refuse_secrets(args.reason, args.question)
    reason = (args.reason or "").strip()
    if _same_person(by, fm.get("reported_by")) and not args.override:
        raise NotDone(f"{issue_id} was reported by {fm.get('reported_by')} — a report is reviewed by someone other than its reporter "
                      f"(another pair of eyes, the method's own rule). A team of one passes `--override --reason \"<why>\"`")
    if args.override and len(reason) < 10:
        raise NotDone("--override needs --reason in your own words (at least 10 characters)")
    fields: dict[str, str] = {"triaged_by": by, "triage_verdict": verdict}
    detail = ""
    if verdict == "needs-info":
        question = (args.question or "").strip()
        if len(question) < 10:
            raise NotDone("needs-info needs --question: what the reporter should add, in a sentence")
        detail = f"asked: {question}"
    elif verdict == "duplicate":
        of = (args.of or "").strip().upper()
        if not im.ISSUE_ID_RE.match(of):
            raise NotDone("duplicate needs --of ISS-NNNN, the report it duplicates")
        if of == issue_id:
            raise NotDone(f"{issue_id} cannot be a duplicate of itself")
        try:
            find_issue(root, of)
        except NotDone:
            raise NotDone(f"--of {of}: no such report")
        fields["duplicate_of"] = of
        detail = f"duplicate of {of}" + (f" — {reason}" if reason else "")
    elif verdict == "wont-fix":
        if len(reason) < 10:
            raise NotDone("wont-fix needs --reason in your own words (at least 10 characters) — the reporter will read it")
        detail = f"won't fix — {reason}"
    else:
        corrections = []
        if args.severity:
            if args.severity not in im.SEVERITIES:
                raise NotDone(f"--severity must be one of {', '.join(im.SEVERITIES)}")
            if args.severity != fm.get("severity"):
                corrections.append(f"severity {fm.get('severity')} → {args.severity}")
                fields["severity"] = args.severity
        if args.data_impact:
            if args.data_impact not in im.DATA_IMPACTS:
                raise NotDone(f"--data-impact must be one of {', '.join(im.DATA_IMPACTS)}")
            if args.data_impact != fm.get("data_impact"):
                corrections.append(f"data impact {fm.get('data_impact')} → {args.data_impact}")
                fields["data_impact"] = args.data_impact
        detail = "confirmed" + (f" ({'; '.join(corrections)})" if corrections else "") + (f" — {reason}" if reason else "")
    history = f"triage by {by}: {detail}" + (f" [override: {reason}]" if args.override and _same_person(by, fm.get("reported_by")) else "")
    status, text = _move(root, path, text, fm, f"triage:{verdict}", by, history,
                         {"event": "triaged", "verdict": verdict, "reason": reason or None, "of": fields.get("duplicate_of"),
                          "question": (args.question or "").strip() or None, "override": bool(args.override)}, fields)
    fm2, _ = split_frontmatter(text)
    report, _ = report_from_file(fm2, sections(split_frontmatter(text)[1]), path)
    result = {"ok": True, "issue": issue_id, "status": status, "verdict": verdict, "triaged_by": by,
              "proposed_priority": im.proposed_priority(report), "proposed_risk": im.proposed_risk(report)}
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    print(f"{issue_id}: {status} — {detail}")
    if status == "triaged":
        print(f"Next: `prioritize --issue {issue_id} --priority {result['proposed_priority']} [--target-sprint SNN]` — {result['proposed_priority']} is the proposal")
    elif status == "needs-info":
        print(f"Next: the reporter answers with `note --issue {issue_id} --note \"…\"`, then triage again")
    return 0


def _sprint_records(args, root: Path) -> list[dict] | None:
    """The sprints sprint.py lists, or None when the list cannot be read (then an id is taken as typed)."""
    try:
        proc = _sibling(root, "sprint.py", ["list", *source_args(args), "--json"])
    except NotDone:
        return None
    if proc.returncode != 0:
        return None
    try:
        doc = json.loads(proc.stdout)
    except ValueError:
        return None
    rows = doc.get("sprints") if isinstance(doc, dict) else None
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else None


def _check_target_sprint(args, root: Path, sprint_id: str) -> list[str]:
    """Warnings (never refusals) about the target sprint: unknown to sprint.py, or closed."""
    if not SPRINT_ID_RE.match(sprint_id):
        raise NotDone(f"--target-sprint '{sprint_id}' is not a sprint id (S07, S12, …)")
    if not SPRINT_SCRIPT.is_file():
        return [f"{SPRINTS_NEED_PRO}; {sprint_id} is recorded as typed"]
    records = _sprint_records(args, root)
    if records is None:
        return ["the sprint list could not be read; the target sprint is recorded as typed"]
    match = next((r for r in records if r.get("id") == sprint_id), None)
    if records and match is None:
        open_ids = [r.get("id", "?") for r in records if r.get("state") != "closed"]
        raise NotDone(f"--target-sprint {sprint_id}: sprint.py lists no such sprint — "
                      + (f"pick an open one ({', '.join(open_ids)}) or create it with /sprd-sprint new" if open_ids
                         else "every sprint record is closed; create the next sprint with /sprd-sprint new first"))
    if match is not None and match.get("state") == "closed":
        raise NotDone(f"--target-sprint {sprint_id} is closed — pick an open sprint")
    return [] if match is not None else [f"no sprint records yet; {sprint_id} is recorded as typed"]


def verb_prioritize(args, root: Path) -> int:
    by = _require_person(args.by, "prioritizing")
    path = find_issue(root, args.issue)
    fm, secs, text = read_report(path)
    issue_id = str(fm.get("issue") or path.name[:8])
    priority = (args.priority or "").strip().upper()
    _refuse_secrets(args.reason)
    report, _ = report_from_file(fm, secs, path)
    proposed = im.proposed_priority(report)
    if not priority:
        raise NotDone(f"--priority is required — the proposal from this report is {proposed} (severity {fm.get('severity')}, data impact "
                      f"{fm.get('data_impact')}, {fm.get('environment')}); a person confirms or changes it")
    if priority not in im.PRIORITIES:
        raise NotDone(f"--priority must be P1, P2 or P3 (the proposal is {proposed})")
    warnings: list[str] = []
    fields = {"priority": priority, "prioritized_by": by}
    target = (args.target_sprint or "").strip().upper()
    if target:
        warnings += _check_target_sprint(args, root, target)
        fields["target_sprint"] = target
    reason = (args.reason or "").strip()
    detail = f"{priority}" + (f" → {target}" if target else "") + (f" — the proposal was {proposed}" if priority != proposed else "") + (f" — {reason}" if reason else "")
    status, _ = _move(root, path, text, fm, "prioritize", by, f"prioritized by {by}: {detail}",
                      {"event": "prioritized", "priority": priority, "proposed_priority": proposed, "target_sprint": target or None, "reason": reason or None},
                      fields)
    result = {"ok": True, "issue": issue_id, "status": status, "priority": priority, "proposed_priority": proposed,
              "target_sprint": target or None, "warnings": warnings, "proposed_risk": im.proposed_risk(report)}
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    print(f"{issue_id}: prioritized {detail}")
    for w in warnings:
        print(f"  warning: {w}")
    print(f"Next: `promote --issue {issue_id} --risk {result['proposed_risk']}" + (" --slate" if target else "") + f" --by \"<name>\"` scaffolds the bugfix spec "
          f"({result['proposed_risk']} is the proposal)")
    return 0


def verb_promote(args, root: Path) -> int:
    by = _require_person(args.by, "confirming the fix is worth a spec")
    path = find_issue(root, args.issue)
    fm, secs, text = read_report(path)
    issue_id = str(fm.get("issue") or path.name[:8])
    current = _status(fm)
    if im.next_status("promote", current) is None:
        raise NotDone(im.transition_refusal("promote", current, issue_id))
    report, _ = report_from_file(fm, secs, path)
    proposed = im.proposed_risk(report)
    risk = (args.risk or "").strip().upper()
    if not risk:
        raise NotDone(f"--risk is required — the proposal from this report is {proposed} (data impact {fm.get('data_impact')}, "
                      f"severity {fm.get('severity')}, {fm.get('environment')}); a person confirms or changes it")
    if risk not in ("HIGH", "MEDIUM", "LOW"):
        raise NotDone(f"--risk must be HIGH, MEDIUM or LOW (the proposal is {proposed})")
    target = str(fm.get("target_sprint") or "").strip()
    slate = args.slate and SPRINT_SCRIPT.is_file()
    if slate and not target:
        records = _sprint_records(args, root)
        active = None
        if records:
            try:
                proc = _sibling(root, "sprint.py", ["list", *source_args(args), "--json"])
                active = json.loads(proc.stdout).get("active")
            except (ValueError, NotDone):
                active = None
        if not active:
            raise NotDone("--slate needs a target sprint: prioritize with --target-sprint, or have an active sprint record")
        target = str(active)

    new_args = [*source_args(args), "--name", f"fix {fm.get('title')}", "--risk", risk, "--source", issue_id, "--json"]
    if args.owner:
        new_args += ["--owner", args.owner]
    if args.team:
        new_args += ["--team", args.team]
    proc = _sibling(root, "new_spec.py", new_args)
    if proc.returncode != 0:
        raise NotDone(f"new_spec.py exited {proc.returncode}:\n{(proc.stderr or proc.stdout).strip()}")
    try:
        doc = json.loads(proc.stdout)
    except ValueError:
        raise NotDone(f"new_spec.py gave no JSON back:\n{proc.stdout.strip()}")
    spec_rel = doc.get("path")
    spec_id = str(doc.get("id") or "")
    spec_path = root / spec_rel if spec_rel else None
    if not spec_path or not spec_path.is_file():
        raise NotDone(f"new_spec.py reported a path that is not there: {spec_rel}")

    try:
        return _finish_promote(args, root, path, text, fm, issue_id, risk, proposed, target, spec_path, spec_rel, spec_id, by)
    except Exception as exc:
        # Nothing after the scaffold may leave a spec nobody's report points at: the file this run
        # created goes, and the refusal is the exit-code contract, not a traceback. But once `_move` has
        # rewritten the report it names this spec (`bugfix_spec`, status promoted), so the spec stays with it:
        # undoing one half would leave a promoted report that points at a file that is gone.
        if _rewritten(path, text):
            raise NotDone(f"promote stopped after the report was updated ({exc}); the report and the bugfix spec "
                          f"{spec_rel} were both left as they are, nothing was undone") from None
        try:
            spec_path.unlink()
        except OSError:
            pass
        if isinstance(exc, (NotDone, Refused)):
            raise
        raise NotDone(f"promote stopped after the scaffold and undid it: {exc}")


def _rewritten(path: Path, before: str) -> bool:
    """Whether the report on disk is no longer the text `before` it was read as. A file that cannot be read says
    yes: not knowing is a reason to keep the spec, never to delete it."""
    try:
        return path.read_text(encoding="utf-8") != before
    except OSError:
        return True


def _finish_promote(args, root: Path, path: Path, text: str, fm: dict, issue_id: str, risk: str, proposed: str, target: str,
                    spec_path: Path, spec_rel: str, spec_id: str, by: str) -> int:
    # The scaffold is a feature spec; a fix is a bugfix (the harness's repro-gate reads `type`).
    # One frontmatter line changes; the body stays the template's for the author to fill, with
    # the Goal pointing at the report so the acceptance checks start from its steps.
    spec_text = spec_path.read_text(encoding="utf-8")
    spec_text = re.sub(r"^type: feature\b[^\r\n]*", "type: bugfix            # repro-gate: the new test FAILS against the pre-fix code", spec_text, count=1, flags=re.MULTILINE)
    spec_text = spec_text.replace("## Goal\n", f"## Goal\n\nFix {issue_id} — {fm.get('title')}. Seen in {fm.get('environment')} on the "
                                                f"{fm.get('channel')} channel as {fm.get('persona')}; severity {fm.get('severity')}, data impact "
                                                f"{fm.get('data_impact')}, priority {fm.get('priority') or 'unset'}. The report — steps, screenshot, "
                                                f"environment — is `{rel(path, root)}`; the first acceptance check is its reproduction.\n", 1)
    spec_path.write_text(spec_text, encoding="utf-8")

    slated: dict | None = None
    warnings: list[str] = []
    slate = args.slate and SPRINT_SCRIPT.is_file()
    if args.slate and not slate:
        warnings.append(f"{SPRINTS_NEED_PRO}; spec {spec_id} was not slated")
    if slate:
        sl = _sibling(root, "sprint.py", ["slate", *source_args(args), "--sprint", target, "--spec", spec_id, "--by", by])
        first = (sl.stdout or sl.stderr).strip().splitlines()
        slated = {"sprint": target, "exit": sl.returncode, "said": first[0] if first else ""}
        if sl.returncode != 0:
            warnings.append(f"sprint.py slate --sprint {target} --spec {spec_id} exited {sl.returncode}: {slated['said']}")

    detail = f"promoted to bugfix spec {spec_id} ({risk}) by {by}" + (f" — the proposal was {proposed}" if risk != proposed else "")
    if slated:
        detail += f"; slated into {target}" if slated["exit"] == 0 else f"; slate into {target} refused (exit {slated['exit']})"
    status, _ = _move(root, path, text, fm, "promote", by, detail,
                      {"event": "promoted", "spec": spec_id, "risk": risk, "proposed_risk": proposed, "slated": slated}, {"bugfix_spec": spec_id})
    result = {"ok": True, "issue": issue_id, "status": status, "spec": spec_id, "path": spec_rel, "risk": risk, "proposed_risk": proposed,
              "slated": slated, "warnings": warnings}
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    print(f"Bugfix spec {spec_id} scaffolded at {spec_rel} ({risk}" + (f"; the proposal was {proposed}" if risk != proposed else "") + ")")
    if slated and slated["exit"] == 0:
        print(f"Slated into {target}: {slated['said']}")
    for w in warnings:
        print(f"  warning: {w}")
    print(f"Next: /sprd-spec --spec {spec_id} to write the acceptance checks — the first one is the repro: a test that fails on the pre-fix code")
    return 0


def verb_note(args, root: Path) -> int:
    by = _require_person(args.by, "writing the note")
    note = (args.note or "").strip()
    if len(note) < 3:
        raise NotDone("--note is required: what you want the fixer or the reporter to know")
    _refuse_secrets(note)
    path = find_issue(root, args.issue)
    fm, _, text = read_report(path)
    issue_id = str(fm.get("issue") or path.name[:8])
    ts = now_ts()
    text = append_history(text, f"{ts} — note by {by}: {note}")
    path.write_text(text, encoding="utf-8", newline="\n")
    write_ledger(root, {"timestamp": ts, "event": "note", "issue": issue_id, "by": by, "note": note})
    if args.json:
        print(json.dumps({"ok": True, "issue": issue_id, "status": _status(fm), "note": note}, indent=2, ensure_ascii=False))
    else:
        print(f"{issue_id}: note recorded" + (" — triage it again when the answer is enough" if _status(fm) == "needs-info" else ""))
    return 0


def verb_reopen(args, root: Path) -> int:
    by = _require_person(args.by, "reopening")
    reason = (args.reason or "").strip()
    if len(reason) < 10:
        raise NotDone("reopen needs --reason in your own words (at least 10 characters) — what still happens")
    _refuse_secrets(reason)
    path = find_issue(root, args.issue)
    fm, _, text = read_report(path)
    issue_id = str(fm.get("issue") or path.name[:8])
    # Back to `new` means back to the start: the review, the priority and the target sprint are
    # cleared so the lifecycle runs again honestly; the bugfix spec stays on the record (it was
    # built) and the history says so.
    kept = f" — bugfix spec {fm.get('bugfix_spec')} kept on the record" if fm.get("bugfix_spec") else ""
    status, _ = _move(root, path, text, fm, "reopen", by, f"reopened by {by}: {reason}{kept}", {"event": "reopened", "reason": reason},
                      {"triaged_by": "", "triage_verdict": "", "duplicate_of": "", "priority": "", "target_sprint": "", "prioritized_by": ""})
    if args.json:
        print(json.dumps({"ok": True, "issue": issue_id, "status": status}, indent=2, ensure_ascii=False))
    else:
        print(f"{issue_id}: {status} — {reason}")
    return 0


def _spec_status(root: Path, spec_id: str) -> str | None:
    specs = root / "specs"
    if not specs.is_dir():
        return None
    for p in specs.glob(f"{spec_id}-*.md"):
        fm, _ = split_frontmatter(p.read_text(encoding="utf-8"))
        return str(fm.get("status") or "").strip() or None
    return None


def verb_sync(args, root: Path) -> int:
    """Promoted reports follow their bugfix spec: `status: merged` on the spec (written by
    spec_status.py once the PR merged) makes the report `fixed`. Reads the spec file; writes only
    the report and its ledger."""
    changed: list[dict] = []
    waiting: list[dict] = []
    for path in issue_files(root):
        fm, _, text = read_report(path)
        if _status(fm) != "promoted" or not fm.get("bugfix_spec"):
            continue
        spec_id = str(fm["bugfix_spec"])
        spec_status = _spec_status(root, spec_id)
        if spec_status == "merged":
            status, _ = _move(root, path, text, fm, "fixed", f"spec {spec_id}", f"fixed — bugfix spec {spec_id} merged (sync)",
                              {"event": "fixed", "spec": spec_id, "via": "sync"}, {})
            changed.append({"issue": fm.get("issue"), "spec": spec_id, "status": status})
        else:
            waiting.append({"issue": fm.get("issue"), "spec": spec_id, "spec_status": spec_status})
    if args.json:
        print(json.dumps({"ok": True, "fixed": changed, "waiting": waiting}, indent=2, ensure_ascii=False))
        return 0
    if not changed and not waiting:
        print("no data — no promoted reports to follow")
        return 0
    for c in changed:
        print(f"{c['issue']}: fixed — spec {c['spec']} merged")
    for w in waiting:
        print(f"{w['issue']}: waiting — spec {w['spec']} is {w['spec_status'] or 'unreadable'}")
    return 0


def verb_set_status(args, root: Path) -> int:
    by = _require_person(args.by, "deciding")
    status = (args.status or "").strip()
    if status not in ("fixed", "wont-fix", "duplicate"):
        raise NotDone("--status must be fixed, wont-fix or duplicate (triage, prioritize, promote and reopen move the others)")
    reason = (args.reason or "").strip()
    _refuse_secrets(reason)
    if status in ("wont-fix", "duplicate") and len(reason) < 10 and not (status == "duplicate" and args.of):
        raise NotDone(f"{status} needs --reason in your own words (at least 10 characters) — the reporter will read it")
    path = find_issue(root, args.issue)
    fm, _, text = read_report(path)
    issue_id = str(fm.get("issue") or path.name[:8])
    if _status(fm) == status:
        if args.json:
            print(json.dumps({"ok": True, "issue": issue_id, "status": status, "changed": False, "message": f"already {status}; nothing changed"}, indent=2, ensure_ascii=False))
        else:
            print(f"{issue_id} is already {status}. Nothing changed.")
        return 0
    fields: dict[str, str] = {}
    if status == "duplicate":
        of = (args.of or "").strip().upper()
        if not im.ISSUE_ID_RE.match(of):
            raise NotDone("duplicate needs --of ISS-NNNN, the report it duplicates")
        if of == issue_id:
            raise NotDone(f"{issue_id} cannot be a duplicate of itself")
        try:
            find_issue(root, of)
        except NotDone:
            raise NotDone(f"--of {of}: no such report")
        fields["duplicate_of"] = of
    detail = status + (f" of {fields['duplicate_of']}" if status == "duplicate" else "") + (f": {reason}" if reason else "")
    new_status, _ = _move(root, path, text, fm, status, by, f"{detail} by {by}" if status != "fixed" else f"fixed by {by}" + (f": {reason}" if reason else ""),
                          {"event": "status", "status": status, "reason": reason or None, "of": fields.get("duplicate_of")}, fields)
    if args.json:
        print(json.dumps({"ok": True, "issue": issue_id, "status": new_status, "reason": reason or None}, indent=2, ensure_ascii=False))
    else:
        print(f"{issue_id}: {detail}")
    return 0


# --- file ---------------------------------------------------------------------------------------

def host_body(fm: dict, secs: dict[str, str], path_rel: str) -> str:
    """What the code host shows: the reporter's sections verbatim, the facts up top, the
    screenshots named by their repository path (neither CLI attaches files)."""
    head = (f"**{fm.get('issue')}** · {fm.get('environment')} · severity `{fm.get('severity')}` · {fm.get('frequency')} · "
            f"data impact `{fm.get('data_impact')}` · seen on the {fm.get('channel')} channel as {fm.get('persona')}"
            + (f" · priority {fm.get('priority')}" if fm.get("priority") else "") + (f" · spec {fm.get('spec')}" if fm.get("spec") else "")
            + (f" · bugfix spec {fm.get('bugfix_spec')}" if fm.get("bugfix_spec") else ""))
    parts = [head, ""]
    for heading in ("What happened", "What you expected", "Steps to reproduce", "Where", "Environment"):
        if secs.get(heading):
            parts += [f"### {heading}", secs[heading], ""]
    n = int(fm.get("screenshots") or 0)
    parts += ["### Screenshots", f"{n} in the repository under `{Path(path_rel).parent.as_posix()}/{fm.get('issue')}/`.", "",
              f"_Reported with /sprd-report-issue; the record is `{path_rel}`._"]
    return "\n".join(parts)


def file_argv(host: str, remote, title: str, body_path: Path, label: str | None) -> list[str]:
    """The GitHub filing argv. Azure DevOps never reaches here: a report goes to the board through the mirror
    (`hand_over`), so no `az` argv is built in this file."""
    if host == "github":
        argv = ["gh", "issue", "create", "--title", title, "--body-file", str(body_path)]
        if remote is not None:
            argv += ["--repo", remote.slug]
        if label:
            argv += ["--label", label]
        return argv
    raise NotDone("no code host for this repository — pin one with `set_setting.py code-host github|azure-devops` (or run with --host)")


def parse_filed(host: str, stdout: str) -> tuple[str, str]:
    """(url, id) from gh's own output: it prints the URL."""
    urls = re.findall(r"https?://\S+", stdout)
    if not urls:
        raise NotDone(f"gh gave no URL back:\n{stdout.strip()}")
    url = urls[-1].rstrip(".")
    return url, url.rsplit("/", 1)[-1]


def plan_command(issue_id: str) -> list[str]:
    """The mirror's plan for one report, as `file` runs it (`boards_plan`, with this repository's --repo/--state)."""
    return ["ado_sync.py", "plan", "--kind", "issue", "--id", issue_id, "--no-comments", "--json"]


def hand_over(args, root: Path, fm: dict, issue_id: str, by: str) -> int:
    """`file` on Azure DevOps: the report reaches the board through the Azure Boards mirror, never through `az` here.
    `--dry-run` names the plan command and runs nothing. A real run runs that plan as a sibling (`boards_plan`) and
    hands back its `boards` block — exit 0 when the plan holds this report's row, else exit 1 with the plan's own
    reason. The report's `filed_*` is never written (the pairing is the mirror's ledger); the one record is a
    `boards_planned` line. A report filed the old way (`filed_id`) is the plan's `link` row, never a second Bug."""
    if args.dry_run:
        note = ("on Azure DevOps a report reaches the board through the Azure Boards mirror: `file` runs this plan for "
                "the repository and hands back its hash, and a named person confirms the apply "
                "(`ado_sync.py apply --confirm <hash> --by <you>`). Nothing was run")
        if args.label:
            note += "; --label is not used here: the mirror writes the report's own tags"
        if args.json:
            print(json.dumps({"ok": True, "dry_run": True, "host": "azure-devops", "handover": True,
                              "command": plan_command(issue_id), "note": note}, indent=2, ensure_ascii=False))
        else:
            print(f"Would hand {issue_id} over to the Azure Boards mirror (cwd {root}):")
            print("  " + " ".join(plan_command(issue_id)))
            print(f"Note: {note}")
        return 0
    boards = boards_plan(args, root, issue_id)
    if not boards["planned"]:
        raise NotDone(boards["reason"] or f"the mirror's plan has nothing to send for {issue_ref(issue_id)}")
    record_boards_planned(root, issue_id, boards, by)
    if args.json:
        print(json.dumps({"ok": True, "issue": issue_id, "status": _status(fm), "host": "azure-devops", "handover": True,
                          "boards": boards}, indent=2, ensure_ascii=False))
        return 0
    print(f"{issue_id} handed over to the Azure Boards mirror — nothing is on the board until a named person applies the plan")
    for line in boards_lines(boards):
        print(line)
    if args.label:
        print("  --label is not used here: the mirror writes the report's own tags")
    prior = str(fm.get("filed_id") or "").strip()
    # A row's own reason (printed above by boards_lines) already says what a person runs; the rebuilt line is only
    # for a link row the plan gave no reason for.
    if (not row_reason(boards) and (boards["row"] or {}).get("action") == "link"
            and fm.get("filed_host") == "azure-devops" and prior.isdigit()):
        print(f"{issue_id} was filed as #{prior} before the bridge: `ado_sync.py link {issue_ref(issue_id)} --work-item {prior} "
              "--by <you>` pairs the two (a named person runs it; nothing here does)")
    return 0


def verb_file(args, root: Path) -> int:
    by = _require_person(args.by, "filing")
    path = find_issue(root, args.issue)
    fm, secs, text = read_report(path)
    issue_id = str(fm.get("issue") or path.name[:8])
    import code_host as ch
    detection = ch.detect_host(root, args.host)
    host = detection.host
    if host == "azure-devops":
        # The mirror pairs a report filed the old way (its `filed_id`) as a `link` row: not "already filed".
        return hand_over(args, root, fm, issue_id, by)
    if fm.get("filed_url"):
        raise NotDone(f"{issue_id} is already filed: {fm['filed_url']}")
    if host != "github":
        # Said before anything is written: a dry run against no host leaves nothing behind.
        file_argv(host, detection.remote, "", Path("-"), None)
    body = host_body(fm, secs, rel(path, root))
    if args.dry_run:
        # A dry run writes NOTHING into the repository: the body goes to a temp file so the printed
        # command is still runnable as shown, and the preview says so.
        import tempfile
        fd, tmp = tempfile.mkstemp(prefix=f"{issue_id}-host-body-", suffix=".md")
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(body)
        body_path = Path(tmp)
    else:
        body_path = root / ISSUES_DIR / issue_id / "host-body.md"   # written below, once the CLI is known to be there
    argv = file_argv(host, detection.remote, str(fm.get("title") or issue_id), body_path, args.label)

    if args.dry_run:
        shown = [a if len(a) < 200 else a[:197] + "…" for a in argv]
        if args.json:
            print(json.dumps({"ok": True, "dry_run": True, "host": host, "cwd": str(root), "argv": shown, "body": str(body_path),
                              "note": "the body is a temporary file for this preview; nothing was written into the repository"}, indent=2, ensure_ascii=False))
        else:
            print(f"Would run (cwd {root}):")
            print("  " + " ".join(json.dumps(a, ensure_ascii=False) if re.search(r"\s", a) else a for a in shown))
            print(f"Body: {body_path} (a temporary file for this preview; nothing was written into the repository)")
        return 0

    cli = argv[0]
    if shutil.which(cli) is None:   # said before the body is written: "nothing written" leaves no file behind
        raise NotDone(f"{cli} is not installed — the {host} host is filed through it")
    kept = body_path.exists()
    body_path.parent.mkdir(parents=True, exist_ok=True)
    body_path.write_text(body, encoding="utf-8", newline="\n")

    def _drop_body() -> None:   # a filing that did not happen leaves no body file this run made
        if not kept:
            try:
                body_path.unlink()
            except OSError:
                pass

    try:
        proc = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
                              check=False, cwd=str(root), env={**os.environ})
    except (OSError, subprocess.TimeoutExpired) as exc:
        _drop_body()
        raise NotDone(f"{cli} did not run: {exc}")
    if proc.returncode != 0:
        _drop_body()
        raise NotDone(f"{cli} exited {proc.returncode}:\n{(proc.stderr or proc.stdout).strip()}")
    url, wid = parse_filed(host, proc.stdout)
    ts = now_ts()
    text = set_field(text, "filed_host", host)
    text = set_field(text, "filed_url", url)
    text = set_field(text, "filed_id", wid)
    text = append_history(text, f"{ts} — filed on {host} by {by}: {url or wid}")
    path.write_text(text, encoding="utf-8", newline="\n")
    write_ledger(root, {"timestamp": ts, "event": "filed", "issue": issue_id, "host": host, "url": url, "id": wid, "by": by})
    if args.json:
        print(json.dumps({"ok": True, "issue": issue_id, "status": _status(fm), "host": host, "url": url, "id": wid, "argv": argv[:3]}, indent=2, ensure_ascii=False))
    else:
        print(f"Filed {issue_id} on {host}: {url or wid}")
    return 0


# --- CLI ----------------------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    src = common.add_mutually_exclusive_group()
    src.add_argument("--state", help="Path to .sdlc/state.yaml (workflow mode; repo root = parent of .sdlc/)")
    src.add_argument("--repo", default=".", help="Target repo root (standalone mode; default: cwd)")
    common.add_argument("--json", action="store_true", help="Emit one JSON document")
    by = argparse.ArgumentParser(add_help=False)
    by.add_argument("--by", required=True, metavar="NAME", help="A named human - an AI name is refused")
    issue = argparse.ArgumentParser(add_help=False)
    issue.add_argument("--issue", required=True, help="ISS-NNNN, NNNN, or the report's path")

    parser = argparse.ArgumentParser(
        description="Bugs in the product the team is building, from report to fix: a report that carries the minimum a fixer needs, "
                    "reviewed by someone other than its reporter, prioritized, promoted to a type: bugfix spec a sprint can slate. "
                    "Nothing is written until the minimum is met; a secret-shaped string is refused.")
    sub = parser.add_subparsers(dest="verb", required=True)

    p = sub.add_parser("questions", parents=[common], help="The question plan (optionally for one channel)")
    p.add_argument("--channel", default=None, help=f"One of {', '.join(im.CHANNELS)}")

    p = sub.add_parser("env", parents=[common], help="The build under test: repository, branch, commit, code host, this machine")
    p.add_argument("--app-version", default=None, help="The desktop app's version, when the app is the caller")

    p = sub.add_parser("new", parents=[common], help="Write a report (only once it clears the minimum)")
    p.add_argument("--title", required=True, help=f"One line, {im.MIN_TITLE_CHARS}-{im.MAX_TITLE_CHARS} characters")
    p.add_argument("--channel", required=True, help=f"Where in the product: one of {', '.join(im.CHANNELS)}")
    p.add_argument("--what", required=True, help=f"What happened (>= {im.MIN_WHAT_CHARS} characters)")
    p.add_argument("--expected", required=True, help=f"What you expected (>= {im.MIN_EXPECTED_CHARS} characters)")
    p.add_argument("--steps", action="append", default=[], metavar="STEP", help="A step to reproduce (repeatable; newlines split too)")
    p.add_argument("--environment", required=True, help=f"One of {', '.join(im.ENVIRONMENTS)}")
    p.add_argument("--product-version", default=None, dest="product_version", help="The build, tag or commit under test (local runs take git's)")
    p.add_argument("--severity", required=True, help=f"One of {', '.join(im.SEVERITIES)}")
    p.add_argument("--frequency", required=True, help=f"One of {', '.join(im.FREQUENCIES)}")
    p.add_argument("--data-impact", required=True, dest="data_impact", help=f"One of {', '.join(im.DATA_IMPACTS)}")
    p.add_argument("--persona", required=True, help="The type of user you were acting as, in the product's own terms")
    p.add_argument("--reporter-role", required=True, dest="reporter_role", help=f"Your role on the team: one of {', '.join(im.REPORTER_ROLES)}")
    p.add_argument("--spec", default="", help="The spec this part of the product was built under (NNNN), optional")
    p.add_argument("--feature", default="", metavar="FE-NN",
                   help="The feature this part of the product belongs to (FE-NN, from the feature briefs), optional; "
                        "on Azure DevOps the Bug is filed under it")
    p.add_argument("--to-boards", action="store_true", dest="to_boards",
                   help="After writing, run the Azure Boards mirror's plan for this report (ado_sync.py plan --kind issue); "
                        "it is never applied here - a named person confirms the apply")
    p.add_argument("--screenshot", action="append", default=[], metavar="PATH", help="An image file (repeatable; at least one)")
    p.add_argument("--no-client-data", action="store_true", dest="no_client_data",
                   help="The reporter's statement: nothing in the screenshots or the words is client data, personal data or a secret")
    p.add_argument("--answer", action="append", default=[], metavar="KEY=VALUE",
                   help="A channel question's answer (`questions --channel X` lists them), repeatable")
    p.add_argument("--env-json", default=None, metavar="PATH", help="The document `env --json` printed, saved to a file")
    p.add_argument("--escaped-from", default=None, metavar="CHECK",
                   help="The check that should have caught this; also records scorecard.py's escaped_bug event")
    p.add_argument("--by", required=True, metavar="NAME", help="The person reporting, by name - an AI name is refused")

    sub.add_parser("show", parents=[common, issue], help="One report in full, with the actions the lifecycle allows and why not")
    sub.add_parser("check", parents=[common, issue], help="Re-validate an existing report (exit 1 when it falls short)")

    p = sub.add_parser("list", parents=[common], help="The queue - what needs a decision first")
    p.add_argument("--status", default=None, help=f"Only one of {', '.join(im.STATUSES)}")
    p.add_argument("--queue", action="store_true", help="Only the reports awaiting review (new, needs-info)")

    p = sub.add_parser("features", parents=[common],
                       help="Every feature brief, its specs and channels, and whether the board links it (read-only)")
    p.add_argument("--spec", default=None, metavar="NNNN", help="Also name the feature this spec's source names, as the default")

    p = sub.add_parser("set-feature", parents=[common, issue, by], help="Name (or clear) the feature a report belongs to")
    p.add_argument("--feature", required=True, metavar="FE-NN", help='The feature id (FE-NN); "" clears it')
    p.add_argument("--reason", default=None, help="Why this feature, in your own words (optional)")

    p = sub.add_parser("triage", parents=[common, issue, by], help="Review a report: confirmed | needs-info | duplicate | wont-fix")
    p.add_argument("--verdict", required=True, help=f"One of {', '.join(im.TRIAGE_VERDICTS)}")
    p.add_argument("--severity", default=None, help="Correct the severity while confirming")
    p.add_argument("--data-impact", default=None, dest="data_impact", help="Correct the data impact while confirming")
    p.add_argument("--question", default=None, help="needs-info: what the reporter should add")
    p.add_argument("--of", default=None, metavar="ISS-NNNN", help="duplicate: the report it duplicates")
    p.add_argument("--reason", default=None, help="wont-fix: why (required); confirmed: a note; with --override: why the reporter reviews")
    p.add_argument("--override", action="store_true", help="Let the reporter review their own report (a team of one) - needs --reason")

    p = sub.add_parser("prioritize", parents=[common, issue, by], help="P1 | P2 | P3 and a target sprint, confirming the proposal or not")
    p.add_argument("--priority", default=None, help="P1 (fix now) | P2 (next sprint) | P3 (backlog)")
    p.add_argument("--target-sprint", default=None, dest="target_sprint", metavar="SNN", help="The sprint the fix should land in (an open sprint.py record)")
    p.add_argument("--reason", default=None, help="Why, when the priority differs from the proposal")

    p = sub.add_parser("promote", parents=[common, issue, by], help="Scaffold a type: bugfix spec from the report (new_spec.py)")
    p.add_argument("--risk", default=None, help="HIGH | MEDIUM | LOW - the person confirms or changes the report's proposal")
    p.add_argument("--owner", default=None, help="Code-host handle of the accountable owner (e.g. @priya-n)")
    p.add_argument("--team", default=None, help="The team the fix belongs to")
    p.add_argument("--slate", action="store_true", help="Also slate the new spec into the target sprint through sprint.py slate")

    p = sub.add_parser("note", parents=[common, issue, by], help="A dated note by a named person")
    p.add_argument("--note", required=True, help="What the fixer or the reporter should know")

    p = sub.add_parser("reopen", parents=[common, issue, by], help="A closed report back to new, with a reason")
    p.add_argument("--reason", required=True, help="What still happens")

    sub.add_parser("sync", parents=[common], help="Promoted reports whose bugfix spec merged become fixed")

    p = sub.add_parser("file", parents=[common, issue, by],
                       help="Open the report on the product's code host (GitHub: gh issue create; Azure DevOps: the "
                            "Azure Boards mirror's plan, which a named person confirms)")
    p.add_argument("--host", choices=["github", "azure-devops"], default=None, help="Override the detected host for this run")
    p.add_argument("--label", default=None,
                   help="A GitHub label to add, e.g. bug (on Azure DevOps the mirror writes the report's own tags)")
    p.add_argument("--dry-run", action="store_true", dest="dry_run",
                   help="Print the exact command instead of running it (on Azure DevOps: the mirror's plan command)")

    p = sub.add_parser("set-status", parents=[common, issue, by], help="fixed | wont-fix | duplicate, under the lifecycle's rules")
    p.add_argument("--status", required=True, help="fixed | wont-fix | duplicate")
    p.add_argument("--reason", default=None, help="Required for wont-fix; optional beside --of for duplicate; optional for fixed")
    p.add_argument("--of", default=None, metavar="ISS-NNNN", help="duplicate: the report it duplicates (required)")
    return parser


VERBS = {"questions": verb_questions, "env": verb_env, "new": verb_new, "show": verb_show, "check": verb_check, "list": verb_list,
         "features": verb_features, "set-feature": verb_set_feature, "triage": verb_triage, "prioritize": verb_prioritize, "promote": verb_promote, "note": verb_note, "reopen": verb_reopen,
         "sync": verb_sync, "file": verb_file, "set-status": verb_set_status}


def main(argv: list[str] | None = None) -> int:
    # The output carries '—' and '→'; on a Windows pipe stdout is cp1252 and would raise AFTER a
    # write landed. UTF-8 with replacement, so the exit code and the words always arrive.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    try:
        root = resolve_repo_root(args) if args.verb != "questions" else None
        return VERBS[args.verb](args, root)
    except Refused as exc:
        if getattr(args, "json", False):
            print(json.dumps({"ok": False, "refused": True, "reasons": str(exc).split("\n")}, indent=2, ensure_ascii=False))
        else:
            print(f"Refused: {exc}")
        return 2
    except NotDone as exc:
        if getattr(args, "json", False):
            print(json.dumps({"ok": False, "refused": False, "error": str(exc), "gaps": exc.gaps}, indent=2, ensure_ascii=False))
        else:
            print(f"Error: {exc}")
            for g in exc.gaps:
                print(f"  - {g}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
