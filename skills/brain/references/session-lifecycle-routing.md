# Session Lifecycle Routing

<!-- agent-brain-reference
{"downstream_rules":["Load RULES-SESSION-LIFECYCLE.md for day rollover, close-session consolidation, and multi-session coordination details.","Use session_open.py as the canonical open-session authority and session_bootstrap.py only as compatibility fallback.","Do not load maintenance, setup, tool-catalog, or constraints references during ordinary session start."],"route_id":"skill.session-routing","scenario_id":"scenario.session-routing","schema_version":"agent-brain-skill-reference/v1","source_ranges":["range.skill.session-routing.protocol","range.skill.session-routing.postcondition"],"trigger_rules":["Load when resolving session start, day rollover, close session, peer-session coordination, or session_open/session_close fallback behavior."]}
-->

## Trigger Rules

- Load when resolving session start, day rollover, close session, peer-session coordination, or session_open/session_close fallback behavior.

## Downstream Rules

- Load RULES-SESSION-LIFECYCLE.md for day rollover, close-session consolidation, and multi-session coordination details.
- Use session_open.py as the canonical open-session authority and session_bootstrap.py only as compatibility fallback.
- Do not load maintenance, setup, tool-catalog, or constraints references during ordinary session start.

## Copied Source Ranges

## After brain resolution

Once a brain path is confirmed, run `session_open.py` to load context and prepare the session in one call.

Run `session_open.py` immediately after resolution. Do not pre-read the brain's `AGENTS.md`,
`BRAIN.md`, `WIP/WIP.md`, `TASK_TYPES/TASK_TYPES.md`, or their `_COMMON/*.common.md`
sources; global runtime instructions are already loaded and the compact digest is the intended
entrypoint.

**Resolve the real session id and runtime BEFORE invoking the script** — never pass a timestamp fallback and never let the script guess a wrong runtime. The calling agent always knows its own runtime:

| Runtime | Resolve session id | Pass `--runtime` |
|---|---|---|
| Antigravity CLI | read the current workspace entry from `~/.gemini/antigravity-cli/cache/last_conversations.json`; if it is absent, use `/resume` and ask rather than guessing | `--runtime antigravity` |
| Claude Code | read `$CLAUDE_CODE_SESSION_ID` | `--runtime claude` (or omit; auto-detected via env) |
| OpenCode | run `opencode session list`, pick the active session | `--runtime opencode` (**required** — no env var) |
| Codex | read `$CODEX_THREAD_ID` (runtime-provided; not a public API) | `--runtime codex` |
| Other | consult the runtime's session-listing command | `--runtime generic` |

If you cannot resolve the real id, **stop and ask the user** rather than inventing one.

```bash
python3 ~/.agents/skills/brain/scripts/session_open.py \
  --brain-root "<brain_path>" \
  --session-id "<REAL session id from your runtime>" \
  --runtime <antigravity|claude|opencode|codex> \
  --session-label '<label from /rename, or empty>' \
  --cwd "$(pwd)"
```

The `--runtime` flag controls the resume-command format emitted in the session note and the daily `# Sessions` entry (`agy --conversation <id>`, `opencode -s <id>`, `claude --resume <id>`, `codex resume <id>`, etc.). The supplied `--cwd` is recorded and prefixed as `cd <cwd> && ...`, because runtime configuration and project guidance are resolved from the launch directory. If `--runtime` is omitted, the script falls back to `detect_runtime()` (Claude only, via env); any unknown runtime emits a bare session id so a wrong runtime is never silently claimed.

The script emits a compact digest (~20-30 lines): brain state, today's daily info, open sessions list, WIP items filtered by cwd, TASK_TYPES one-liners, and any warnings. The digest is a state trace, not a prose snapshot: it records operational-file presence and selected one-liners, but never includes `AGENTS.md`, `BRAIN.md`, rule, task, or reference bodies. **Do not additionally read `AGENTS.md`, `BRAIN.md`, `WIP/WIP.md`, or `TASK_TYPES/TASK_TYPES.md` — the digest is the only brain context the main agent needs.**

After reviewing the digest, announce to the user that the brain is connected and briefly summarize active context.

After the user acknowledges the digest (or when the session open is routine), pass `--apply` to create the session note and idempotently register it in today's daily `# Sessions` block:

```bash
python3 ~/.agents/skills/brain/scripts/session_open.py \
  --brain-root "<brain_path>" \
  --session-id "<REAL session id>" \
  --runtime <antigravity|claude|opencode|codex> \
  --session-label '<label>' \
  --cwd "$(pwd)" \
  --apply
```

`--apply` is safe to repeat: the script upserts by full session id, preserves a user-edited
daily summary, refreshes the canonical session-note link, removes known `# Sessions` template
scaffold, and verifies that the session note and daily contain one canonical recovery command.

**Day rollover**: if the digest reports `day_rollover_detected: yes`, load the brain-local `RULES-SESSION-LIFECYCLE.md` when present, otherwise `_COMMON/RULES-SESSION-LIFECYCLE.common.md`, and run the semantic review in Flow 1 / Flow 2 Scenario B first. When that review is complete, run `session_open.py --prepare-daily --apply` once. `--prepare-daily` links the new daily to the nearest existing daily notes, updates those neighbors reciprocally with rollback on failure, and leaves `# Sessions` empty before the same command performs the idempotent registration. It refuses divergent local/common daily templates and ambiguous or malformed navigation instead of choosing silently.

**If the brain has no operational files** (`AGENTS.md`, `BRAIN.md` all missing): ask the user whether to proceed with generic notes conventions, and be conservative about writes.

**Multi-session coordination**: the digest's `open_sessions:` list is the canonical source of peer session ids. For each peer session id, respect its scope per the brain-local `RULES-SESSION-LIFECYCLE.md`, or `_COMMON/RULES-SESSION-LIFECYCLE.common.md` when the wrapper is unavailable, under "Multi-session coordination" — do not edit or move artifacts inside another session's scope without an explicit handoff.

**Conditional payloads**: runtime-injected project instructions are already loaded by the agent runtime. After the digest, load only the one rule, task, or reference whose trigger matches the current work. Load `BRAIN.md` only for structural or classification questions.

**Fallback** (if `session_open.py` is unavailable): read the operational files manually in this order: `AGENTS.md` → `BRAIN.md` → `WIP/WIP.md` → `TASK_TYPES/TASK_TYPES.md`, run `session_bootstrap.py --brain-root <brain_path>`, then create the session note and update the daily manually per `RULES-SESSION-LIFECYCLE.md` Flow 2.

## Project-aware note loading

After loading brain context (above), filter what to display by deriving project keywords from the current working directory and matching them against WIP items + notes found via `find_related_notes.py`. Only load notes the user selects.

The full 5-step workflow (keyword extraction, WIP cross-reference, script invocation, selection UI, fallback) is in [references/project-aware-note-loading.md](references/project-aware-note-loading.md).


## Common lifecycle workflows

Brains use the shared `agent-brain` operating model through a brain-local `_COMMON` symlink. When the user asks to set up, update, verify, or install the model, prefer deterministic scripts from the agent-brain checkout instead of manual edits.

### Maintain, clean, order, or standardize a brain

When the user invokes `brain init`, `brain maintain`, `brain clean`, `brain order`, `brain standardize`, or natural-language requests like "ordena el brain", "haz mantenimiento", "limpia el brain", or "revisa el brain", run the guided brain maintenance engine: mechanical setup check → mode detection → drain `_STAGING/` (Initial mode) or run assessment (Maintenance mode).

The full 4-step workflow is in [references/brain-maintenance.md](references/brain-maintenance.md).

Do not silently perform semantic reorganization. The first output should explain what mode was detected, what safe maintenance was run, what is due/review, and what decisions remain for the user.

### Setup and attachment operations

For one-time setup or repair: locate the agent-brain checkout, attach a brain via `bootstrap-zero.sh`/`home_setup.py`, or install/repair a runtime skill via `skill_link.sh`. All commands follow the dry-run-first pattern.

The full commands and decision logic are in [references/setup-and-attach.md](references/setup-and-attach.md).
