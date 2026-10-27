# Changelog

## 2.2.0

- **`/sprd-update`** says which Shepherd you run, which release is current, and runs the one
  `claude plugin` step that moves you forward when you say yes. It then offers to turn on Claude
  Code's automatic updates, which are off by default for this catalogue. `docs/updating.md` has
  the route by hand.

## 2.1.0 — first public release

Shepherd Free is published under the Apache License 2.0. It is generated from Shepherd's source,
so this changelog starts here rather than carrying the source's history.

- **The phase lifecycle**: discovery to close, each phase with its documents, gates and sign-off.
- **Specs as the unit of Build work**: one spec, one branch, one pull request, with a Definition
  of Ready enforced before work starts and a risk tier that sets how much checking it needs.
- **Bug reports as records** (`/sprd-report-issue`): an interview that captures what a fixer needs,
  review by someone other than the reporter, a priority, promotion to a bugfix spec, and filing on
  GitHub.
- **The delivery harness**, installed by `/sprd-harness`: CI rails, hooks, agents and skills.
- **The `starter` profile**, and the schema any company's own profile is validated against.
