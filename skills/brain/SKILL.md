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
  - Agent
  - AskUserQuestion
  - Bash(python3:*, git mv:*, mkdir:*)
metadata:
  short-description: Connect to a notes brain and document activity
---

# Brain Connector

Connect the current session to a notes brain, load its operating model, and document session activity there. Obsidian vaults are supported, but Obsidian is not required.

## Invocation routing

For explicit invocation, Codex CLI and the IDE extension use `$brain`; Antigravity CLI and
Claude Code use `/brain`. Natural-language requests can still activate the skill implicitly.

- No arguments, `session`, `nueva sesión`, `new session`, `inicio sesión`, `connect`, or `start` → run the session-start protocol: resolve the brain, run `session_open.py` (see "After brain resolution"), consume the compact digest, and follow Flow 2 (`new session`) for the detected scenario. Flow 2 creates today's daily note when it is missing — first consolidating the durable work of clearly-finished previous sessions (State-driven rollover), then closing the previous day. Starting the day is part of session start and does **not** require an explicit `nuevo día` instruction.
- `new-day`, `nuevo día`, `cambio de día`, `cambia de día`, or `we changed day` → run the day-rollover protocol. Resolve the brain, run `session_open.py` (day_rollover_detected will be `yes`), load `RULES-SESSION-LIFECYCLE.md`, and follow Flow 1 (`day change / same session continues`). Do not create a new session note in this flow.
- `close session`, `cerrar sesión`, `cerramos la sesión`, `wrap up`, `end session`, `consolidate`, or `consolidar` → run the session-close protocol: resolve the brain, load `RULES-SESSION-LIFECYCLE.md` (Closing gate + Consolidation rules), then run `session_close.py`. Use the canonical apply form `session_close.py --brain-root <brain> --apply handoff <session-id>` for a handoff. For full consolidation, use `session_close.py --brain-root <brain> --cwd <cwd> --apply consolidate <session-id> --archive` (pass the session's real working directory as `--cwd` so the still-due-sources check selects the right environment profile) when the closing gate passes and the session note is Git-tracked; the brain-internal move has standing user authorization and needs no separate Git confirmation. If the note is untracked, omit `--archive` and report why it remains in place. The CLI also accepts a trailing `--apply` so equivalent natural invocations do not fail. Objectives review is required before consolidation (see `RULES-DAILY-NOTES.md`).
- `ingesta <fuente>` or `ingest <fuente>` (`$brain ingesta <fuente>` in Codex/OpenCode) → source ingestion is a brain-scoped optional capability (`RULES-OPTIONAL-CAPABILITIES.common.md` → "Source ingestion"); only proceed if `WIP/WIP.md` links `sources.registry.md` anywhere (no project filter). Look up `<fuente>` there; if missing, ambiguous, disabled, or blocked (see `source_scheduler.py list-due`), fail closed and say so. Otherwise investigate that one source now (bypassing its due-ness check), then `source_scheduler.py mark-checked --brain-root <brain> --source <fuente> --status <ok|no_activity|degraded> --apply` — and, if the descriptor declares `Scan targets:`, pass `--scanned` naming every target actually covered; an incomplete claim is refused and the watermark stays put.
- `revisar fuentes` or `review sources` → list the not-yet-triaged capture under `INBOX/sources/*` for the whole brain (source ingestion is brain-scoped, not per-project) and let the user ask for detail on any item; this only reads and summarizes, it does not triage on its own.

Do not run broad brain maintenance, standardization, or semantic reorganization from a no-argument/session-start invocation. Those require explicit arguments such as `maintain`, `clean`, `order`, `standardize`, or `init`. Exception: when today's daily note is missing, Flow 2 finalises the **previous** day (review-first TODO carry-over and Objectives review, then empty-category cleanup scoped to that single previous daily) and creates today's note. That per-day rollover is part of session start; the restriction here is about brain-wide maintenance, not the previous-day rollover.

## Prerequisites

- Python 3.x (stdlib only — scripts have no external dependencies).
- `git` on PATH (used for `git mv` during brain reorganization).
- A notes brain to connect to.
- The `brain` skill installed by the agent-brain bootstrap. Codex and OpenCode share `~/.agents/skills/brain`; Claude uses `~/.claude/skills/brain`; Antigravity CLI uses `~/.gemini/antigravity-cli/skills/brain`.

> **Runtime path note:** command examples use `~/.agents/skills/brain/scripts/...`, shared by Codex and OpenCode. In another runtime, use its installed `brain/scripts/` path, such as `~/.claude/skills/brain/scripts/` or `~/.gemini/antigravity-cli/skills/brain/scripts/`.

## Brain resolution

Run strict discovery from the current directory first. It accepts only brains whose
`_COMMON` symlink resolves to the current agent-brain model:

```bash
python3 ~/.agents/skills/brain/scripts/find_home.py "$PWD"
```

If that returns no brain, run it without a path to surface all current-model brains under
the user's home. Never use `--candidates` for session resolution; that mode is reserved for
bootstrap destination suggestions.

The script returns JSON. Handle each outcome:

**1 brain found** → use it directly, proceed to loading context.

**Multiple brains found** → check for nested brains. Each brain object includes:
- `has_agents_md` / `has_brain_md`: true if the brain has operational docs
- `is_nested` / `parent_brain`: indicates this brain lives inside another found brain

If one brain has `has_agents_md: true` and others do not, prefer the one with operational docs. If still ambiguous, present the list to the user and ask them to pick.

**No brains found** → tell the user no brain was found and ask them to provide the brain path manually. Then run the script again with that path.

**Error (path does not exist)** → report the error and ask for a valid path.

**Conflicting `_COMMON` found** → report that the directory targets another model or has an
invalid `_COMMON` entry. Do not connect or pass it to lifecycle scripts; it requires an
explicit repair or migration first.

## After brain resolution

Once a brain path is confirmed, run `session_open.py` immediately. Do not pre-read the brain's `AGENTS.md`, `BRAIN.md`, `WIP/WIP.md`, `TASK_TYPES/TASK_TYPES.md`, or their `_COMMON/*.common.md` sources; the compact digest is the session-start entrypoint.

The digest is state-only progressive loading: operational-file presence, open-session state, cwd-filtered WIP snippets, and `TASK_TYPES` index one-liners. It must not include `AGENTS.md`, `BRAIN.md`, rule, task, or reference bodies. Runtime-injected project instructions are already loaded by the agent runtime; only load a brain operational file later when a matching task requires it, and then load exactly one triggered rule, task, or reference at a time.

Resolve the real session id and runtime before invoking the script. Never pass a timestamp fallback or let the script guess a wrong runtime. If the real id cannot be resolved, stop and ask the user.

```bash
python3 ~/.agents/skills/brain/scripts/session_open.py \
  --brain-root "<brain_path>" \
  --session-id "<REAL session id>" \
  --runtime <antigravity|claude|opencode|codex|generic> \
  --session-label '<label, or empty>' \
  --cwd "$(pwd)"
```

Review the compact digest, announce that the brain is connected, and briefly summarize active context. If the digest lists `maintenance_jobs`, mention the due/review jobs briefly and offer to run `brain maintain` — do not run it unprompted. If the digest lists `sources_due` entries, split them by form: a line ending in `blocked — <reason>` is reported to the user, never investigated (no subagent); every other line is a due source, so spawn one subagent per listed source using the runtime's subagent mechanism when available and permitted, otherwise investigate them sequentially in the parent — each subagent reads that source's descriptor (and the matching `SOURCE_TYPES/` guide) for what to look for, reports back only if something is genuinely relevant, and any partial failure (timeout, missing permission, error) is logged as a one-line note and skipped — never blocking the rest of the sources or the session start. Mark each investigated (non-blocked) source checked via `source_scheduler.py mark-checked --apply` once done — pass `--scanned` too if that source's descriptor declares `Scan targets:`. On routine opens, pass `--apply` with the same resolved id/runtime/cwd to create or upsert the session note and daily `# Sessions` registration.

Load [references/session-lifecycle-routing.md](references/session-lifecycle-routing.md) only when the task needs detailed session start, day rollover, close-session, peer-session, `session_open.py`, `session_close.py`, or `session_bootstrap.py` behavior.

### Ownership metadata

| Policy area | Owner | Authority |
|---|---|---|
| canonical-open-authority | session_open.py | unique |
| compatibility-fallback | session_bootstrap.py | compatibility-only |

## Conditional Reference Router

Do not load broad references during ordinary invocation. Load exactly the referenced file whose trigger matches the user's request:

| Trigger | Load |
|---|---|
| Project-aware WIP/note selection after session open | `references/project-aware-note-loading.md` |
| Brain maintenance, clean, order, standardize, or `brain init` | `references/brain-maintenance.md` |
| Setup, attach, install, repair, bootstrap, or runtime skill linking | `references/setup-and-attach.md` |
| Session start details, day rollover, close session, peer sessions, or lifecycle fallback | `references/session-lifecycle-routing.md` |
| Durable activity notes, WIP/MEMORY/project documentation classification, or asset placement | `references/documentation-and-classification.md` |
| Tool selection, script/log conventions, or non-obvious tool documentation | `references/tool-catalog.md` |
| Brain write authorization, apply-mode gates, `_STAGING`, skip-full-reorder, or tool failure handling | `references/constraints.md` |

Read the specific `TOOL.*.md` file before using a non-obvious script documented by `references/tool-catalog.md`.

## Dependencies

Required files in `references/`. Read each file when first referenced by the section noted below.
If any file cannot be read, stop immediately and tell the user:
`Reference file references/<name>.md is missing — reinstall the skill.`

| File | Section |
|------|---------|
| `references/project-aware-note-loading.md` | Project-aware note loading |
| `references/brain-maintenance.md` | Maintain, clean, order, or standardize a brain |
| `references/setup-and-attach.md` | Setup and attachment operations |
| `references/session-lifecycle-routing.md` | Session lifecycle routing and postconditions |
| `references/documentation-and-classification.md` | Documentation and classification |
| `references/tool-catalog.md` | Available skill tools and script conventions |
| `references/constraints.md` | Constraints and apply-mode safety gates |

## Constraints

- Never write to the brain without the user's awareness. If unsure whether something should be documented, ask.
- Never modify `.obsidian/` unless the user explicitly requests it.
- Never delete content from the brain. Prefer moving, renaming, or consolidating. If cleanup suggests deletion, move the candidate to `QUARANTINE/TRASH/` with traceability and wait for explicit user approval before permanent deletion.
- The Bash `python3:*` allowance is for invoking the documented runtime skill scripts and lifecycle scripts under `<agent-brain>/model/SCRIPTS/` and `<agent-brain>/skills/brain/scripts/`. Never run inline `python3 -c "..."` expressions or arbitrary user-supplied Python files; if a task seems to require it, ask the user explicitly first.
- Never pass `--skip-full-reorder` to `home_setup.py` autonomously. The choice between full reorder and skipping the staging sweep is always the user's. Before invoking the script with that flag, ask the user via `AskUserQuestion` and respect their answer. Do not infer the choice from brain size, content, or any other heuristic — the default is full reorder.
- When setup dry-run reports `symlink_policy: required`, ask whether to ingest the listed targets with `copy` (recommended) or leave eligible non-canonical links at the brain root with `keep`. Never offer `keep` for a link that occupies a canonical scaffold directory.
- Never drain `_STAGING/` content autonomously. Every batch — including purely mechanical date-based moves (e.g. daily notes by year) and scaffolding writes (e.g. `WIP/WIP.md`, `WIP/STANDARDIZE_PROCESS.md`) — requires explicit user confirmation via `AskUserQuestion` immediately before execution. That confirmation approves the batch scope and classifications; the resulting brain-internal `git mv` operations use the bounded standing authorization in `_COMMON/AGENTS.common.md` and need no additional Git prompt. Default to one batch per session and stop unless the user explicitly asks to continue. See `references/brain-maintenance.md` step 3 for the full gate pattern.
- If the user's brain has a local `TEMPLATES/Daily Note Template.md` whose shape differs from the common source (`_COMMON/TEMPLATES/TEMPLATE.daily-note.common.md`), pause and propose unification. Do not auto-replace either side and do not perpetuate the divergence by writing notes against the local-only shape.
- Every apply-mode script run writes a `.log` file (see Script conventions). These logs are the audit trail for brain writes; do not delete them until the user has verified the changes are correct.
- If the brain's `AGENTS.md` or `BRAIN.md` define rules that conflict with these instructions, follow the brain's own rules.
