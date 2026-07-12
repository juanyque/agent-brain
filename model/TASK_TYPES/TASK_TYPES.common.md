# TASK_TYPES

How-to-approach guides for recurring task types. When the current task matches one of the entries below, deep-read the corresponding note before starting. See `BRAIN.common.md` → "TASK_TYPES" for the model.

## Entries

- [[basename-collision-cleanup]] — Resolve `*.md` basename collisions in an Obsidian vault using `check_basename_collisions.py` (detector + per-file attribution + auto-rename + interactive review for referenced files). Naming convention `<stem>.<parent-folder-slug>.md`.
- [[dead-code-detection]] — Systematic identification of dead code (unused imports, unreferenced symbols, unreachable code, invalid tests) with explicit confidence per finding and a false-positives-excluded section.
- [[test-coverage-analysis]] — Decide which tests to create, redo, or eliminate. Typically a prerequisite for sensitive upgrades (language version, framework major bump).
- [[evidence-management]] — Maintain the continuous evidence store (`WIP/evidence/`) that feeds all review reports. Covers the atomic-note schema, daily capture-and-harvest cycle, and backfill protocol for historical evidence.
- [[brag-report]] — Generate a brag report from the evidence store for a date range, then curate it into a narrative for performance review. Adapted from Julia Evans's concept.
- [[feedback-report]] — Generate structured feedback for a peer (given or received) from the evidence store, filtered by person and cycle. Linked to `MEMORY/People/`.
- [[complaint-report]] — Generate a factual, dated evidence report for a complaint or escalation from the evidence store, filtered by topic. Facts separated from interpretations, `sensitive` tag mandatory.
