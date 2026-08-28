# Session lifecycle rules

Use this rule when starting, rolling over, consolidating, or closing session notes in `WIP/SESSIONS/`.

## Source of truth

This file is the canonical procedure for session lifecycle decisions.

- `AGENTS.md` only points agents to this rule.
- `BRAIN.md` defines the conceptual model and folder ownership.
- `JOBS.md` follows the common job structure; execution state is recorded in `JOBS_LOGS.md`. Neither should duplicate this procedure.

## Ownership metadata

| Policy area | Owner | Authority |
|---|---|---|
| state-transitions | RULES-SESSION-LIFECYCLE.common.md | canonical |
| multi-session-coordination | RULES-SESSION-LIFECYCLE.common.md | canonical |
| canonical-open-authority | session_open.py | unique |
| compatibility-fallback | session_bootstrap.py | compatibility-only |
| brain-internal-moves | user | standing-preauthorization |
| other-git-operations | user | explicit-authorization-required |

## Session notes

- Session notes are temporary operational memory stored in `WIP/SESSIONS/`.
- Use date-first filenames with the **full** session id and a topic, for example `YYYY-MM-DD-session-<full-session-id>-topic.md` (e.g. `2026-05-22-session-fb2f1974-7eb1-4dda-9cb2-a26bc4328e30-brain-followup.md`). Always use the full id — never truncate — so the filename matches the resume command verbatim. When the session id is not yet known at creation time, fall back to a unique counter (`-session-01-`, `-session-02-`) and rename in place once the id is resolved (see identification below).
- **Topic field — derive deterministically, never ask**. The topic component of the filename must be derived from observable session signals, in this order:
  1. Explicit session label set via the runtime's rename command (e.g. Claude Code `/rename`), if surfaced to the agent — slugify (`lowercase`, spaces → `-`, drop non-alphanumeric).
  2. Active ticket prefix from the current branch name (`PROJ-307-...` → `proj-307`), when the cwd is a code repo.
  3. Cwd basename (`demo-app`, `org-marketplace`, brain root → `<brain-name>`).
  4. `unspecified-<YYYYMMDD-HHMM>` as last-resort fallback.
  Never block on the topic field via `AskUserQuestion`. The user can rename the file in place if they prefer a different label — that round-trip is cheap; the round-trip to ask is not.
- A session note must use the real session id from the agent runtime (OpenCode, Claude Code, Codex, etc.) in its resume command. It must also record the absolute working directory and provide a paste-ready recovery command that changes to that directory before resuming, because project guidance and runtime configuration depend on the launch directory. Examples: `cd /path/to/project && opencode -s ses_abc123`, `cd /path/to/project && claude --resume <uuid>`, and `cd /path/to/project && codex resume <uuid>`.
- Identify the current session id from inside the running session:
  - **Claude Code**: read the `CLAUDE_CODE_SESSION_ID` environment variable (a UUID like `fb2f1974-7eb1-4dda-9cb2-a26bc4328e30`). This env var is not part of the publicly documented API but is consistently set by the CLI runtime. Fallback if it ever becomes empty: take the basename (minus `.jsonl`) of the newest file under `~/.claude/projects/<encoded-cwd>/`, where `<encoded-cwd>` is the current working directory with both `/` and `.` replaced by `-`. Canonical shell expression: `pwd | tr '/.' '-'`. Examples: `/Users/foo/bar` → `-Users-foo-bar`; `/Users/user/workspace/foo` → `-Users-user-workspace-foo` (the `.` in `jane.smith` must also be substituted, not only the `/`).
  - **OpenCode**: `opencode session list` and pick the active one.
  - **Codex**: read the runtime-provided `CODEX_THREAD_ID` environment variable and resume with `codex resume <uuid>`. The environment variable is observed runtime behavior, not a public API; if it is unavailable, stop rather than inventing an id. Codex also supports `-C` / `--cd`; the shared model emits `cd <cwd> && codex resume <uuid>` so recovery has one uniform shape across runtimes.
  - **Other runtimes**: consult the runtime's own session-listing command; document the equivalent here when known.
- If none of the runtime-specific methods works, leave a clearly-marked placeholder in the session note and the daily's `# Sessions` entry, and ask the user to fill it.
- Track explicit session state in the note: `open`, `handoff-only`, `consolidated`, or `stale-follow-up`.
- A session note should stay short and contain:
  - session state
  - current objective
  - decisions taken
  - working assumptions
  - open questions
  - immediate next step
  - consolidation checklist

## Closing gate

Before moving a previous session note out of `WIP/SESSIONS/`, an agent must verify and record all of the following:

1. Durable state has been preserved in the relevant daily note, WIP note, project note, or `MEMORY/` note.
2. The previous session is not the session currently being resumed or continued.
3. The note is not only a handoff for a still-open same-session rollover.
4. The consolidation checklist is complete, or any unchecked item has an explicit written reason in the new session note or `JOBS_LOGS.md`. Do not trust the checklist's own checkboxes as proof: `session_close.py consolidate` verifies the "Session ID written in daily note" item against the real `JOURNAL/*.md` files on disk and prints `verified` or `WARNING` accordingly — read that line rather than assuming the box was checked correctly.
5. Closed session notes no longer carry the `wip` tag in frontmatter. Keep `session` if useful, but remove `wip` before moving a consolidated note out of `WIP/SESSIONS/`.
6. **Demo-evidence checkpoint**: the agent has asked "did anything demo-worthy happen this session?" and captured it in the ticket's `<slug>.demo-evidence.md` (per `RULES-ISSUE-DOCS.common.md` → "Demo evidence"). Pending visual evidence (a screenshot the user still needs to take) is recorded as an explicit `[PENDING screenshot]` entry rather than dropped.
7. **External draft checkpoint**: for each ticket this session touched, the agent has asked "is there anything worth reflecting in the ticket's comments or an open PR's description?" and captured a draft in `<slug>.external-draft.md` (per `RULES-ISSUE-DOCS.common.md` → "External draft") if so. "Nothing worth drafting" is a valid, recordable outcome — this never blocks closing, it only requires having considered it. The draft is never posted by the agent.
8. **Improvement-detection checkpoint**: if a non-happy-path/improvement-detection skill is available to this session (`boyscout` is the reference example bundled with this repo, but this must never be hardcoded — some installs won't have it), invoke it before finalizing close so it can document improvement opportunities while the session's context is still available. Never install, configure, or substitute one just to satisfy this step — if none is available, it is a no-op.

If any gate is uncertain, leave the note in `WIP/SESSIONS/`, mark it `stale-follow-up`, and report the exact uncertainty. Do not infer closure from age alone.

### Session-close dump: two roles

Closing gate item 1 ("durable state has been preserved") splits into two roles, not one:

- **Drafting the summary is never delegated.** The calling agent is the only one with the full context of what happened this session and why it matters; handing that judgment to a subagent risks losing the exact nuance a compressed instruction can't carry. Draft it — what happened, why it matters — before moving to the next step.
- **Deciding where it goes and how it's formatted is delegated.** Spawn one subagent using the runtime's subagent mechanism when available and permitted by the active instructions; otherwise do this step inline in the parent. Give it the drafted summary and let it decide the destination(s) and exact formatting by reading `BRAIN.common.md`'s "Information Maturity Model", `RULES-DAILY-NOTES.common.md`, and `RULES-FILE-NAMING.common.md` — `MEMORY/` for stable reusable knowledge, `WIP/` for active operational state, the daily note under the matching `# Actions` category otherwise, or a finalised issue working doc per "Consolidation rules" below if a tracker ticket was implemented this session. A single dispatch writing once carries no concurrent-writer risk from this session itself, but the subagent still follows "Multi-session coordination" for any file another session might also be touching (append under a unique heading, never rewrite a section it doesn't own). It reports back exactly which files it touched.

This is the closing-time mirror of source ingestion's own split: there, the router carries only a reference and the subagent carries the domain knowledge needed to investigate; here, the calling agent carries the one thing that can't be delegated (why this session's work matters) and hands off the one thing that can (where this vault's own filing conventions say it belongs).

## Daily note session tracking

Daily note structure (sections `# Actions`, `# Sessions`, work organization by project/context) is defined in `RULES-DAILY-NOTES.md`.

## Flow 1: day change / same session continues

Trigger examples: `nuevo día`, `new day`, `cambio de día`, `cambia de día`, `we changed day`.

Use this flow only when the user is continuing the same working session and the calendar changed.

1. Create today's daily note if it does not exist.
2. **Migrate the previous day's unfinished `* [[TODO]]:` items.** Before cleaning the previous note, review its TODO list with the user (do not move silently — same review-first pattern as the Objectives review in `RULES-DAILY-NOTES.md`): carry unfinished items into today's `* [[TODO]]:`, promote real tasks to `WIP/`/`BACKLOG/` where they belong, and drop done/obsolete ones. This empties the previous TODO so the cleanup in the next step can remove it if it ends up empty.
3. Clean the previous existing daily note by removing empty action categories. **Scope the script to the previous daily** so the current day's fresh note (and other days) are never cleaned — a note may only be cleaned once its date is no longer today (see `RULES-DAILY-NOTES.md` → Cleanup timing): `~/.agents/skills/brain/scripts/cleanup_empty_action_categories.py --brain-root <brain> --glob <prev-date>.md --apply` (e.g. `--glob 2026-05-29.md`). It skips legacy-shape dailies without a `# Actions` section, preserves real content, and removes placeholder-only categories per `TOOL.cleanup-empty-action-categories.md`. **Defer this cleanup if the previous day still has open session notes pending consolidation** (same rule as Flow 2 Scenario B step 3) — empty placeholders are harmless and those sessions' template sections must survive until they consolidate.
4. If there are open session notes from previous days:
   - consolidate their work into the last day the work was actually done;
   - do **not** delete the session note if that same session is continuing;
   - reduce the continuing session note to minimal handoff context.
5. Update the navigation chain between existing daily notes: the nearest previous daily points forward to today, and today points back to it. Keep tomorrow as the provisional forward link until a later daily is created; when a later daily skips dates, replace that provisional link with the new actual neighbor.
6. Do **not** create a new session note; the same session continues.

Handoff-only previous session notes are allowed only in this same-session rollover flow.

## Flow 2: new session

Trigger examples: `nueva sesión`, `new session`, `inicio sesión`, a clearly fresh session context, or simply invoking the connector with no argument.

Guiding principle: **a new session always leaves a session trace, and never lets the day go unstarted.** If today's daily note is missing, starting the session also creates today's note and closes the previous day — this does not require an explicit `nuevo día` instruction. Before the previous day is cleaned, it **consolidates the durable work of previous sessions into its right place** so nothing is lost when the day closes. That consolidation is **State-driven, not blind**: sessions that are clearly finished are consolidated and closed; sessions that may still be live are left untouched and only reported, because a peer session may still be active (see "Previous sessions rollover" below).

The two scenarios differ only by **whether today's daily note already exists** — not by whether the user mentioned a day change.

### Scenario A: today's daily note already exists

The day has already been started, so there is no previous day to close.

1. Create a new session note with the real current session id and a topic derived per the "Topic field — derive deterministically, never ask" rule above. This is the first durable artifact of the session — write it before loading deep brain context, not after.
2. Add the session id or resume command to today's daily note under `# Sessions`.
3. Do not mass-consolidate existing sessions by default. Report the open session notes other than the current one, and run the **"Previous sessions rollover"** below only for sessions the user asks to close, or for clearly stale notes that need it.

### Scenario B: today's daily note does not exist

The day has not been started yet. Start it as part of the session, consolidating previous sessions and closing the previous day in the process.

1. Identify the previous day = the latest existing daily note in `JOURNAL/`.
2. **Run the "Previous sessions rollover"** (below) **first**, so the durable work of finished previous sessions lands in the right daily / `WIP/` / `BACKLOG/` / `MEMORY/` **before** the previous day is cleaned. This is the substance of the old "Scenario C", now run on every day-start (State-driven), not only when the user said `nuevo día`.
3. **Review-first close of the previous day** (never silent):
   - **Migrate the previous day's unfinished `* [[TODO]]:` items** — review the list with the user, carry unfinished items into today's `* [[TODO]]:`, promote real tasks to `WIP/`/`BACKLOG/`, drop done/obsolete ones (per `RULES-DAILY-NOTES.md` → TODO carryover).
   - Run the **Objectives review** pass for the previous day (`RULES-DAILY-NOTES.md` → Objectives review) before any cleanup.
4. Clean the previous daily note by removing empty action categories, **scoped to that single daily** — but **only if that day has no open session note still pending consolidation** (any session the rollover above left live). The cleanup removes only empty placeholders, never real content; still, if a session that worked that day is still open, **defer this cleanup** so its template sections survive until it consolidates. A deferred day is cleaned later — by a later rollover when those sessions close, or by the Daily maintenance job. A note may only be cleaned once its date is no longer today (see `RULES-DAILY-NOTES.md` → Cleanup timing). Command, when it does run: `~/.agents/skills/brain/scripts/cleanup_empty_action_categories.py --brain-root <brain> --glob <prev-date>.md --apply` (e.g. `--glob 2026-06-08.md`).
5. Run `session_open.py --prepare-daily --apply` with the real session id, runtime,
   and cwd. After the review steps above, this one idempotent operation creates today's
   daily from the template, links it reciprocally with the nearest existing daily notes,
   leaves `# Sessions` empty for script ownership, creates or updates the session note,
   and upserts exactly one daily registration. Navigation preparation rolls back all
   touched daily notes if any write fails.
6. Confirm the script's postcondition check passes before adding semantic detail to the
   daily or session note.

The current session trace is mandatory even when daily-note state is incomplete.

### Previous sessions rollover

Shared by Flow 1 and Flow 2. The goal is to **not lose durable work** held in previous session notes, while **never touching a session that may still be active**. It is **State-driven**: decide per note from its `## State` and `## Immediate next step`. Never consolidate or close the session currently being resumed or continued.

**Delegate the read-classify-draft pass; keep every write serial in the calling agent.** Reading a peer session note, deciding whether it's finished, and drafting where its durable content belongs is informative work about the past, not a decision that shapes what the current session does next — a good fit for parallel subagents. Actually writing to `WIP/WIP.md` or a daily note is different: those are shared files another session may also touch, and a concurrent, uncoordinated write to the same file is a real, previously observed failure mode in this vault (a whole `[[TODO]]` section was overwritten once by two sessions writing to it at the same time) — so writes never run in parallel here, regardless of how the reads were parallelized.

For each open session note in `WIP/SESSIONS/` that is **not** the current session (the `open_sessions` list from `session_open.py` is the canonical source; `session_bootstrap.py` is only a compatibility fallback):

1. Spawn one subagent per peer session note using the runtime's subagent mechanism when available and permitted by the active instructions; otherwise process them sequentially in the parent. Each subagent has read-only access — it never edits, moves, or archives anything itself.
2. The subagent reads the note's `## State` and `## Immediate next step` and classifies it:
   - **Clearly finished** — `State` is `consolidated`, `handoff-only`, or `stale-follow-up`, or the immediate next step is "none" / "session closed": it drafts the durable content and its destination, by **the day the work actually happened** (not today) — a daily note for the day the work was done, `WIP/WIP.md` or a project-specific WIP note for active operational state, `BACKLOG/` for real but deferred tasks, `MEMORY/` for stable reusable knowledge, or a finalised issue working doc destined for `MEMORY/Projects/...` if the session implemented a tracker ticket.
   - **Live or ambiguous** — `State` is `open` with a real pending next step, or it cannot tell whether the session is done: it reports this with a one-line reason and drafts nothing. When genuinely unsure, it reports the ambiguity rather than guessing — it never asks the user directly.
3. The calling agent applies every draft from step 2 itself, one at a time: writing the consolidated content to its real destination, moving a finalised issue working doc to `MEMORY/Projects/...` via `git mv` under the bounded standing authorization in `AGENTS.common.md` (per the "Consolidation rules" below), and, once the **Closing gate** above passes, archiving the tracked session note in `QUARANTINE/TRASH/` with `session_close.py --brain-root <brain> --apply consolidate <session-id> --archive` — this internal move needs no separate Git confirmation, but permanent deletion still requires explicit user approval. Notes classified live-or-ambiguous are left untouched in `WIP/SESSIONS/` (respect scope ownership per "Multi-session coordination").
4. Report what was consolidated and closed, and what was left open and why — using the subagents' short summaries, not their full note content, and without re-deciding a classification the subagent already made.

The current session trace is mandatory even when previous sessions are intentionally left open.

## Consolidation rules

- Work belongs to the day it was actually done, not the day when consolidation happens.
- Durable records must describe the state after the approved operation. Do not persist
  planning-only phrases such as "waiting for approval" once approval has been given.
- A completed verification is evidence, not a pending task. Temporary handoff files may
  be used as sources during consolidation but must not become durable references unless
  the user explicitly promotes them.
- Do not duplicate full session transcripts into daily notes; summarize durable progress, decisions, blockers, and next actions.
- Archive fully consolidated, Git-tracked session notes in `QUARANTINE/TRASH/` with `session_close.py --brain-root <brain> --apply consolidate <session-id> --archive` rather than keeping them active. The bounded standing authorization in `AGENTS.common.md` covers this internal `git mv`; report the staged rename. If the note is untracked, consolidate it without `--archive` and report that it could not be moved safely. Permanent deletion requires explicit user approval.
- Before moving a fully consolidated session note out of `WIP/SESSIONS/`, remove the `wip` tag from its frontmatter so closed notes do not appear in active WIP views.
- If preserving a prior session note is necessary, it must be reported as a stale-session follow-up so `WIP/SESSIONS/` does not silently accumulate dead operational notes.
- If the session was implementing a tracker ticket (Jira / GitHub issue / equivalent), its **issue working doc** has been kept current throughout the session per `RULES-ISSUE-DOCS.common.md`. At consolidation time, finalise that doc (update `## Status`, frontmatter `status`, `merged_at` if applicable) and move the folder from `WIP/<project-area>/<repo>/` to `MEMORY/Projects/<project-area>/<repo>/` via `git mv` under the bounded standing authorization in `AGENTS.common.md`. The session note's "durable state preserved outside" closing-gate item is satisfied primarily by the issue working doc, not by the daily note alone.

## Recurring session and WIP review

- Recurring maintenance reviews inspect orphaned or stale session notes that were not fully consolidated. Apply the Closing gate and Previous sessions rollover rules above: consolidate durable work into the day it happened, active WIP, BACKLOG, or MEMORY; leave live or ambiguous sessions untouched and report the reason.
- Recurring maintenance reviews inspect blocked or stale WIP items and decide whether they should remain in active WIP, move to BACKLOG, consolidate to MEMORY, or archive as historically important inactive content under the established information-architecture rules.
- These reviews identify candidates and decisions only. Once a move is semantically justified by the applicable rule, the bounded standing authorization in `AGENTS.common.md` covers its brain-internal `git mv`. The reviews do not authorize peer-scope edits, permanent deletion, or any other Git operation without the explicit user authorization required by the relevant rule.

## Multi-session coordination

Multiple agent sessions may operate against the same brain in parallel (e.g. one session per code repo plus a clean-brain session). Without explicit coordination, sessions can overwrite each other's edits or move artifacts another session is still using. The rules below keep the parallel arrangement safe.

- **Scope ownership**: each session owns the scope it touches. Brain edits scoped to a ticket folder, project subdirectory, or workflow are the exclusive responsibility of the session that started that work. Another session must not edit, move, or consolidate notes inside a peer session's active scope without an explicit handoff request from the user.
- **Shared state files are edited surgically**. `WIP/WIP.md`, today's daily note `JOURNAL/<date>.md`, and any other brain-wide dashboard live in a shared space. Sessions touching them must:
  - append entries under a unique, project-specific heading (per the project-uniqueness rule of daily notes — see `RULES-DAILY-NOTES.common.md`);
  - never rewrite or restructure sections owned by other sessions;
  - never replace an entire shared file in one edit when only a section is theirs.
- **Detect parallel sessions at session start**. Use `session_open.py`'s compact digest. Any session id present and not equal to the current session is a parallel session whose scope must be respected. If only the compatibility fallback is available, `session_bootstrap.py`'s `open_session_notes` list can be used to read each peer note's `## Current objective` and learn its scope.
- **When in doubt, ask the user** which session owns an ambiguous scope. Do not infer from filenames or cwd alone.

This section is referenced by `skills/brain/SKILL.md` → "After brain resolution" so the rule loads at every `brain` connection.
