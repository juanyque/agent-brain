# Constraints

<!-- agent-brain-reference
{"downstream_rules":["Ask before uncertain brain writes and before skip-full-reorder decisions.","Never drain _STAGING autonomously.","Diagnose failures read-only; never repeat an unchanged failed strategy; retry corrected or materially different strategies only within existing authorization; stop on ambiguity or after three failed strategies."],"route_id":"skill.constraints","scenario_id":"scenario.constraints","schema_version":"agent-brain-skill-reference/v1","source_ranges":["range.skill.constraints"],"trigger_rules":["Load when checking brain write permissions, setup safety gates, apply-mode constraints, or failure-handling rules."]}
-->

## Trigger Rules

- Load when checking brain write permissions, setup safety gates, apply-mode constraints, or failure-handling rules.

## Downstream Rules

- Ask before uncertain brain writes and before skip-full-reorder decisions.
- Never drain _STAGING autonomously.
- Diagnose failures read-only; never repeat an unchanged failed strategy; retry corrected or materially different strategies only within existing authorization; stop on ambiguity or after three failed strategies.

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
- Never drain `_STAGING/` content autonomously. Every batch — including purely mechanical date-based moves (e.g. daily notes by year) and scaffolding writes (e.g. `WIP/WIP.md`, `WIP/STANDARDIZE_PROCESS.md`) — requires explicit user confirmation via `AskUserQuestion` immediately before execution. That confirmation approves the batch scope and classifications; the resulting brain-internal `git mv` operations use the bounded standing authorization in `_COMMON/AGENTS.common.md` and need no additional Git prompt. Default to one batch per session and stop unless the user explicitly asks to continue. See `references/brain-maintenance.md` step 3 for the full gate pattern.
- If the user's brain has a local `TEMPLATES/Daily Note Template.md` whose shape differs from the common source (`_COMMON/TEMPLATES/TEMPLATE.daily-note.md`), pause and propose unification — analyze what the local has that the common does not, suggest enriching the common to absorb the local additions, then collapse to a single shared template. Do not auto-replace either side and do not perpetuate the divergence by writing notes against the local-only shape.

### Failure recovery and retries

- A retry strategy is the combination of the operation, its inputs and parameters, and the execution approach. Never automatically repeat a failed operation with the same inputs, parameters, and strategy.
- After a failure, read-only checks are allowed to diagnose the cause and determine whether the operation produced partial or external state.
- A corrected retry may proceed without additional authorization only when all of the following are true:
  - the original operation was already authorized;
  - the failure produced no dangerous partial state or ambiguous external state;
  - the cause is understood;
  - the input has been corrected or the new approach is materially different;
  - the retry preserves the same scope, permissions, and risk level; and
  - the retry is not destructive.
- A trivial formatting or syntax error, stale context, or a known unmet precondition may be corrected and retried under the existing authorization when all retry conditions above hold. When useful, briefly report the cause and the corrected path without turning a recoverable error into a mandatory interruption.
- Count consecutive failed strategies, not command executions. The original failed strategy counts as the first. After three distinct strategies fail without material progress, stop, summarize what was tried, and ask the user for direction. Reset the counter when a strategy makes material progress or when the blocking condition materially changes.
- Stop immediately, even before three failed strategies, when partial state or external state may be ambiguous, the cause remains unclear, the next attempt expands scope or requires new permissions, the next attempt is destructive, or the failure requires a user decision.
- Failure recovery never grants new authority. It must not introduce an unauthorized write, bypass an approval gate, expand the target or scope, increase permissions or risk, or authorize a destructive action.

| Scenario | Required decision |
|---|---|
| Repeat the same failed command with the same inputs, parameters, and strategy | Prohibited |
| A patch fails because its context is stale; the target is reread and the patch is rebuilt against current content | Allowed when every corrected-retry condition holds |
| A syntax or formatting error is diagnosed and the invocation is corrected | Allowed when every corrected-retry condition holds |
| A third distinct consecutive strategy fails without material progress | Stop, summarize the three strategies, and ask for direction |
| The failed operation may have produced partial or ambiguous state | Stop immediately and inspect or request direction; do not retry |

- Every apply-mode script run writes a `.log` file (see Script conventions). These logs are the audit trail for brain writes; do not delete them until the user has verified the changes are correct.
- If the brain's `AGENTS.md` or `BRAIN.md` define rules that conflict with these instructions, follow the brain's own rules.
