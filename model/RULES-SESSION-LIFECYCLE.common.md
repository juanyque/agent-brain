# Session lifecycle rules

Use this rule when starting, rolling over, consolidating, or closing session notes in `WIP/SESSIONS/`.

## Source of truth

This file is the canonical procedure for session lifecycle decisions.

- `AGENTS.md` only points agents to this rule.
- `BRAIN.md` defines the conceptual model and folder ownership.
- `JOBS.md` follows the common job structure; execution state is recorded in `JOBS_LOGS.md`. Neither should duplicate this procedure.

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
4. The consolidation checklist is complete, or any unchecked item has an explicit written reason in the new session note or `JOBS_LOGS.md`.
5. Closed session notes no longer carry the `wip` tag in frontmatter. Keep `session` if useful, but remove `wip` before moving a consolidated note out of `WIP/SESSIONS/`.
6. **Demo-evidence checkpoint**: the agent has asked "did anything demo-worthy happen this session?" and captured it in the ticket's `<slug>.demo-evidence.md` (per `RULES-ISSUE-DOCS.common.md` → "Demo evidence"). Pending visual evidence (a screenshot the user still needs to take) is recorded as an explicit `[PENDING screenshot]` entry rather than dropped.

If any gate is uncertain, leave the note in `WIP/SESSIONS/`, mark it `stale-follow-up`, and report the exact uncertainty. Do not infer closure from age alone.

## Daily note session tracking

Daily note structure (sections `# Actions`, `# Sessions`, work organization by project/context) is defined in `RULES-DAILY-NOTES.md`.

## Flow 1: day change / same session continues

Trigger examples: `nuevo día`, `new day`, `cambio de día`, `cambia de día`, `we changed day`.

Use this flow only when the user is continuing the same working session and the calendar changed.

1. Create today's daily note if it does not exist.
2. **Migrate the previous day's unfinished `* [[TODO]]:` items.** Before cleaning the previous note, review its TODO list with the user (do not move silently — same review-first pattern as the Objectives review in `RULES-DAILY-NOTES.md`): carry unfinished items into today's `* [[TODO]]:`, promote real tasks to `WIP/`/`BACKLOG/` where they belong, and drop done/obsolete ones. This empties the previous TODO so the cleanup in the next step can remove it if it ends up empty.
3. Clean the previous existing daily note by removing empty action categories. **Scope the script to the previous daily** so the current day's fresh note (and other days) are never cleaned — a note may only be cleaned once its date is no longer today (see `RULES-DAILY-NOTES.md` → Cleanup timing): `_COMMON/SKILLS/obsidian/scripts/cleanup_empty_action_categories.py --brain-root <brain> --glob <prev-date>.md --apply` (e.g. `--glob 2026-05-29.md`). It skips legacy-shape dailies without a `# Actions` section, preserves real content, and removes placeholder-only categories per `TOOL.cleanup-empty-action-categories.common.md`. **Defer this cleanup if the previous day still has open session notes pending consolidation** (same rule as Flow 2 Scenario B step 3) — empty placeholders are harmless and those sessions' template sections must survive until they consolidate.
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
4. Clean the previous daily note by removing empty action categories, **scoped to that single daily** — but **only if that day has no open session note still pending consolidation** (any session the rollover above left live). The cleanup removes only empty placeholders, never real content; still, if a session that worked that day is still open, **defer this cleanup** so its template sections survive until it consolidates. A deferred day is cleaned later — by a later rollover when those sessions close, or by the Daily maintenance job. A note may only be cleaned once its date is no longer today (see `RULES-DAILY-NOTES.md` → Cleanup timing). Command, when it does run: `_COMMON/SKILLS/obsidian/scripts/cleanup_empty_action_categories.py --brain-root <brain> --glob <prev-date>.md --apply` (e.g. `--glob 2026-06-08.md`).
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

For each open session note in `WIP/SESSIONS/` that is **not** the current session (the `open_session_notes` list from `session_bootstrap.py` is the canonical source):

1. Read its `## State` and `## Immediate next step`.
2. **If it is clearly finished** — `State` is `consolidated`, `handoff-only`, or `stale-follow-up`, or the immediate next step is "none" / "session closed" — consolidate its durable content into the right place, by **the day the work actually happened** (not today):
   - daily notes for the days when the work was done;
   - `WIP/WIP.md` or project-specific WIP notes for active operational state;
   - `BACKLOG/` for real but deferred tasks;
   - `MEMORY/` for stable reusable knowledge.
   If the session implemented a tracker ticket, finalise its issue working doc and `git mv` it to `MEMORY/Projects/...` per the "Consolidation rules" below. Then, once the **Closing gate** above passes, move the session note to `QUARANTINE/TRASH/` (permanent deletion still requires explicit user approval).
3. **If it is live or ambiguous** — `State` is `open` with a real pending next step, or you cannot tell whether it is done — **leave it untouched** in `WIP/SESSIONS/` (do not consolidate, edit, or move it — respect scope ownership per "Multi-session coordination"), record a stale-session follow-up only if it needs later maintenance, and report it. When unsure, ask the user rather than guessing.
4. Report what was consolidated and closed, and what was left open and why.

The current session trace is mandatory even when previous sessions are intentionally left open.

## Consolidation rules

- Work belongs to the day it was actually done, not the day when consolidation happens.
- Durable records must describe the state after the approved operation. Do not persist
  planning-only phrases such as "waiting for approval" once approval has been given.
- A completed verification is evidence, not a pending task. Temporary handoff files may
  be used as sources during consolidation but must not become durable references unless
  the user explicitly promotes them.
- Do not duplicate full session transcripts into daily notes; summarize durable progress, decisions, blockers, and next actions.
- Prefer moving fully consolidated session notes to `QUARANTINE/TRASH/` for reversible cleanup rather than keeping them active. Permanent deletion requires explicit user approval.
- Before moving a fully consolidated session note out of `WIP/SESSIONS/`, remove the `wip` tag from its frontmatter so closed notes do not appear in active WIP views.
- If preserving a prior session note is necessary, it must be reported as a stale-session follow-up so `WIP/SESSIONS/` does not silently accumulate dead operational notes.
- If the session was implementing a tracker ticket (Jira / GitHub issue / equivalent), its **issue working doc** has been kept current throughout the session per `RULES-ISSUE-DOCS.common.md`. At consolidation time, finalise that doc (update `## Status`, frontmatter `status`, `merged_at` if applicable) and move the folder from `WIP/<project-area>/<repo>/` to `MEMORY/Projects/<project-area>/<repo>/` via `git mv`. The session note's "durable state preserved outside" closing-gate item is satisfied primarily by the issue working doc, not by the daily note alone.

## Multi-session coordination

Multiple agent sessions may operate against the same brain in parallel (e.g. one session per code repo plus a clean-brain session). Without explicit coordination, sessions can overwrite each other's edits or move artifacts another session is still using. The rules below keep the parallel arrangement safe.

- **Scope ownership**: each session owns the scope it touches. Brain edits scoped to a ticket folder, project subdirectory, or workflow are the exclusive responsibility of the session that started that work. Another session must not edit, move, or consolidate notes inside a peer session's active scope without an explicit handoff request from the user.
- **Shared state files are edited surgically**. `WIP/WIP.md`, today's daily note `JOURNAL/<date>.md`, and any other brain-wide dashboard live in a shared space. Sessions touching them must:
  - append entries under a unique, project-specific heading (per the project-uniqueness rule of daily notes — see `RULES-DAILY-NOTES.common.md`);
  - never rewrite or restructure sections owned by other sessions;
  - never replace an entire shared file in one edit when only a section is theirs.
- **Detect parallel sessions at session start**. After loading brain context, scan today's daily note `# Sessions` block. Any session id present and not equal to the current session is a parallel session whose scope must be respected. If `session_bootstrap.py` is available, its `open_session_notes` list is the canonical source — read each peer note's `## Current objective` to learn its scope.
- **When in doubt, ask the user** which session owns an ambiguous scope. Do not infer from filenames or cwd alone.

This section is referenced by `SKILL.obsidian.common.md` → "After brain resolution" so the rule loads at every `/obsidian` connection.
