---
name: brain
description: >
  Connect the current session to a brain for reading context and documenting activity.
  Use when the user asks to document work in the brain, connect to it, or log progress
  to their second brain. Triggers: "document in brain", "connect to brain", "log to brain",
  "update my brain", "brain", or any reference to documenting activity in the user's brain.
allowed-tools:
  - Read
  - Edit
  - Write
  - Glob
  - Grep
  - AskUserQuestion
  - Bash(python3:*, git mv:*, mkdir:*)
metadata:
  short-description: Connect to a notes brain and document activity
---

# Brain Connector

Connect the current session to a notes brain, load its operating model, and document session activity there. Obsidian vaults are supported, but Obsidian is not required.

## Invocation routing

- No arguments, `session`, `nueva sesión`, `new session`, `inicio sesión`, `connect`, or `start` → run the session-start protocol: resolve the brain, run `session_open.py` (see "After brain resolution"), consume the compact digest, and follow Flow 2 (`new session`) for the detected scenario. Flow 2 creates today's daily note when it is missing — first consolidating the durable work of clearly-finished previous sessions (State-driven rollover), then closing the previous day. Starting the day is part of session start and does **not** require an explicit `nuevo día` instruction.
- `new-day`, `nuevo día`, `cambio de día`, `cambia de día`, or `we changed day` → run the day-rollover protocol. Resolve the brain, run `session_open.py` (day_rollover_detected will be `yes`), load `RULES-SESSION-LIFECYCLE.md`, and follow Flow 1 (`day change / same session continues`). Do not create a new session note in this flow.
- `close session`, `cerrar sesión`, `cerramos la sesión`, `wrap up`, `end session`, `consolidate`, or `consolidar` → run the session-close protocol: resolve the brain, load `RULES-SESSION-LIFECYCLE.md` (Closing gate + Consolidation rules), then run `session_close.py` (see "Available skill tools"). For a handoff: `session_close.py handoff <session-id> --apply`. For full consolidation: `session_close.py consolidate <session-id> [--archive] --apply`. Objectives review is required before consolidation (see `RULES-DAILY-NOTES.md`).

Do not run broad brain maintenance, standardization, or semantic reorganization from a no-argument/session-start invocation. Those require explicit arguments such as `maintain`, `clean`, `order`, `standardize`, or `init`. Exception: when today's daily note is missing, Flow 2 finalises the **previous** day (review-first TODO carry-over and Objectives review, then empty-category cleanup scoped to that single previous daily) and creates today's note. That per-day rollover is part of session start; the restriction here is about brain-wide maintenance, not the previous-day rollover.

## Prerequisites

- Python 3.x (stdlib only — scripts have no external dependencies).
- `git` on PATH (used for `git mv` during brain reorganization).
- A notes brain to connect to.
- The `brain` skill installed by the agent-brain bootstrap. Codex discovers the user skill at `~/.agents/skills/brain`; Claude uses `~/.claude/skills/brain`.

> **Runtime path note:** command examples use `~/.agents/skills/brain/scripts/...`, the Codex user-skill location. In another runtime, use its installed `brain/scripts/` path, such as `~/.claude/skills/brain/scripts/`.

## Brain resolution

Run the discovery script first. It handles all deterministic path logic:

```bash
python3 ~/.agents/skills/brain/scripts/find_home.py [path]
```

The script returns JSON. Handle each outcome:

**1 brain found** → use it directly, proceed to loading context.

**Multiple brains found** → check for nested brains. Each brain object includes:
- `has_agents_md` / `has_brain_md`: true if the brain has operational docs
- `is_nested` / `parent_brain`: indicates this brain lives inside another found brain

If one brain has `has_agents_md: true` and others do not, prefer the one with operational docs. If still ambiguous, present the list to the user and ask them to pick.

**No brains found** → tell the user no brain was found and ask them to provide the brain path manually. Then run the script again with that path.

**Error (path does not exist)** → report the error and ask for a valid path.

## After brain resolution

Once a brain path is confirmed, run `session_open.py` to load context and prepare the session in one call.

Run `session_open.py` immediately after resolution. Do not pre-read the brain's `AGENTS.md`,
`BRAIN.md`, `WIP/WIP.md`, `TASK_TYPES/TASK_TYPES.md`, or their `_COMMON/*.common.md`
sources; global runtime instructions are already loaded and the compact digest is the intended
entrypoint.

**Resolve the real session id and runtime BEFORE invoking the script** — never pass a timestamp fallback and never let the script guess a wrong runtime. The calling agent always knows its own runtime:

| Runtime | Resolve session id | Pass `--runtime` |
|---|---|---|
| Claude Code | read `$CLAUDE_CODE_SESSION_ID` | `--runtime claude` (or omit; auto-detected via env) |
| OpenCode | run `opencode session list`, pick the active session | `--runtime opencode` (**required** — no env var) |
| Codex | read `$CODEX_THREAD_ID` (runtime-provided; not a public API) | `--runtime codex` |
| Other | consult the runtime's session-listing command | `--runtime generic` |

If you cannot resolve the real id, **stop and ask the user** rather than inventing one.

```bash
python3 ~/.agents/skills/brain/scripts/session_open.py \
  --brain-root "<brain_path>" \
  --session-id "<REAL session id from your runtime>" \
  --runtime <claude|opencode|codex> \
  --session-label '<label from /rename, or empty>' \
  --cwd "$(pwd)"
```

The `--runtime` flag controls the resume-command format emitted in the session note and the daily `# Sessions` entry (`opencode -s <id>`, `claude --resume <id>`, `codex resume <id>`, etc.). The supplied `--cwd` is recorded and prefixed as `cd <cwd> && ...`, because runtime configuration and project guidance are resolved from the launch directory. If `--runtime` is omitted, the script falls back to `detect_runtime()` (Claude only, via env); any unknown runtime emits a bare session id so a wrong runtime is never silently claimed.

The script emits a compact digest (~20-30 lines): brain state, today's daily info, open sessions list, WIP items filtered by cwd, TASK_TYPES one-liners, and any warnings. **Do not additionally read `AGENTS.md`, `BRAIN.md`, `WIP/WIP.md`, or `TASK_TYPES/TASK_TYPES.md` — the digest is the only brain context the main agent needs.**

After reviewing the digest, announce to the user that the brain is connected and briefly summarize active context.

After the user acknowledges the digest (or when the session open is routine), pass `--apply` to create the session note and idempotently register it in today's daily `# Sessions` block:

```bash
python3 ~/.agents/skills/brain/scripts/session_open.py \
  --brain-root "<brain_path>" \
  --session-id "<REAL session id>" \
  --runtime <claude|opencode|codex> \
  --session-label '<label>' \
  --cwd "$(pwd)" \
  --apply
```

`--apply` is safe to repeat: the script upserts by full session id, preserves a user-edited
daily summary, removes known `# Sessions` template scaffold, and verifies that the session
note and daily contain one canonical recovery command.

**Day rollover**: if the digest reports `day_rollover_detected: yes`, load the brain-local `RULES-SESSION-LIFECYCLE.md` when present, otherwise `_COMMON/RULES-SESSION-LIFECYCLE.common.md`, and run the semantic review in Flow 1 / Flow 2 Scenario B first. When that review is complete, run `session_open.py --prepare-daily --apply` once. `--prepare-daily` instantiates navigation and leaves `# Sessions` empty before the same command performs the idempotent registration. It refuses divergent local/common daily templates instead of choosing one silently.

**If the brain has no operational files** (`AGENTS.md`, `BRAIN.md` all missing): ask the user whether to proceed with generic notes conventions, and be conservative about writes.

**Multi-session coordination**: the digest's `open_sessions:` list is the canonical source of peer session ids. For each peer session id, respect its scope per the brain-local `RULES-SESSION-LIFECYCLE.md`, or `_COMMON/RULES-SESSION-LIFECYCLE.common.md` when the wrapper is unavailable, under "Multi-session coordination" — do not edit or move artifacts inside another session's scope without an explicit handoff.

**Fallback** (if `session_open.py` is unavailable): read the operational files manually in this order: `AGENTS.md` → `BRAIN.md` → `WIP/WIP.md` → `TASK_TYPES/TASK_TYPES.md`, run `session_bootstrap.py --brain-root <brain_path>`, then create the session note and update the daily manually per `RULES-SESSION-LIFECYCLE.md` Flow 2.

## Project-aware note loading

After loading brain context (above), filter what to display by deriving project keywords from the current working directory and matching them against WIP items + notes found via `find_related_notes.py`. Only load notes the user selects.

The full 5-step workflow (keyword extraction, WIP cross-reference, script invocation, selection UI, fallback) is in [references/project-aware-note-loading.md](references/project-aware-note-loading.md).

## Documenting activity

Document **meaningful** session activity in the brain — not everything, only what has lasting value:

- **Daily-note rule pre-check**: before writing to a daily note, read the brain-local `RULES-DAILY-NOTES.md` if it exists, otherwise read `_COMMON/RULES-DAILY-NOTES.common.md`. Validate the planned edit against cleanup timing, `# Sessions` traceability, and project-section uniqueness before writing.
- **Daily note**: record significant progress, decisions, and next actions in today's daily note under `JOURNAL/`. Create it if it does not exist, following the brain's daily note template and linking conventions.
- **WIP updates**: if the session touches active WIP items, update the relevant WIP notes.
- **WIP dashboard invariant**: every active non-session note under `WIP/` must be linked
  from `WIP/WIP.md`. After creating or activating one, run `brain_check.py --wip-note
  <brain-relative-path>`; do not report completion if the check fails.
- **Session note**: if the brain uses session notes (`WIP/SESSIONS/`), create or update the session note.
- **New notes**: only create new notes when the session produces knowledge worth preserving beyond the current task.
- **Post-apply truth**: write durable notes from the resulting state, not the approval plan.
  Completed checks are evidence rather than TODOs, and temporary handoffs are sources,
  not durable references unless the user explicitly promotes them.

Follow all formatting conventions, frontmatter schemas, and linking patterns defined in the brain's `AGENTS.md` and `BRAIN.md`. Do not invent new conventions — match what already exists.

## Content classification: brain vs project documentation

When the session is connected to both a brain and a project (repo, workspace, etc.), apply these rules to decide where each piece of content belongs.

### Classification rule

Ask one question per piece of content:

> **"Would another person need this to operate, understand, or plan the project?"**
> → Goes to the **project's documentation home**.

> **"Does this answer what I did, when, why, or how I got here?"**
> → Goes to the **brain** (daily notes, sessions, WIP).

MEMORY only if the content provides **reusable value** beyond historical trace (e.g. installation steps, configuration recipes). Pure activity logs do not belong in MEMORY.

### Project documentation home

Each project declares its documentation home in its `AGENTS.md`, `CLAUDE.md`, or equivalent runtime config file. Look for a `## Documentation home` section at brain resolution time.

| Declaration | Meaning |
|---|---|
| `## Documentation home` → this repo | Project documentation lives in the project's own repository. |
| `## Documentation home` → external tool (Notion, Confluence, wiki) | Project documentation lives in the named external tool. Include link. |
| No declaration | **Default: the brain** is the project's documentation home. |

When in doubt, default to the brain. The brain is always a valid destination; the project's declared home may or may not exist.

### Heavy assets rule

Images, evidence files, and other large binary assets must go to **accessible online storage** (S3-compatible, object storage, or equivalent). The documentation home (repo, brain, or external tool) should **link** to the asset's permanent location, not store the binary itself.

While online storage is not yet set up, the brain may temporarily hold assets in `ATTACHMENTS/` — but this is explicitly temporary. Track the migration in the project's WIP.

### When a note answers both questions

If a single note contains both "what another person needs" and "what I did", split it:
- Extract the operational/project knowledge → project documentation home.
- Keep the personal trace (decisions, timeline, reasoning) → brain.

## Concepts

Key terms used throughout the maintenance and setup workflows below:

- **`_COMMON`** — brain-local symlink pointing to the `agent-brain/model` directory. Its presence signals the brain is attached to the shared operating model.
- **`_STAGING/`** — temporary directory in the brain root used during initial standardization to hold all original content before it is classified and moved into the target structure (`JOURNAL/`, `WIP/`, `MEMORY/`, etc.). Its presence signals Initial mode; its absence signals Maintenance mode.
- **`_AGENTS/`** — on-demand home (created by `home_setup.py`) for brain-internal directories that act as the source of truth for an external agent runtime (e.g. `_AGENTS/CLAUDE/`, referenced via symlinks under `~/.claude/`). Sits alongside `_COMMON` and `_STAGING` as an operational top-level directory, never as content.
- **`QUARANTINE/TRASH/`** — destination for content that looks discardable but must never be deleted automatically. Items remain there until the user explicitly approves permanent deletion.
- **`WIP/STANDARDIZE_PROCESS.md`** — durable state file tracking brain standardization progress across sessions. Update it after each batch of moves; never rewrite from scratch.
- **`WIP/AGENTS_MIGRATION.<date>.md`** — generated by `home_setup.py` when it rewrites external runtime symlinks to point into `_AGENTS/`. Lists every rewritten symlink, its `.bak.<timestamp>` backup, and the exact `rm` commands to clean up the backups once the user has verified the new symlinks resolve correctly.

## Available skill tools

The runtime skill exposes deterministic helper tools under its installed `scripts/` directory (see the Runtime path note above). Prefer these tools over brain-local copies.

- `find_home.py` — resolve candidate brains from a path (notes-agnostic: obsidian, generic, empty).
- `find_related_notes.py` — find notes related to project keywords.
- `memory_query.py` — rank a few curated-memory candidates from index metadata without loading note bodies. Use only when prior cross-session guidance may help; open only relevant returned notes.
- `session_open.py` — session-start ceremony: emits a compact digest, optionally prepares a missing daily after rollover review, creates/updates the session note, idempotently upserts daily `# Sessions`, and verifies postconditions. Args: `--brain-root`, `--session-id` (real id from the agent runtime — never a timestamp), `--runtime` (claude|opencode|codex; controls resume-command format), `--session-label` (opt), `--cwd` (opt), `--prepare-daily` (opt), `--apply`. Dry-run by default.
- `brain_check.py` — read-only postcondition checker. Verifies a session has exactly one
  daily registration with the expected runtime/cwd recovery command, and/or verifies
  active WIP notes are registered in `WIP/WIP.md`. Args: `--brain-root`, optional session
  tuple (`--session-id`, `--runtime`, `--cwd`, `--date`), and repeatable `--wip-note`.
- `session_close.py` — idempotent session-close ceremony. Subcommands: `handoff <session-id>` (→ handoff-only), `consolidate <session-id> [--archive]` (→ consolidated, optional `git mv` to `QUARANTINE/TRASH/`). Archive apply refuses untracked notes or occupied destinations before editing the note and rolls back note content if the move fails. Args: `--brain-root`, `--apply`. Dry-run by default.
- `session_bootstrap.py` — legacy: inspect daily/session state and print verbose kickoff prompt. Preserved for callers that depend on it; prefer `session_open.py` for new sessions.
- `maintenance_scheduler.py` — decide which recurring Daily/Weekly/Monthly/Yearly/session maintenance jobs are due.
- `standardize_assessment.py` — assess an organized brain in maintenance mode and generate/update `WIP/STANDARDIZE_PROCESS.md`.
- `attachments_audit.py` — audit all `ATTACHMENTS/` folders under a chosen scope and optionally relocate only safe cases with `git mv`.
- `canvas_path_repair.py` — audit `.canvas` file-node paths and optionally repair only uniquely resolvable broken paths.
- `cleanup_ds_store.py` — remove `.DS_Store` noise files from visible brain content. Safe (does not destroy information); runs automatically in `home_setup.py` before the empty-dir sweep, and as a maintenance pre-check.
- `cleanup_empty_action_categories.py` — remove empty / placeholder-only action categories from daily notes (`# Actions` section). Dry-run by default. Skips legacy-shape dailies without `# Actions`. Pass `--skip-if-open-sessions` to refuse cleaning a daily that still has open session notes pending consolidation (exit code 2). Intended hook for `brain` day-rollover cleanup.
- `check_basename_collisions.py` — detect `*.md` basename collisions brain-wide. Counts incoming references (wikilink-simple / wikilink-path / markdown-simple / markdown-path) across `.md` + `.canvas` (refs inside code spans are skipped — Obsidian does not resolve them). If all four counters are 0, suggests renaming every instance and `--apply` executes via `git mv`. Otherwise computes per-file attribution and auto-renames the files no reference points at, leaving files that are referenced to interactive review via `--show-refs <basename>`. `--exclude-path` skips runtime-governed subtrees (e.g. `_AGENTS/CLAUDE/memory/`).

Tool documentation lives next to the scripts using Obsidian-safe common names:

- `TOOL.brain-check.md`
- `TOOL.attachments-audit.md`
- `TOOL.canvas-path-repair.md`
- `TOOL.check-basename-collisions.md`
- `TOOL.cleanup-ds-store.md`
- `TOOL.cleanup-empty-action-categories.md`
- `TOOL.maintenance-scheduler.md`
- `TOOL.memory-query.md`
- `TOOL.session-bootstrap.md`
- `TOOL.standardize-assessment.md`

All tools that move or rewrite files are dry-run by default. Apply only after reviewing the printed plan.

### Script conventions

- Common lifecycle setup scripts live under `<agent-brain>/model/SCRIPTS/`.
- Runtime skill tools live under `<agent-brain>/skills/brain/scripts/` and are exposed through installed runtime symlinks such as `~/.agents/skills/brain/scripts/`.
- Python scripts and latest-run logs use CLI-oriented basenames, while Markdown docs keep notes-safe `.md` names.
- Skill tool docs use Obsidian-safe names such as `TOOL.attachments-audit.md`.
- Scripts are dry-run by default when they create, link, move, or rewrite files.
- Every run prints to console and writes the latest `.log`; logs are runtime artifacts and should not be committed.

## Common lifecycle workflows

Brains use the shared `agent-brain` operating model through a brain-local `_COMMON` symlink. When the user asks to set up, update, verify, or install the model, prefer deterministic scripts from the agent-brain checkout instead of manual edits.

### Maintain, clean, order, or standardize a brain

When the user invokes `brain init`, `brain maintain`, `brain clean`, `brain order`, `brain standardize`, or natural-language requests like "ordena el brain", "haz mantenimiento", "limpia el brain", or "revisa el brain", run the guided brain maintenance engine: mechanical setup check → mode detection → drain `_STAGING/` (Initial mode) or run assessment (Maintenance mode).

The full 4-step workflow is in [references/brain-maintenance.md](references/brain-maintenance.md).

Do not silently perform semantic reorganization. The first output should explain what mode was detected, what safe maintenance was run, what is due/review, and what decisions remain for the user.

### Setup and attachment operations

For one-time setup or repair: locate the agent-brain checkout, attach a brain via `bootstrap-zero.sh`/`home_setup.py`, or install/repair a runtime skill via `skill_link.sh`. All commands follow the dry-run-first pattern.

The full commands and decision logic are in [references/setup-and-attach.md](references/setup-and-attach.md).

## How to verify

Invoke `brain` (explicitly as `$brain` in Codex, or by a matching natural-language request) and confirm:
- From inside an attached brain directory, it connects directly without prompting.
- From outside any brain, it asks for a path or surfaces detected brains.
- After connection, `session_open.py` is called via Bash and its compact digest appears in the response; no separate Read calls are made for `AGENTS.md`, `BRAIN.md`, `WIP/WIP.md`, or `TASK_TYPES/TASK_TYPES.md`.
- From a working directory matching a project (e.g. `~/workspace/<project>/`), related WIP items appear pre-selected in the selection form; unrelated notes are not loaded.
- `brain close session` (or `wrap up`) triggers `session_close.py` in dry-run first; the status transition (`open → handoff-only` or `open → consolidated`) is printed; `--apply` writes the Status line and removes the `wip` tag on consolidate.
- `brain init` on a brain with `_STAGING/` enters Initial mode and reads `WIP/STANDARDIZE_PROCESS.md` before any moves.
- `brain maintain` (or any maintenance trigger) on a brain without `_STAGING/` runs `maintenance_scheduler.py` and presents due/review jobs before structural assessment.
- Running `cleanup_empty_action_categories.py --skip-if-open-sessions` exits with code 2 and prints which session notes block cleanup when a daily has open sessions pending consolidation.
- All file moves use `git mv` (no plain copy+delete) when the brain is a Git repo. Discardable items go to `QUARANTINE/TRASH/`, not deletion.

## Dependencies

Required files in `references/`. Read each file when first referenced by the section noted below.
If any file cannot be read, stop immediately and tell the user:
`Reference file references/<name>.md is missing — reinstall the skill.`

| File | Section |
|------|---------|
| `references/project-aware-note-loading.md` | Project-aware note loading |
| `references/brain-maintenance.md` | Maintain, clean, order, or standardize a brain |
| `references/setup-and-attach.md` | Setup and attachment operations |

## Constraints

- Never write to the brain without the user's awareness. If unsure whether something should be documented, ask.
- Never modify `.obsidian/` unless the user explicitly requests it.
- Never delete content from the brain. Prefer moving, renaming, or consolidating. If cleanup suggests deletion, move the candidate to `QUARANTINE/TRASH/` with traceability and wait for explicit user approval before permanent deletion.
- `home_setup.py` may rewrite external symlinks under canonical agent runtime homes (`~/.agents`, `~/.claude`, `~/.codex`, plus any `--runtime-home`) when it moves runtime-tied directories into `_AGENTS/`. Originals are preserved as `.bak.<timestamp>` siblings and the rewrites are recorded in `WIP/AGENTS_MIGRATION.<date>.md`. Never delete the `.bak` files automatically — they belong to the user to verify and clean up.
- The Bash `python3:*` allowance is for invoking the documented runtime skill scripts and lifecycle scripts under `<agent-brain>/model/SCRIPTS/` and `<agent-brain>/skills/brain/scripts/`. Never run inline `python3 -c "..."` expressions or arbitrary user-supplied Python files; if a task seems to require it, ask the user explicitly first.
- Never pass `--skip-full-reorder` to `home_setup.py` autonomously. The choice between full reorder and skipping the staging sweep is always the user's. Before invoking the script with that flag, ask the user via `AskUserQuestion` and respect their answer. Do not infer the choice from brain size, content, or any other heuristic — the default is full reorder.
- Never drain `_STAGING/` content autonomously. Every batch — including purely mechanical date-based moves (e.g. daily notes by year) and scaffolding writes (e.g. `WIP/WIP.md`, `WIP/STANDARDIZE_PROCESS.md`) — requires explicit user confirmation via `AskUserQuestion` immediately before any `git mv` or file write is executed. Reversibility through Git is not authorization. Default to one batch per session and stop unless the user explicitly asks to continue. See `references/brain-maintenance.md` step 3 for the full gate pattern.
- If the user's brain has a local `TEMPLATES/Daily Note Template.md` whose shape differs from the common source (`_COMMON/TEMPLATES/TEMPLATE.daily-note.md`), pause and propose unification — analyze what the local has that the common does not, suggest enriching the common to absorb the local additions, then collapse to a single shared template. Do not auto-replace either side and do not perpetuate the divergence by writing notes against the local-only shape.
- If a skill tool script fails (non-zero exit or unexpected error), report the error and the relevant `.log` path to the user and ask whether to retry, skip, or stop. Never retry automatically — partial state from a failed apply-mode run may need manual review.
- Every apply-mode script run writes a `.log` file (see Script conventions). These logs are the audit trail for brain writes; do not delete them until the user has verified the changes are correct.
- If the brain's `AGENTS.md` or `BRAIN.md` define rules that conflict with these instructions, follow the brain's own rules.
