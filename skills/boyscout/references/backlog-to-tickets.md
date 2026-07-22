# Backlog → Tickets mode

> **Backend:** Select the ticket backend from explicit repository/user context. Concrete provider
> operation names and write permissions remain outside this public reference.

Loaded when `/boyscout` is invoked as `/boyscout tickets`. Use it to convert an aged or themed slice of
the backlog into tracked tickets — typically an epic plus child tickets — when the findings are too
many or too large to attack inline. It is the bulk counterpart to the single-finding ticket path
(Step 4B); the ticket body format comes from [ticket-template.md](ticket-template.md).

## When to use

- The backlog has grown and several findings against the same target/theme deserve tracking rather than
  immediate fixing.
- You want to group related findings under one epic so they can be scheduled and split into PRs by owner.

## Workflow

**T1. Filter candidates.** Load the backlog (`backlog.py list --json`). Narrow to the slice worth
ticketing — by target (`--target`), by age (`backlog.py sweep --days N` surfaces stale items), and by
running `backlog.py dedup-check` so duplicates are merged, not ticketed twice.

**T2. Propose theme groupings.** Cluster the filtered findings into coherent themes (e.g. "docs robustness",
"tooling", "new modes"). Present the groupings with `AskUserQuestion` and let the user confirm, merge, or
split them. Each group becomes one ticket (or one workstream/acceptance-criteria block within a ticket).

**T3. Accept a template ticket.** Ask the user for an existing ticket URL/key to inherit from. Use the
selected backend's read operation and inherit only fields the user confirms. If no template is given,
ask for the project/parent context instead of assuming an organization-specific default.

**T4. Create the parent + children.** Use the selected backend's create operation. Body format per
[ticket-template.md](ticket-template.md), all content in English unless explicit project policy says
otherwise.

Provider-specific formatting workarounds belong in private configuration or an optional provider
adapter, never in this public workflow.

**T5. Prune consumed findings.** Once a finding is captured in a ticket, remove it from the backlog with
`backlog.py remove --target … --summary …` (the selected tracker is now the source of truth). Prune as each ticket is
created, not at the end, so an interrupted run stays consistent. Run `backlog.py validate` after the batch.

**T6. End-of-run summary.** List every ticket created with its URL and the findings it absorbed, plus any
findings left in the backlog and why.

## Pitfalls

- **Don't ticket duplicates.** Run `dedup-check` in T1 — two findings with the same (target, summary) become
  one ticket.
- **Don't lose board placement.** The whole point of the template ticket (T3) is inheriting epic/labels/
  components; a ticket created without them disappears from the team's filters.
- **Honor provider policy.** Do not copy an environment-specific formatting workaround into this public flow.
- **One ticket can still need multiple PRs.** If a themed ticket spans files owned by different CODEOWNERS
  teams, note that in the ticket so it ships as sibling PRs (one per ownership boundary), not one mega-PR.
