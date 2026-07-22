# Backlog → Tickets mode

> **Backend:** Resolve `issues.*` through the active environment profile before this flow. Provider
> details and write permissions remain outside this public reference.

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
profile-resolved `issues.read` capability and the selected `field_inheritance` policy. If no template is
given, follow the profile's default-project and parent-resolution policy; ask the user whenever those
values are absent or confirmation is required.

**T4. Create the parent + children.** Use the profile-resolved `issues.create` capability and inherit
only fields named by the active policy. Body format per [ticket-template.md](ticket-template.md), using
the profile's content language.

When `description_write` is `create_then_update_markdown`, create with a minimal description and then
apply the real body through the profile-resolved `issues.update` capability. Other providers use their
declared write behavior; never infer a provider-specific workaround in this public workflow.

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
- **Honor provider write policy.** If the profile requires a create-then-update sequence, record the
  created ticket before the update so interruption cannot cause a duplicate on retry.
- **One ticket can still need multiple PRs.** If a themed ticket spans files owned by different CODEOWNERS
  teams, note that in the ticket so it ships as sibling PRs (one per ownership boundary), not one mega-PR.
