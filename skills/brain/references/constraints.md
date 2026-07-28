# Constraints

<!-- agent-brain-reference
{"downstream_rules":["Ask before uncertain brain writes and before skip-full-reorder decisions.","Never drain _STAGING autonomously.","Report failing skill tool logs and ask whether to retry, skip, or stop."],"route_id":"skill.constraints","scenario_id":"scenario.constraints","schema_version":"agent-brain-skill-reference/v1","source_ranges":["range.skill.constraints"],"trigger_rules":["Load when checking brain write permissions, setup safety gates, apply-mode constraints, or failure-handling rules."]}
-->

## Trigger Rules

- Load when checking brain write permissions, setup safety gates, apply-mode constraints, or failure-handling rules.

## Downstream Rules

- Ask before uncertain brain writes and before skip-full-reorder decisions.
- Never drain _STAGING autonomously.
- Report failing skill tool logs and ask whether to retry, skip, or stop.

## Copied Source Ranges

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
