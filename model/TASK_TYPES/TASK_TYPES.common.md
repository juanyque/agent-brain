# TASK_TYPES
<!-- content-boundary: {"kind":"task-index","owner":"model/TASK_TYPES/TASK_TYPES.common.md"} -->

How-to-approach guides for recurring task types. When the current task matches one of the entries below, deep-read the corresponding note before starting. See `BRAIN.common.md` → "TASK_TYPES" for the model.

## Contract

`TASK_TYPES/` holds how-to-approach guides for recurring task types. It organizes knowledge by kind of work, not by domain folders such as Tools, Projects, Services, or People.

- Templates define the shape of a single note. Task-type guides describe the procedure for a kind of work and may point to a template or include a suggested note shape as one section.
- Rules define brain-operational constraints. Task-type guides define domain-task procedure for work that uses the brain.
- Tool notes are passive references about a tool. Task-type guides are active procedural references for work that may combine multiple tools, services, projects, and skills.
- Skills are runtime-loaded action sequences. Task-type guides are Markdown references any agent can read.

## Index

The index is intentionally compact: one line per task-type, with a short description and a wikilink to the guide. Keep entries current as task-types are introduced or retired.

## Guide Shape

Each `TASK_TYPES/<task-type>.md` guide should include:

- **When this applies** — concrete trigger conditions.
- **Before starting** — prerequisites and external coordination.
- **Process** — the steps that matter, focused on what is easy to miss.
- **Note shape** — optional suggested structure for the deliverable note.
- **Common gotchas** — known pitfalls and workarounds.
- **References** — wikilinks to related memory notes, task-types, templates, external docs, and skills.

## Promotion to skill

Promote a task-type guide to a skill when it becomes procedurally rich enough for an agent runtime to execute, such as when it needs confirmation gates, persistent state, or deterministic action sequencing. Keep the TASK_TYPES index pointing at the guide, the promoted skill, or both while the transition is active.

## Common vs brain-local

Common task-types live under `_COMMON/TASK_TYPES/` and brain-local wrappers expose them at `<brain>/TASK_TYPES/`. Brain-only task-types live directly in the brain's `TASK_TYPES/` folder and are listed in the local index under local task-types.

Promote a brain-local task-type to common only when the same procedure would apply unchanged in another brain.

## Entries

- [[basename-collision-cleanup]] — Resolve `*.md` basename collisions in an Obsidian vault using `check_basename_collisions.py` (detector + per-file attribution + auto-rename + interactive review for referenced files). The naming policy is owned by `RULES-FILE-NAMING.common.md`.
- [[dead-code-detection]] — Systematic identification of dead code (unused imports, unreferenced symbols, unreachable code, invalid tests) with explicit confidence per finding and a false-positives-excluded section.
- [[test-coverage-analysis]] — Decide which tests to create, redo, or eliminate. Typically a prerequisite for sensitive upgrades (language version, framework major bump).
- [[evidence-management]] — Maintain the continuous evidence store (`WIP/evidence/`) that feeds all review reports. Covers the atomic-note schema, daily capture-and-harvest cycle, and backfill protocol for historical evidence.
- [[brag-report]] — Generate a brag report from the evidence store for a date range, then curate it into a narrative for performance review. Adapted from Julia Evans's concept.
- [[feedback-report]] — Generate structured feedback for a peer (given or received) from the evidence store, filtered by person and cycle. Linked to `MEMORY/People/`.
- [[complaint-report]] — Generate a factual, dated evidence report for a complaint or escalation from the evidence store, filtered by topic. Facts separated from interpretations, `sensitive` tag mandatory.
- [[feature-development]] — Generic idea-to-review-request lifecycle (PRD, design, ADRs, adversarial verification before implementation, TDD) for environments with no broader development-lifecycle definition of their own. Draft, expect it to evolve with use.
