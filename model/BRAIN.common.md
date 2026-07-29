# BRAIN.common.md

## Purpose
- This file is the shared conceptual structure guide for compatible Obsidian brains.
- Local `AGENTS.md` is the always-on operational guardrail. Local `BRAIN.md` may add brain-specific workflow details and should reference this common model when appropriate.
- This model describes preferred information architecture. Local brains may diverge, but divergence should be explicit in local wrappers.

## Design goals
- Keep the brain useful as a second brain: easy to update, query, and resume.
- Separate active work from consolidated knowledge.
- Preserve information during reorganization.
- Keep top-level context compact and load deeper guidance only when a task needs it.
- Favor Markdown-first structures that Obsidian and deterministic tools can maintain.
- Keep common brains similar enough that shared rules, jobs, scripts, and the `brain` skill can operate predictably.

## Canonical Operational Links
| Topic | Canonical owner |
|---|---|
| Session lifecycle and day/session transitions | [`RULES-SESSION-LIFECYCLE.common.md`](RULES-SESSION-LIFECYCLE.common.md) |
| Daily note shape, cleanup timing, and action categories | [`RULES-DAILY-NOTES.common.md`](RULES-DAILY-NOTES.common.md) |
| File naming, basename identity, and issue-note naming | [`RULES-FILE-NAMING.common.md`](RULES-FILE-NAMING.common.md) |
| Links and wikilink conventions | [`RULES-LINKS.common.md`](RULES-LINKS.common.md) |
| Optional capability activation and storage boundaries | [`RULES-OPTIONAL-CAPABILITIES.common.md`](RULES-OPTIONAL-CAPABILITIES.common.md) |
| Review evidence and report lifecycle | [`RULES-REVIEW-EVIDENCE.common.md`](RULES-REVIEW-EVIDENCE.common.md) |
| Attachment ownership and quarantine handling | [`RULES-ATTACHMENTS.common.md`](RULES-ATTACHMENTS.common.md) |
| Issue working-doc procedure | [`RULES-ISSUE-DOCS.common.md`](RULES-ISSUE-DOCS.common.md) |
| Recurring maintenance routines | [`JOBS.common.md`](JOBS.common.md) |

## Information Maturity Model
- `INBOX` = fresh capture and not-yet-classified notes.
- `WIP` = live work, active dashboards, session context, and temporary operational memory.
- `JOURNAL` = dated record of work, decisions, blockers, and progress.
- `MEMORY` = consolidated knowledge intended for future reuse.
- `BACKLOG` = future work, ideas, and initiatives not active enough for WIP.
- `ARCHIVED` = historical consolidated knowledge that is no longer active.
- `REPORTS` = views, summaries, or derived outputs.
- `OUTBOX` = generated deliverables awaiting user collection or external delivery.
- Avoid mixing these layers unless a local wrapper documents why.

## Operational Top-Level Directories
- `_COMMON/` points at the shared common model consumed by local wrappers.
- `_STAGING/` is a transitional area for migration work and is not a durable knowledge layer.
- `_AGENTS/` may hold brain-internal runtime configuration sources, isolated from content layers.
- Directories with a leading underscore are operational. They are not candidates for MEMORY promotion, BACKLOG triage, or ordinary note reorganization.

## Content Directories
- `INBOX/` is the central capture area. Use `INBOX/LEGACY/` for inherited dump-style material that needs slow extraction.
- `WIP/` is the main entrypoint for active work. `WIP/WIP.md` is a compact dashboard, not a full archive.
- `WIP/SESSIONS/` holds temporary per-session memory. Session notes support continuity until durable state has been consolidated.
- `JOURNAL/` is the dated historical record. Work belongs to the day it was actually done.
- `MEMORY/` holds reusable knowledge. Common areas include Projects, Clients, People, Tools, Providers, Inventory, Services, Infrastructure, and Canvas material.
- `BACKLOG/` holds non-active future initiatives and ideas.
- `ARCHIVED/` preserves no-longer-active knowledge that should remain available as historical reference.
- `REPORTS/` holds generated or curated views that depend on existing notes, plugins, or queries.
- `OUTBOX/` is one-way egress and remains visible to Git. Nothing is ingested or promoted from it; material returning from outside always re-enters through `INBOX/`.
- `QUARANTINE/` holds material that needs human disposition before a final home is chosen.

## WIP Relationships
- Project-specific WIP notes carry enough context to resume: what the work is, why it matters now, recent progress, blockers, and next useful step.
- Session notes are temporary support files for one active or recently interrupted session. They are operational context, not long-term MEMORY.
- `WIP/OBJECTIVES.md`, when present, is a local hub for recurring objectives. Daily evidence links back to those objectives through the daily-note rules.
- `WIP/evidence/`, when present, is the continuous evidence store. Reports are derived from it and follow the review-evidence rule.
- Optional capability registries or descriptors are active only when the relevant WIP dashboard entry links to them.

## TASK_TYPES
- `TASK_TYPES/` contains how-to-approach guides organized by kind of work rather than by domain.
- `TASK_TYPES/TASK_TYPES.common.md` is the compact catalog. Load the specific task-type note only when the current task matches it.
- Task-type guides describe procedure. Templates define artifact shape. Rules define operational constraints. Skills define runtime action sequences.
- Brain-local task-types may exist beside common wrappers when the procedure is not generic enough for the shared model.

## TEMPLATES
- `TEMPLATES/` is the Obsidian-facing template folder.
- Common templates live under `_COMMON/TEMPLATES/` and may be exposed through local wrappers or managed links.
- Template files should remain shape-focused. Lifecycle and policy live in their canonical rules.

## Attachments
- Attachments are binary or external-support material associated with notes.
- Local `ATTACHMENTS/` folders and `QUARANTINE/ATTACHMENTS/` are structural homes; ownership, movement, conflicts, and deletion constraints live in the attachment rule.
- Evidence-specific attachments are part of the review-evidence model and should remain connected to the evidence notes or reports they support.

## JOBS
- `JOBS.md` is the local recurring-maintenance surface.
- The common job model defines purpose, trigger, and task group semantics for Daily, Session consolidation, Weekly, Monthly, and Yearly routines.
- Job execution state belongs in local logs or notes, not in the common structure guide.

## SCRIPTS
- `SCRIPTS/` contains deterministic lifecycle scripts for setup, update, check, and maintenance support.
- Script-operation semantics belong to [`SCRIPTS/README.scripts.common.md`](SCRIPTS/README.scripts.common.md) and the `SCRIPT.*.common.md` owners.

## Reorganization Semantics
- Reorganization is no-loss information modeling across maturity layers, canonical owners, links, and quarantine boundaries.
- Folder moves, note renames, attachment handling, traceability, cleanup, and discard decisions are operational policy owned by the canonical rules linked above.

## Common vs Brain-Local
- Common content lives under `_COMMON/` and is consumed through thin local wrappers.
- Local wrappers inherit, add, override, or replace common sections without duplicating common content verbatim.
- Promote local structure or task-types to common only when the same guidance would apply unchanged in another brain.
