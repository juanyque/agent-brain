---
name: boyscout
description: "Leave things better than you found them: silently archive improvement opportunities to a backlog during the primary task; the user opts in to attack a finding now (worktree), route it to a ticket, or clean the backlog on demand"
version: 0.11.0
argument-hint: "<optional: 'clean' to manage the backlog, 'deep [days]' for multi-session analysis (default 2 days), 'batch' to work through findings, 'tickets' to convert findings to tickets, 'doctor' for the skill self-test, or comma-separated hints, e.g. 'flaky tests, dead code'>"
allowed-tools:
  - Agent
  - AskUserQuestion
  - Read
  - Write(~/.boyscout/*)
  - Grep
  - Glob
  - Bash(fzf:*, mkdir:*, rm -rf /tmp/boyscout)
  - Bash(python3 scripts/backlog.py:*)
  - Bash(python3 scripts/doctor.py:*)
  - Bash(python3 ~/.agents/skills/brain/scripts/profile_context.py:*)
  - Bash(gh pr view:*)
  - Bash(gh issue view:*)
---

# boyscout

Apply the Boy Scout Rule: leave things better than you found them.

While working on a task, scan the surrounding context for improvement opportunities — flaky tests, broken scripts, missing coverage, dead code, interesting refactors, outdated docs, skill gaps, etc. New findings are silently archived to the backlog so the primary task is not interrupted. When the user explicitly invokes `/boyscout` (or `/boyscout clean` / `/boyscout deep`), present the accumulated findings and let them attack each in an isolated worktree (branched from an up-to-date base branch), route to a detailed ticket, or leave in the backlog for later.

**Golden rule: default to silent archive — never auto-fix without explicit user opt-in.** New findings are added to the backlog without interrupting the primary task. Triage and fixes are opt-in: the user invokes `/boyscout` to see the selection form, or explicitly says "fix item N now" during the scan. When a finding is attacked from the backlog, success consumes the entry (deletes it).

## When to use

Invoke `/boyscout` when you notice opportunities while working on a primary task:
- Flaky or intermittently failing tests
- Scripts that don't behave as expected or are clearly broken
- Refactoring opportunities (extract function, rename, simplify)
- Missing or insufficient test coverage
- Dead code: unused imports, unreachable branches, obsolete flags
- Leftover TODOs or FIXMEs with a clear path forward
- Side tasks uncovered during investigation (e.g. a related bug, a needed migration)
- Outdated or wrong documentation: READMEs, setup guides, inline comments that lie about the code
- Skill gaps: an agent-runtime skill that failed to handle a case, did not cover a scenario, or produced a confusing interaction

Invoke `/boyscout deep` (see [Deep mode](#deep-mode-boyscout-deep-days) below) to analyse the interaction context across recent sessions — repeated instructions, automation opportunities, and promotable flows — not just the codebase.

---

## Workflow

### Step 1 — Identify all opportunities

**1a. Load the backlog.** Load entries with `python3 scripts/backlog.py list --json` (run from the skill dir). If the file doesn't exist, `pending_findings = []`. If `python3 scripts/backlog.py validate` reports problems, fix them first (see Failure modes) — the path is often a symlink, so always mutate via `backlog.py`, never by hand. See [references/backlog.md](references/backlog.md).

**1b. Scan for new opportunities.** Scan the context available (files touched, errors seen, test output, code read) and build `new_findings[]`, up to **10 new findings per run**.

**1c. Dedup.** For each new finding, check if a pending finding already covers it (same `target` + same one-line summary). If a match exists: bump it with `python3 scripts/backlog.py touch --target "<target>" --summary "<summary>"` (updates `last_seen` to today and increments `times_seen`) and drop the new finding. Only `last_seen` and `times_seen` are updated — the new finding's `context` and `how_found` are discarded, so the backlog preserves the *first* detection context only. `times_seen` is the proxy for breadth of impact across sessions.

**1d. Combine.** `all_findings = new_findings + pending_findings`

For each finding, collect the fields in [references/finding-schema.md](references/finding-schema.md): one-line summary, target, location, type, how found, context, estimated effort, risk, and suggested action.

**1e. Resolved sweep.** If `pending_findings` is empty, skip this step. Otherwise, before presenting the selection form, show the pending backlog entries numbered locally (1, 2, 3… — Step 2 assigns fresh global numbers after any removals), then ask the user: *"Any backlog entries you know are already resolved? Enter numbers to remove before we continue."* Remove the selected entries from `all_findings` and delete their blocks with `python3 scripts/backlog.py remove --target "<target>" --summary "<summary>"`. This zero-effort prompt prevents stale entries from accumulating across sessions.

**Verification before dropping `flaky-test` / `test-isolation` findings.** Source-only inspection is insufficient for these types. Before removing one as resolved (here or in clean mode), reproduce the original verification boundary and require it to pass (for example, the relevant module check). A finding that still reproduces stays in the backlog.

### Step 2 — Present the selection form

Launch `fzf` multi-select with per-finding detail previews, grouped by `target`. If `fzf` fails, fall back to `AskUserQuestion` with a numbered list. The exact command, temp-file layout, grouping format, and freshness indicators (`[NEW]`, `[PENDING · date · ×N]`, `[STALE?]`) are in [references/selection-ui.md](references/selection-ui.md).

**Staleness:** findings with `last_seen` > 7 days ago are marked `[STALE?]`. To remove stale findings from the backlog, use `/boyscout clean`.

Never proceed past this step without an explicit user selection.

### Step 3 — Decide action per finding

**Default per finding: keep in / add to backlog** (no decision pressure during triage). Two opt-in paths override the default:

- **Attack now** — fix immediately in a worktree (or in an existing PR branch — see special case below). On success, the corresponding backlog entry is **consumed** (deleted). See Step 4A.
- **Create ticket** — route to a ticket when the finding is too large or risky for in-line fix. Ticketed findings also leave the backlog (ticket tracker is source of truth). See Step 4B.

The attack-now path is recommended when:

- User explicitly says *"fix item N now"* / *"attack 3"* / similar.
- Finding has `effort: XS` AND `confidence: high` AND it is in-scope of the active task (continuing the session is cheaper than backlogging + re-loading context later).

**`confidence: low` blocks auto-fix.** If a finding has `confidence: low`, never propose attack-now — the proposed action may be speculative or could plausibly make things worse. Ask the user to discuss diagnosis first, not the fix.

**Special case — in-review PR.** If a finding targets a file already modified in an open PR currently under review (detected from session context — e.g. running `/boyscout` mid-review — or by asking the user), the attack-now variant becomes **"Fix in existing PR branch"** instead of a new worktree. This avoids a separate PR for a one-line follow-up. See the "Fixing into the PR currently under review" section of [references/worktree-playbook.md](references/worktree-playbook.md) for the exact commands. If the PR is not `OPEN`, fall back to the worktree variant.

**Decision matrix.** Use the suggested-action table in [references/finding-schema.md](references/finding-schema.md) § "Triage decision matrix (Step 3)" to map (effort, risk, impact, confidence) → attack-now / ticket / backlog. Key rows: `XS/S · low · high · high` → attack now; `M/L` (any) → ticket; `confidence: low` (any) → never auto-fix, discuss diagnosis first. When ambiguous, ask explicitly surfacing all four dimensions.

**Before spawning any subagents for attack-now or ticketing, show a confirmation summary:**

```
Ready to act on N items:
  → Attack now (worktree, consume on success):  items 1, 3
  → Attack now (existing PR branch):            items X
  → Create ticket:                              items 2, 4
  → Keep in backlog (no change):                items 5

Proceed?
```

Wait for explicit confirmation before doing anything.

### Step 4A — Attack now (isolated worktree)

Fix each selected item in an isolated worktree on a branch from the up-to-date base. See [references/worktree-playbook.md](references/worktree-playbook.md) for the exact commands, the `skill-gap` variant (different repo, no worktree), and the "fix into the PR currently under review" variant.

**Multi-finding targets:** When multiple selected findings share the same `target` key, pass them all to a single subagent — all fixes go in one branch and one PR. Inform the user: "Items X and Y share target `<repo> / <component>` — they will be fixed together in one PR."

**Consume on success.** After a fix lands successfully (PR opened, or commit pushed to existing PR), delete the corresponding entry from `~/.boyscout/backlog.md`. This is the "consume on attack" pattern — attack-now turns a pending backlog entry into resolved state, removing the entry rather than leaving it stale. See [references/backlog.md](references/backlog.md) § "Consume on attack" for the surgical-edit rules. If the attack started from a `new` finding (never written to the backlog), no removal is needed.

### Step 4B — Create ticket

Resolve the ticket capabilities before choosing a backend. If the current session is already
connected to a brain containing `_AGENTS/SHARED/environment.json`, run the public resolver for
the active runtime (the calling agent knows its runtime):

```bash
python3 ~/.agents/skills/brain/scripts/profile_context.py \
  --brain-root "<brain-root>" \
  --cwd "$PWD" \
  --runtime <claude|codex|opencode|generic> \
  --include-policy \
  --capability issues.create \
  --capability issues.read \
  --capability issues.search \
  --capability issues.update
```

Add `--live` for Codex registry/auth discovery. Do not add it for Claude: its official MCP list
command may rewrite runtime settings even when used as a health check. In Claude, resolve without
`--live` and use the active tool catalog as the readiness gate. When the agent can enumerate the
complete catalog, append one `--available-tool <exact-name>` argument per exposed tool plus
`--tool-catalog-complete`; resolution then fails if the selected MCP invocation is absent.

The resolver returns sanitized JSON containing the selected profile, provider, abstract
operation, readiness, and a runtime invocation hint. It never returns credentials, endpoints,
or raw runtime configuration.

- Treat `invocation` as an adapter hint. A complete caller-supplied catalog verifies exact active
  exposure; otherwise `tool_exposure` remains `unverified` and the caller must check it before use.
  Registry presence alone is insufficient.
- Public skill frontmatter intentionally does not pre-authorize provider-specific external writes.
  The resolved invocation must use the runtime's normal consent flow. Future private overlays may
  grant narrower environment-specific permissions without changing this public skill.
- Use the provider `service` to choose the matching backend reference below. Do not infer a
  different backend from branch naming after the profile selected one.
- Use returned `issue_tracking` policy for project detection, defaults, parent resolution, and
  content language. Explicit user/project instructions still take precedence.
- If live discovery or a required capability fails, leave the finding in the backlog and report
  the missing provider/auth/tool state. Never silently switch ticket trackers.
- If no brain/profile is active, preserve the portable fallback: GitHub Issues via `gh`, with
  explicit user selection when project/backend context is ambiguous.

Then determine project context:

1. **Current branch matches a selected profile `branch_patterns` entry:** use the captured issue/project context.
2. **cwd is a git repo but branch has no ticket prefix:** ask the user *"No ticket context detected. Which project should host this ticket?"*
3. **cwd is not a git repo, OR finding type is `skill-gap`:** ask the user for the target repo/project.

Then create using the appropriate backend:
- **GitHub Issues (default):** see [references/ticket-github.md](references/ticket-github.md) — uses `gh issue create`.
- **Jira:** see [references/ticket-jira.md](references/ticket-jira.md) — requires a resolved and exposed Jira MCP operation.
- **GitLab Issues:** see [references/ticket-gitlab.md](references/ticket-gitlab.md) — uses `glab issue create`.

Use the body format in [references/ticket-template.md](references/ticket-template.md) regardless of backend.

### Post-action — Update the backlog

After all actions complete, apply every backlog change through `python3 scripts/backlog.py` — it owns the file format, so no hand-editing (the path is often a symlink the harness can't `Edit`/`Write` through, and prose surgical-edits are what once orphaned an entry). See [references/backlog.md](references/backlog.md) for the format the script implements.

1. `mkdir -p ~/.boyscout` if it doesn't exist (`backlog.py add` does this on first write).
2. **Attacked findings (PR landed)** → `backlog.py remove --target … --summary …` — consume-on-success pattern.
3. **Ticketed findings** → `backlog.py remove …` (ticket tracker is source of truth).
4. **New findings not attacked or ticketed** → `backlog.py add --target … --summary … --type … --effort … --risk … --impact … --confidence … --context … --how-found … --action …` (defaults `status: pending`, today's `detected`/`last_seen`, `times_seen: 1`). This is the **default path** for any finding the user did not explicitly attack or ticket.
5. **Pending findings the user explicitly left in the backlog** → leave as-is (no change).
6. **Dedup-updated findings** (already bumped via `backlog.py touch` in Step 1c) → nothing more to do.

Run `python3 scripts/backlog.py validate` after the batch to confirm the file is still well-formed.

**Backward compatibility.** Legacy pending entries without `impact` / `confidence` remain valid; treat missing fields as `medium` for the matrix and never auto-fix without confirming the missing dimensions first. Full rules in [references/backlog.md](references/backlog.md) § "Backward compatibility".

---

## Clean mode (`/boyscout clean`)

When invoked as `/boyscout clean`, skip the normal scan and enter backlog management mode.

1. **Load the backlog.** Read `~/.boyscout/backlog.md`. If empty or missing, print "Backlog is empty." and stop.
2. **Present the deletion form.** Show all backlog findings in the same grouped selection UI (see [references/selection-ui.md](references/selection-ui.md)), with prompt: `"Select findings to remove from the backlog >"`.
3. **Confirm.** List the selected findings and ask: `"Remove these N findings from the backlog? (yes / no)"`
4. **Remove.** On confirmation, delete each selected finding with `python3 scripts/backlog.py remove --target … --summary …` and print a summary of what was removed.

The normal fix/ticket workflow is not invoked in clean mode — selected findings are only deleted from the backlog.

`/boyscout clean` is also the place to drain stale entries in bulk: `python3 scripts/backlog.py sweep --days 7` lists everything older than the staleness window, and `--remove` deletes them after you confirm.

---

## Deep mode (`/boyscout deep [days]`)

When invoked as `/boyscout deep`, skip the normal codebase scan and analyse the **interaction context** of recent sessions instead — repeated instructions, deterministic ceremonies the agent ran by hand, and ad-hoc flows worth promoting to a skill. It replaces Step 1b with three isolated detector passes (parallel when the runtime and active instructions permit it), then rejoins the main workflow at Step 1c (dedup). Default window 2 days; `/boyscout deep 7` widens it. Mutually exclusive with `clean`.

The full workflow (D1–D6), the closed source list, the PII / untrusted-transcript guardrail, target namespaces, and deep-mode verification live in [references/deep-mode.md](references/deep-mode.md) — loaded only on `/boyscout deep`.

---

## Doctor mode (`/boyscout doctor`)

When invoked as `/boyscout doctor`, run the skill's self-test and report — no scan, no backlog mutation:

```bash
python3 scripts/doctor.py
```

It asserts: every `references/*.md` named in the Dependencies table exists and is non-empty; the deep-mode types in `finding-schema.md` each have a matching `detection-*.md` brief (and vice-versa); the backlog (if present) passes `backlog.py validate`; and `deep-mode.md`'s D4 fan-out links every detection brief. Exits non-zero on any failure, so it doubles as the pre-PR gate when changing boyscout itself. Pass `--backlog <path>` to check a specific backlog file.

---

## Batch-implement mode (`/boyscout batch`)

When invoked as `/boyscout batch` (or `/boyscout implement`), work through several selected backlog findings in one guided sitting: explain each in plain language → ask **implement / skip / defer / convert-to-ticket** per item → implement in logical batches (one commit per coherent change, same `target` → same PR) → pause-and-verify before each commit → prune consumed findings from the backlog *after* each commit. The full procedure and pitfalls are in [references/batch-implement-playbook.md](references/batch-implement-playbook.md). Worktree mechanics come from [references/worktree-playbook.md](references/worktree-playbook.md); a batch must never mix CODEOWNERS boundaries.

---

## Backlog → Tickets mode (`/boyscout tickets`)

When invoked as `/boyscout tickets`, convert an aged/themed slice of the backlog into tracked tickets: filter candidates (by target, age via `backlog.py sweep`, dedup via `backlog.py dedup-check`) → propose theme groupings (`AskUserQuestion`) → accept a template ticket URL/key and inherit its epic/labels/components → create the epic + child tickets → prune consumed findings → summarise with ticket URLs. The full procedure is in [references/backlog-to-tickets.md](references/backlog-to-tickets.md).

---

## Resumability

`/boyscout` mutates state across step boundaries, so a run interrupted mid-flow can be re-entered safely once you know what each phase touched:

- **Step 1c (dedup)** mutates only `last_seen` / `times_seen` on existing backlog entries, and only in memory until Post-action writes them. Re-running a fully-completed run bumps `times_seen` again — re-apply a dedup only if the earlier attempt did not reach Post-action.
- **Step 4A (attack now)** creates a branch + worktree + PR per target. Safe to re-run: the worktree playbook checks for an existing branch/worktree before creating. A backlog entry is consumed (deleted) only *after* its PR is opened.
- **Step 4B (create ticket)** calls the ticket backend, then removes the entry from the backlog. If the run dies between ticket creation and backlog removal, the next run still sees the entry and could re-ticket it (duplicate) — see Failure modes. On resume, remove the consumed entry first.
- **Post-action** is the only phase that writes the backlog file. Until it runs, the backlog on disk is unchanged from session start.

## Failure modes

- **Backlog file malformed** (e.g. a `- status:` block whose `###` heading was lost — the corruption that motivated the tooling work): do not guess the structure. Run `scripts/backlog.py validate` to locate the broken block, then fix it before any other mutation.
- **Ticket backend unavailable** (profile resolution, live registry/auth, active tool exposure, `gh`/`glab`, or provider call failure): Step 4B cannot create tickets. Leave the finding in the backlog and report the exact failed boundary — never silently drop or reroute a finding meant to be ticketed.
- **`fzf` installed but no TTY** (non-interactive shell, piped invocation): the multi-select cannot render. Fall back to `AskUserQuestion` with a numbered list (the Step 2 fallback).
- **Partial state on ticket creation** (ticket creation succeeds but the Post-action backlog removal fails): the entry is still present, so a naive retry creates a *duplicate* ticket. On resume, remove the already-ticketed entry before re-running Step 4B and confirm in the ticket tracker that no duplicate exists.

---

## How to verify

Run `/boyscout` in a repo with known issues and confirm:
- On explicit invocation (`/boyscout`, `/boyscout clean`, or `/boyscout deep`), the selection form appears grouped by `target` before any action is taken; during a passive scan triggered while working on another task, new findings are silently archived to the backlog without surfacing a form.
- Fixes produce a new branch in an isolated worktree, not changes in the current working tree
- Multiple findings with the same target produce a single PR
- Ticketed items appear in the ticket tracker with all context fields populated
- An attack-now on a `pending` backlog entry that lands successfully removes the entry (consume-on-attack); failed attacks leave the entry intact.
- Step 4B resolves profile-backed `issues.*` capabilities before backend/project selection; live provider failure preserves the backlog entry, while the no-profile fallback asks for explicit backend/project context when ambiguous
- Skipped new findings appear in `~/.boyscout/backlog.md` after the run
- Re-running boyscout after a skip increments `times_seen` for the re-detected finding (no duplicate entry)
- Running `/boyscout clean` shows the full backlog grouped by target; selecting findings and confirming removes them

For deep mode, see the verification checklist in [references/deep-mode.md](references/deep-mode.md).

---

## Dependencies

Required files in `references/`. Read each file when first referenced by a step.
If any file cannot be read, stop immediately and tell the user:
`Reference file references/<name>.md is missing — reinstall the skill .`

| File | Step | Load |
|------|------|------|
| `references/finding-schema.md` | Step 1, Deep mode | always |
| `references/selection-ui.md` | Step 2 | always |
| `references/worktree-playbook.md` | Step 4A | always |
| `references/ticket-template.md` | Step 4B | always |
| `references/backlog.md` | Step 1, Post-action | always |
| `references/deep-mode.md` | Deep mode | conditional — only on `/boyscout deep` |
| `references/batch-implement-playbook.md` | Batch-implement mode | conditional — only on `/boyscout batch` |
| `references/backlog-to-tickets.md` | Backlog → Tickets mode | conditional — only on `/boyscout tickets` |

`references/deep-mode.md` in turn loads `deep-sources.md`, `runtimes.md`, and the three `detection-*.md` detector briefs — only on `/boyscout deep`.

Deterministic helpers live in `scripts/` (`backlog.py`, `doctor.py`) — invoked by the steps above, not "loaded".

---

## Notes

- Never interrupt or block the primary task.
- All fixes happen in worktrees or separate repos — never in the current working tree.
- Prefer a ticket over a fix when uncertain. A tracked item is better than an unreviewed change.
- Keep each subagent scope minimal: one finding, one fix, one commit.
- Sub-agents spawned via `Agent` receive the session's tool permissions — they are **not** limited by this skill's `allowed-tools`. Mitigate: brief each subagent to the minimal task and the specific files it may touch; never delegate a destructive operation without an `AskUserQuestion` gate first; never pass a user-controlled or transcript-derived path into a `Bash` command.
- All ticket content must be in English, regardless of conversation language.
