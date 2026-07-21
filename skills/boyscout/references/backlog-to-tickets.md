# Backlog → Tickets mode

> **Backend:** This reference describes the Jira bulk-ticket flow. For GitHub Issues or GitLab, the equivalent uses `gh issue create` / `glab issue create` with labels and milestones instead of epics. Adapt the create steps per [ticket-github.md](ticket-github.md) or [ticket-gitlab.md](ticket-gitlab.md).

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

**T3. Accept a template ticket.** Ask the user for an existing ticket URL/key to inherit from. Fetch it
with `mcp__jira__getJiraIssue` and read its **project, parent epic, labels, and components** — new tickets
inherit these so they land in the right place on the board. If no template is given, fall back to the
Step 4B ladder (project `PROJ`, current KTLO epic), confirmed with the user.

**T4. Create the epic + children.** Create with `mcp__jira__createJiraIssue` inheriting the template's
epic/labels/components. Body format per [ticket-template.md](ticket-template.md), all content in English.

> **Multiline-description gotcha:** `mcp__jira__createJiraIssue` double-escapes `\n` in the `description`
> field, so a multiline body renders as literal `\n`. Create the issue with a minimal/one-line description,
> then set the real body with `mcp__jira__editJiraIssue` using `contentFormat: "markdown"`. Apply the same
> two-step (create → edit-with-markdown) to every child ticket.

**T5. Prune consumed findings.** Once a finding is captured in a ticket, remove it from the backlog with
`backlog.py remove --target … --summary …` (Jira is now the source of truth). Prune as each ticket is
created, not at the end, so an interrupted run stays consistent. Run `backlog.py validate` after the batch.

**T6. End-of-run summary.** List every ticket created with its URL and the findings it absorbed, plus any
findings left in the backlog and why.

## Pitfalls

- **Don't ticket duplicates.** Run `dedup-check` in T1 — two findings with the same (target, summary) become
  one ticket.
- **Don't lose board placement.** The whole point of the template ticket (T3) is inheriting epic/labels/
  components; a ticket created without them disappears from the team's filters.
- **Don't skip the create→edit markdown step (T4).** A description full of literal `\n` is the most common
  failure here.
- **One ticket can still need multiple PRs.** If a themed ticket spans files owned by different CODEOWNERS
  teams, note that in the ticket so it ships as sibling PRs (one per ownership boundary), not one mega-PR.

## Provenance

This ticket (PROJ-368) was itself produced by running this mode by hand: 14 boyscout findings were
filtered, grouped into four themed workstreams, and bundled into one ticket inheriting the team's epic and
components. The procedure above is that flow, made repeatable.
