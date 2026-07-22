# Batch-implement mode

Loaded when `/boyscout` is invoked as `/boyscout batch` (or `/boyscout implement`). Use it to work
through several backlog findings in one guided sitting — explaining each in plain language, deciding
per item, implementing, verifying, and pruning the backlog as work lands. It is the multi-finding
counterpart to the single-finding attack-now path (Step 4A); the worktree mechanics still come from
[worktree-playbook.md](worktree-playbook.md).

## When to use

- The backlog has accumulated several findings against the **same repo / area** and you want to clear
  a batch rather than ticket them.
- A focused "let's clean these up" session, as opposed to the passive scan or the one-off attack-now.

If the findings span unrelated repos/owners, prefer [Backlog → Tickets mode](backlog-to-tickets.md) — a
single PR must not mix ownership boundaries (one PR per CODEOWNERS team).

## Workflow

**B1. Load + select.** Load the backlog (`backlog.py list --json`), present the grouped selection UI
(see [selection-ui.md](selection-ui.md)), and let the user pick the findings to work through. Validate
first (`backlog.py validate`) so a corrupt file is fixed before any work starts.

**B2. Explain each selected finding in plain language.** For every selected item, before touching code,
state in one or two sentences: what it is, why it matters, and the proposed change. No jargon dump — the
user is deciding, so give them what they need to decide.

**B3. Decide per item.** Ask once per finding (batch the questions with `AskUserQuestion` when several
share context). Four outcomes:

| Choice | Effect |
|--------|--------|
| **Implement** | Fix it now in this session's branch (see B4). |
| **Skip** | Leave in backlog unchanged. |
| **Defer** | Leave in backlog; note it was reviewed (bump `last_seen` via `backlog.py touch` so it doesn't read as stale). |
| **Convert to ticket** | Route to Jira (Step 4B / [ticket-template.md](ticket-template.md)); then `backlog.py remove`. |

**B4. Group into logical batches.** Findings sharing a `target` (or that naturally belong in one
reviewable change) form one commit. Implement a batch in an isolated worktree on a single branch from
an up-to-date base (worktree-playbook.md). Keep each commit coherent — a reviewer should be able to read
it as one idea.

**B5. Pause-and-verify after each batch.** Run the relevant check before committing — tests / linter for
code, `doctor.py` + `backlog.py validate` for skill changes, the module check for `flaky-test` /
`test-isolation` findings (source-only is not enough). Show the result. Do not proceed to the next batch
on a red check.

**B6. Commit per logical batch, then prune.** Commit the batch, then immediately remove the consumed
findings from the backlog with `backlog.py remove --target … --summary …` — prune *after each commit*,
not at the very end, so an interrupted session leaves the backlog consistent with what actually landed.

**B7. End-of-run summary.** List what was implemented (with commit/PR refs), what was skipped/deferred,
and what was ticketed (with URLs).

## Pitfalls

- **Don't bundle across ownership.** One PR per CODEOWNERS boundary. If selected findings cross repos or
  owners, split into separate branches/PRs (or switch to Backlog → Tickets mode).
- **Don't prune before the commit lands.** Consume-on-success: a finding leaves the backlog only after its
  change is committed (and pushed, if a PR is opened). A failed batch leaves its findings intact.
- **Don't skip the per-item explanation.** The value of batch mode over a silent bulk-fix is that the user
  approves each change with enough context to catch a bad call early.
- **`confidence: low` findings are not eligible for Implement** — discuss diagnosis first (same rule as the
  Step 3 decision matrix).

## Provenance

This procedure was refined through repeated real-world runs and is kept provider-neutral so it can
be reused without exposing environment-specific tickets or organizational context.
