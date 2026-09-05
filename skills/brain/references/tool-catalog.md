# Tool Catalog

<!-- agent-brain-reference
{"downstream_rules":["Read the specific TOOL.*.md file before using a non-obvious tool.","Prefer runtime-installed skill script paths over brain-local copies.","Review every dry-run plan before apply-mode tools that move or rewrite files."],"route_id":"skill.tool-catalog","scenario_id":"scenario.tool-catalog","schema_version":"agent-brain-skill-reference/v1","source_ranges":["range.skill.tool-catalog.catalog","range.skill.tool-catalog.log-contract"],"trigger_rules":["Load when selecting a deterministic brain skill script, checking tool documentation, or reasoning about script/log conventions."]}
-->

## Trigger Rules

- Load when selecting a deterministic brain skill script, checking tool documentation, or reasoning about script/log conventions.

## Downstream Rules

- Read the specific TOOL.*.md file before using a non-obvious tool.
- Prefer runtime-installed skill script paths over brain-local copies.
- Review every dry-run plan before apply-mode tools that move or rewrite files.

## Copied Source Ranges

## Available skill tools

The runtime skill exposes deterministic helper tools under its installed `scripts/` directory (see the Runtime path note above). Prefer these tools over brain-local copies.

- `find_home.py` — resolve only brains implanted with the current agent-brain model. Its explicit `--candidates` mode retains notes-agnostic destination suggestions for bootstrap and must not be used to open sessions.
- `find_related_notes.py` — find notes related to project keywords.
- `memory_query.py` — rank a few curated-memory candidates from index metadata without loading note bodies. Use only when prior cross-session guidance may help; open only relevant returned notes.
- `profile_context.py` — resolve one or more generic capabilities through the active environment profile. It can inspect sanitized Codex MCP registry/auth readiness with `--live`, returns runtime invocation hints without credentials/endpoints, and optionally includes issue-tracking policy. A caller that can enumerate its active tool names safely may pass `--available-tool` plus `--tool-catalog-complete`; an absent exact MCP invocation then fails closed. Claude live discovery is refused because its registry command may rewrite settings. Profile resolution never grants tool permission.
- `session_open.py` — session-start ceremony: emits a compact digest, optionally prepares a missing daily after rollover review with reciprocal nearest-neighbor navigation and rollback, creates/updates the session note, idempotently upserts daily `# Sessions`, and verifies postconditions. Args: `--brain-root`, `--session-id` (real id from the agent runtime — never a timestamp), `--runtime` (antigravity|claude|opencode|codex; controls resume-command format), `--session-label` (opt), `--cwd` (opt), `--prepare-daily` (opt), `--apply`. Dry-run by default.
- `resolve_session_id.py` — deterministic OpenCode session-id resolution: `$OPENCODE_SESSION_ID` (plugin-injected) → `-s`/`--session` in the `$OPENCODE_PID` command line → SQLite liveness probe (newest `part` write in `--cwd`, recency + margin) → exit 3 with candidates for the ask-the-user fallback. Never infers by list order. `--install-plugin` copies the `brain-session-env` plugin (opencode `shell.env` hook) into `$OPENCODE_CONFIG_DIR/plugins/` to enable signal 1 globally.
- `brain_check.py` — read-only postcondition checker. Verifies an active or archived
  session has exactly one daily registration with the expected runtime/cwd recovery command,
  preferring the active note when both exist, and/or verifies
  active WIP notes are registered in `WIP/WIP.md`. Args: `--brain-root`, optional session
  tuple (`--session-id`, `--runtime`, `--cwd`, `--date`), and repeatable `--wip-note`.
- `session_close.py` — idempotent session-close ceremony. It refuses roots that are not implanted with this checkout's current model before reading or mutating session state. Subcommands: `handoff <session-id>` (→ handoff-only), `consolidate <session-id> [--archive]` (→ consolidated, optional `git mv` to `QUARANTINE/TRASH/`). Archive apply refuses untracked notes or occupied destinations before editing, stages the final consolidated destination, and restores the original path and content if the move or staging step fails. Args: `--brain-root`, `--apply`; `--apply` is accepted before or after the subcommand. Dry-run by default.
- `session_bootstrap.py` — legacy: inspect daily/session state and print verbose kickoff prompt. Preserved for callers that depend on it; prefer `session_open.py` for new sessions.
- `maintenance_scheduler.py` — decide which recurring Daily/Weekly/Monthly/Yearly/session maintenance jobs are due.
- `source_scheduler.py` — decide whether source ingestion is activated for the brain and which registered sources are due, not due, or blocked; record the watermark after a source is investigated; plus `check-health`, a read-only quiet-streak advisory (never blocks, never disables a source). Dry-run by default; `mark-checked` requires `--apply` to write.
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
- `TOOL.profile-context.md`
- `TOOL.session-bootstrap.md`
- `TOOL.source-scheduler.md`
- `TOOL.standardize-assessment.md`

All tools that move or rewrite files are dry-run by default. Apply only after reviewing the printed plan.

### Script conventions

- Common lifecycle setup scripts live under `<agent-brain>/model/SCRIPTS/`.
- Runtime skill tools live under `<agent-brain>/skills/brain/scripts/` and are exposed through installed runtime symlinks such as `~/.agents/skills/brain/scripts/`.
- Python scripts and latest-run logs use CLI-oriented basenames, while Markdown docs keep notes-safe `.md` names.
- Skill tool docs use Obsidian-safe names such as `TOOL.attachments-audit.md`.
- Scripts are dry-run by default when they create, link, move, or rewrite files.
- Every run prints to console and writes the latest `.log`; logs are runtime artifacts and should not be committed.


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
- All justified brain-internal file moves use `git mv` under the bounded standing authorization in `_COMMON/AGENTS.common.md` (no plain copy+delete) when the brain is a Git repo. Discardable items go to `QUARANTINE/TRASH/`, not deletion.
