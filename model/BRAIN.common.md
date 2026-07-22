# BRAIN.common.md

## Purpose
- This file is the shared operating guide for how compatible Obsidian brains can be structured and maintained.
- Local `AGENTS.md` is the always-on guardrail; local `BRAIN.md` holds brain-specific workflow details and should reference this common model when appropriate.
- This is a preferred normalized model, not merely a lowest-common-denominator description. Local brains may diverge, but divergence should be explicit in local entrypoints.

## Design goals
- Keep the brain useful as a second brain: easy to update, easy to query, easy to resume after interruptions.
- Separate active work from consolidated knowledge.
- Preserve information during reorganization.
- Keep context small at the top level and load deeper context only when needed.
- Favor simple Markdown-first workflows that Obsidian can manage well.
- Make brains that use this common model similar enough that shared scripts, procedures, jobs, and the `obsidian` skill can operate predictably across them.

## Installing common into an existing brain
- Before relying on common workflows, run a conservative brain standardization pass when the brain structure is unclear or inherited.
- The normalization pass should inspect the existing brain, propose a safe information-maturity structure, and migrate in phases with zero knowledge loss.
- The preferred destination structure is `INBOX/`, `WIP/`, `JOURNAL/`, `MEMORY/`, `BACKLOG/`, `REPORTS/`, `TEMPLATES/`, `SCRIPTS/`, and `QUARANTINE/` where needed.
- The user may choose local divergences, but those divergences should be documented in local `AGENTS.md` or `BRAIN.md` so agents do not assume the default common structure blindly.

## Information maturity model
- Use this distinction consistently:
  - `JOURNAL` = what happened, by date.
  - `WIP` = what is live right now.
  - `MEMORY` = what has been consolidated for future reuse.
  - `ARCHIVED` = what was consolidated but is no longer active or has become historical reference.
  - `BACKLOG` = future work, ideas, and initiatives not active enough for WIP.
  - `INBOX` = fresh capture and not-yet-classified notes.
  - `REPORTS` = views, summaries, or derived outputs.
- Avoid mixing these layers unless there is a clear reason.

## Operational top-level directories
- Some top-level dirs are operational, not content. They are created and maintained by `obsidian-brain-common` tooling and are not part of the information maturity model.
- `_COMMON` — symlink to the shared `obsidian-brain-common` repository.
- `_STAGING` — transitional area created by `brain_setup.py` during initial reorganization. Drained area by area via `/obsidian init`.
- `_AGENTS` — on-demand home for agent runtime configuration kept inside the brain (e.g. a `CLAUDE/` directory referenced by external symlinks under `~/.claude/`).
- The `_` prefix marks these dirs as operational. They are never considered candidates for reorganization, MEMORY promotion, or BACKLOG triage.

## ARCHIVED
- `ARCHIVED/` holds consolidated knowledge that is historically important but no longer active or relevant to current work.
- Content moves to `ARCHIVED/` when it becomes clear that it will not be referenced actively anymore, but discarding it would lose valuable context (e.g., deprecated tools, old projects, historical decisions).
- Expected structure mirrors `MEMORY/`: `ARCHIVED/Projects/`, `ARCHIVED/Tools/`, `ARCHIVED/People/`, etc., preserving the organizational context from which it was archived.
- Use `ARCHIVED/` as the final destination instead of `QUARANTINE/TRASH/` when the material is definitively complete, stable, and worth preserving as historical reference.
- Notes should be moved from `MEMORY/` to `ARCHIVED/` using `git mv` to preserve their history. Optionally add a dated comment at the top of archived notes (e.g., `<!-- Archived 2026-05-22 -->`) to mark when they were moved.
- `ARCHIVED/` is not a staging area; do not use it for uncertain or incomplete material. Uncertain material belongs in `QUARANTINE/` until its disposition is clear.
- Regular maintenance jobs should check `ARCHIVED/` periodically and flag content that has become dead links or references broken external resources, but should not delete content automatically.

## _AGENTS
- `_AGENTS/` holds brain-internal directories that act as the source of truth for an external agent runtime (Claude Code, Codex, Anthropic Agents SDK, etc.) via symlinks rooted in the user's home (`~/.claude`, `~/.codex`, `~/.agents`).
- Each subdirectory uses the runtime's natural folder name as it lived at the brain root before installation (for example `_AGENTS/CLAUDE/`).
- Population is on-demand: `brain_setup.py` creates `_AGENTS/` only when external symlinks pointing into the brain are detected, and moves the affected top-level dirs into it.
- The brain stays the source of truth for these configurations; external runtime homes hold only symlinks pointing here. This keeps runtime config versioned with the brain and portable across machines.
- Do not mix `_AGENTS/` with content layers. Agent runtimes evolve on their own cadence and may rewrite their own configuration; isolating them avoids polluting `MEMORY/`, `WIP/`, or `JOURNAL/`.
- Files inside `_AGENTS/<runtime>/` should be location-agnostic. Avoid embedding the file's own absolute brain path inside its content (e.g. header lines like "Source: …/_AGENTS/<runtime>/<this-file>") — the filesystem (via symlinks rooted in `~/.<runtime>/`) is the canonical source of truth for the runtime↔brain relationship, and embedded paths break on every future rename or move.
- Top-level Markdown files inside `_AGENTS/<runtime>/` should use the suffix `*.runtime.<runtime>.md` (e.g. `CLAUDE.runtime.claude.md`, `README.runtime.codex.md`) to keep basenames unique across runtimes and avoid collisions with brain notes that Obsidian indexes by basename.

## JOURNAL
- `JOURNAL/` is the home for daily notes / bitácora.
- Treat it as the historical record of what happened on a given day: progress, decisions, blockers, and next actions.
- Preferred convention: current-year daily notes stay directly under `JOURNAL/`; closed years are archived under `JOURNAL/<year>/`.
- Daily notes should be created from the daily template as-is, then filled with meaningful activity as it happens. Pre-filled fields should be used only by explicit workflows that need them.
- The daily-note shape (sections, scaffolding) is defined in `TEMPLATES/Daily Note Template.md`; operational rules for organizing and cleaning daily notes (project uniqueness, cleanup timing, session tracking) live in `RULES-DAILY-NOTES.md`.
- Significant work on a note should be referenced from the daily note for that day, so JOURNAL acts as the historical record of when a note was actively worked on.
- Work belongs to the day it was actually done, not to the day the session was opened.
- If a session spans multiple days, each day’s daily note should only contain work executed on that specific day.
- Empty template action categories should be cleaned when a day is closed, while preserving real content and metadata. Remove only clearly useless template noise: empty category bullets and static legends, while preserving real content and metadata.
- When creating a new daily note, update the previous existing daily note so its "next" link points to the new note, and the new note links back to the previous one.
- Daily-note cleanup belongs to the end-of-day process, not to initial note creation.
- If today's daily note does not exist yet, treat that as a trigger to review whether the previous day still has pending session consolidation or end-of-day cleanup before starting the new day.
- This trigger should behave as a pre-check, not as a blind destructive automation: unresolved carry-over should be reviewed first, then the new daily note can be created or the carry-over can be explicitly postponed.

## WIP
- `WIP/` should be the main entrypoint for active work.
- New work can start in `WIP/` immediately.
- `WIP/WIP.md` should answer, with minimal context, what is active now, what is blocked, what is next, and why each referenced note matters right now.
- The top-level WIP must stay compact; it is a dashboard, not the full archive.
- Each active project or context should have its own WIP note with enough context to resume quickly: what it is, why it matters now, recent progress, blockers if any, and next useful step.
- Project-specific tasks should usually live with that project’s WIP, not only in a global backlog.
- `WIP/` should stay limited to work that is actually active now or clearly blocked but still live.
- Moving a note into `WIP/` is not enough by itself; `WIP/WIP.md` should also be updated so future sessions can understand why that note is active without opening it first.

### Optional capabilities
- Optional tools and integrations are disabled by default. A vault or project opts in by linking a capability registry or descriptor directly from its project-specific entry in `WIP/WIP.md`.
- The dashboard link is the activation and discovery contract. A directory or note that exists without an active dashboard link is dormant.
- Capability registries stay compact and point to project descriptors. Generated or heavy assets live outside the brain and project checkout; descriptors record their external location and freshness.
- Graphify uses `WIP/GRAPHIFY/graphify.registry.md` plus one Obsidian-safe `graphify.<project-or-graph>.md` descriptor per generated graph. The detailed contract is in `RULES-OPTIONAL-CAPABILITIES.common.md`.
- Installing a capability does not register a project. Enrollment, asset generation, and project-native hooks always require explicit user intent.

### Minimal generic WIP note
- Start with one generic WIP shape that works for projects, trips, admin issues, or other active contexts.
- The note should stay lightweight and answer these questions quickly:
  - What is this?
  - Why does it matter now?
  - What is blocked?
  - What is the next useful step?
- Recommended initial sections:
  - `# Summary` — one short explanation of what the note is about.
  - `## Now` — current focus and most recent meaningful progress.
  - `## Blockers` — things preventing progress.
  - `## Next steps` — short actionable list to resume quickly.
  - `## References` — related notes, links, documents, or external systems.
- Avoid over-designing the first template. Plain Markdown is preferred over heavy metadata.

### Session memory
- Keep temporary session-memory notes to preserve active decisions, assumptions, and handoff context between sessions.
- This is operational context, so it belongs with WIP, not MEMORY.
- Store session notes in `WIP/SESSIONS/`.
- Use date-first filenames with an additional unique identifier, for example `YYYY-MM-DD-session-01-topic.md`.
- `WIP/WIP.md` is the shared operational dashboard; session notes are temporary support files for one specific session.
- Multiple sessions may exist in parallel, so do not rely on a single shared `CURRENT_SESSION.md` file.
- Session lifecycle procedures should live in `RULES-SESSION-LIFECYCLE.md`; update that rule when changing how sessions are started, rolled over, consolidated, or closed.

### Objectives tracking (optional)
- A brain may keep a `WIP/OBJECTIVES.md` hub note listing recurring objectives that should stay top-of-mind across days (performance-framework items, personal habits, cross-team practices, etc.).
- The content is brain-specific (it depends on role, performance cycle, personal goals); the *structure* is common: a flat list of `[[Objective name]]` wiki-links with a short "why" and a short "how to evidence" line.
- Objectives evolve in `WIP/OBJECTIVES.md` (add/remove/refine over time). Daily evidence of progress is recorded in the daily note under `# Actions` → `* [[OBJECTIVES]]:` per `RULES-DAILY-NOTES.md`.
- When the brain has no `WIP/OBJECTIVES.md`, the `[[OBJECTIVES]]` item in the daily template stays empty and gets cleaned up like any other empty action category.
- When the brain *does* have `WIP/OBJECTIVES.md`, "what should I work on?" / WIP triage answers can surface objectives as candidate tasks (talk to other teams, document something, exercise, etc.) alongside project work.

### Review evidence (optional)

- A brain may keep a **continuous evidence store** under `WIP/evidence/`: self-contained atomic notes capturing accomplishments, feedback, incidents, and learnings as they happen. Reports (brag, feedback, complaint) are generated on demand by filtering the store, then curated by the human.
- The conventions for the store and reports (naming, lifecycle, sensitivity, attachment handling, daily capture) live in `RULES-REVIEW-EVIDENCE.common.md`. The procedural guides live in `TASK_TYPES/evidence-management.common.md` (the store), `TASK_TYPES/brag-report.common.md`, `TASK_TYPES/feedback-report.common.md`, and `TASK_TYPES/complaint-report.common.md` (the reports).
- The daily note is the capture surface: three action categories (`* [[BRAG]]:`, `* [[FEEDBACK]]:`, `* [[COMPLAIN]]:` — see `TEMPLATES/TEMPLATE.daily-note.common.md`) hold one-line stubs that are harvested into atomic evidence notes. These are the backward-looking counterpart of `* [[OBJECTIVES]]:`.
- Evidence notes are permanent and append-only. Reports are transient: generated in `WIP/`, curated, shared, then moved to `ARCHIVED/Reviews/` via `git mv` when the cycle closes. Reports tagged `sensitive` (complaint reports) stay in `WIP/` unless the user explicitly decides to archive them, because retention may be governed by HR policy.
- People referenced by evidence and reports live in `MEMORY/People/`; notes link to people notes via the `people:` frontmatter field so the people notes accumulate a review history through backlinks.

## BACKLOG
- `BACKLOG/` holds ideas, initiatives, investigations, and future work that is not active enough for `WIP/` yet.
- `BACKLOG/` may initially look messy, but it should still be cleaner than `INBOX/` and more intentional than raw capture.
- Promote notes from `BACKLOG/` into `WIP/` only when they become active enough to deserve immediate context and next-step tracking.

## MEMORY
- `MEMORY/` should hold consolidated knowledge that is no longer just active scratch work.
- Expected areas include topics such as Projects, Clients, People, Tools, Providers, Inventory, Services, and Infrastructure.
- Content belongs in MEMORY when it is stable enough to be useful for future retrieval beyond the current task.
- MEMORY should favor clarity and reuse over raw chronology.
- If a project clearly belongs to a client, prefer storing it under that client context instead of in a global projects area.
- Use generic project/client/service areas only when the context is clearly general, personal, or not tied to a more specific owner.
- A normalization pass should propose a concrete `MEMORY/` structure for the brain, usually including areas such as Clients, Projects, People, Tools, Providers, Inventory, Services, Infrastructure, or other locally meaningful domains.
- Use `MEMORY/Providers/` for external suppliers and vendors, such as registrars, SaaS providers, infrastructure providers, banks, utilities, or professional services.
- Use `MEMORY/Inventory/` for operational asset catalogs that must be easy to audit, such as domains, subscriptions, licenses, certificates, renewals, hardware assignments, or other owned assets.
- Keep `MEMORY/Services/` for internal, self-hosted, or organization-operated services, not for the external provider companies behind them.
- Keep provider-owned evidence and contracts next to the provider note when the document primarily explains the supplier relationship; link from inventories when the same document supports an asset entry.
- General consolidated canvas files should live in `MEMORY/CANVAS/`.
- A canvas that is still being created or actively worked should stay in `INBOX/` or `WIP/` until its final home is clear.
- If a canvas belongs clearly to one specific context, prefer keeping it next to that context instead of in the generic `MEMORY/CANVAS/` area.

## TASK_TYPES
- `TASK_TYPES/` holds **how-to-approach** guides for recurring task types — knowledge organized by the kind of work being done rather than by domain (Tools / Projects / Services / People).
- This is a content layer distinct from existing ones:
  - **vs `TEMPLATES/`**: TEMPLATES define the shape of a single note; TASK_TYPES describe the procedure for a kind of work, and may inline a suggested note shape as one of their sections.
  - **vs `RULES-*.md`**: RULES are brain-operational (how to keep the brain consistent and well-formed); TASK_TYPES are domain-task-operational (how to approach a kind of work that uses the brain).
  - **vs `MEMORY/Tools/<tool>.md`**: tool notes are passive references about a tool; task-type notes are active procedural guides about a kind of work that may combine multiple tools, services, and projects.
  - **vs skills**: skills are runtime-loaded action sequences executed by an agent runtime (Claude Code, Codex, etc.); TASK_TYPES notes are informational guides that any agent can read. A task-type may be **promoted to a skill** when it becomes procedurally rich enough to deserve automated invocation.
- The expected access pattern is index-first: agents scan a tiny index at session start, then deep-read the specific note only when the current task matches one of the listed types.

### Index

- `TASK_TYPES/TASK_TYPES.md` is the always-loadable index. One line per task-type, with a short description and a `[[wikilink]]` to the note.
- Keep the index tight. Add or trim entries when task-types are introduced or retired; do not let it accumulate stale entries.
- The agent runtime / skill should load this file as part of the normal brain-connect step (alongside `AGENTS.md`, `BRAIN.md`, `WIP/WIP.md`), so the catalog is available without explicit search.

### Note shape

Each `TASK_TYPES/<task-type>.md` should follow this structure:
- **When this applies** — concrete trigger conditions; what the user is doing when this guide should kick in.
- **Before starting** — pre-requisites and external coordination (e.g. queue reservation, branch from updated master, VPN, approvals).
- **Process** — the steps that matter; anchored on what is easy to miss, not exhaustive.
- **Note shape** (optional) — suggested structure for the deliverable note, if the task produces one.
- **Common gotchas** — known pitfalls and their workarounds.
- **References** — `[[wikilinks]]` to `MEMORY/Tools/`, `MEMORY/Services/`, `MEMORY/Projects/`, related task-types, external docs, and any related skills.

### Promotion to skill

When a task-type guide becomes rich enough that an agent should execute it (action sequences with confirmation gates, persistent state to track, etc.), promote it to a `SKILL.md`:
- Live home: `_AGENTS/<runtime>/skills/<name>/SKILL.md` so it can be symlinked into runtime homes like `~/.claude/skills/<name>/`.
- The TASK_TYPES index keeps a pointer entry pointing at the skill instead of (or alongside) the markdown guide.

### Common vs brain-local

Task-types follow the same wrapper convention as RULES and AGENTS (see `AGENTS.common.md` → "Wrapper convention"):

- Common content lives in `_COMMON/TASK_TYPES/<name>.common.md`. The index is `_COMMON/TASK_TYPES/TASK_TYPES.common.md`.
- `brain_setup.py` discovers each `*.common.md` and creates a thin wrapper at `<brain>/TASK_TYPES/<name>.md`.
- Brain-only task-types (no common counterpart) live directly at `<brain>/TASK_TYPES/<name>.md` and are listed in the brain index under "Additional local task-types".

Promote a brain-local task-type to common when its procedure is generic enough that the same content would apply unchanged in a different brain.

## INBOX
- `INBOX/` is the central capture area for newly created or not-yet-classified notes.
- Notes should not stay in `INBOX/` longer than necessary; they should be re-homed into `WIP/`, `MEMORY/`, client/project areas, or moved to `QUARANTINE/TRASH/` only if they are confirmed empty or accidental.
- Reviewing `INBOX/` should be part of normal maintenance, especially daily/session consolidation.
- `INBOX/LEGACY/` is the place for inherited, older dump-style notes that still need slow extraction and triage.
- `INBOX/` itself should stay clean and functional for fresh capture, while `INBOX/LEGACY/` can hold older material that has not yet been digested.

## Attachments
- Attachments should move together with the notes they clearly belong to whenever those notes are reorganized.
- Preferred convention: attachments live near their owning notes, typically in local `ATTACHMENTS/` folders controlled by Obsidian settings and cleanup scripts. This setting is primarily an organizational rule for creation, not a hard requirement for later link resolution.
- If attachment ownership is already clear while reading and moving a note, move the attachment at the same time as the note.
- If attachment ownership is not resolved during note reorganization, defer that case to deterministic maintenance tooling instead of guessing manually.
- Reorganizing a note should include checking its linked attachments and moving them with traceability when ownership is clear.
- Never delete attachments automatically during reorganization.
- Potential orphaned attachments should be moved to `QUARANTINE/ATTACHMENTS/` for manual review rather than deleted.
- Conflicts such as duplicate filenames, one attachment referenced from multiple notes in different locations, or ambiguous ownership should be reported and left unresolved until reviewed explicitly.
- After a folder has been fully reorganized, review any remaining `ATTACHMENTS/` contents there to determine whether they are still valid local attachments, were missed during migration, or are potential orphans.

## TODO and backlog handling
- Avoid recreating a giant undifferentiated TODO area.
- Active work belongs in `WIP/`.
- Non-active future initiatives and ideas belong in `BACKLOG/`.
- Older dump-style material that still needs slow extraction should live in `INBOX/LEGACY/` until it is processed.
- Prefer separating fresh capture (`INBOX/`), future initiatives (`BACKLOG/`), and active work (`WIP/`).

## Note naming (basename uniqueness for Obsidian wikilinks)

- Obsidian resolves `[[wikilinks]]` by **basename**, not by full path. Two notes with the same basename in different folders produce ambiguous or wrong wikilink resolution.
- When grouping related files inside an identifying folder (e.g. `WIP/demo-may-1-22/`, `WIP/<project>/<ticket>/`, an attached-folder ticket per `RULES-FILE-NAMING.md`), the **filenames inside still need to be identifying and ideally unique brain-wide**. Use the folder name as a prefix on each contained file's basename.
- Example — *wrong* (basenames collide across folders):
  ```
  WIP/demo-may-1-22/{estado,script}.md + deck.html
  WIP/demo-jun-3-15/{estado,script}.md + deck.html   ← ambiguous wikilinks
  ```
- Example — *right* (each basename is identifying):
  ```
  WIP/demo-may-1-22/{demo-may-1-22_estado.md, demo-may-1-22_script.md, demo-may-1-22_deck.html}
  WIP/demo-jun-3-15/{demo-jun-3-15_estado.md, demo-jun-3-15_script.md, demo-jun-3-15_deck.html}
  ```
- The same principle applies to facets per ticket (`plan/decisiones/analisis/estado.md` are basenames that DO collide across tickets — they only work because Obsidian wikilinks to them are typically scoped via context or use the relative-path form `[[../<ticket>/estado|estado]]`). For new conventions, prefer unique basenames by default; reserve the bare-facet form for cases where wikilinks always carry the path.
- See also: file naming patterns and the "folder with same-named file" promotion rule in [`RULES-FILE-NAMING.md`](RULES-FILE-NAMING.md). The ticket-folder pattern there (`TICKET_ID - SHORT_DESCRIPTION/TICKET_ID - SHORT_DESCRIPTION.md`) follows this principle — the inner note carries the ticket ID, not a bare `note.md`.

## TEMPLATES
- `TEMPLATES/` is an operational Obsidian folder.
- Do not rename or move it until local `.obsidian` configuration is verified.
- Favor simple templates that support the agreed workflow instead of template-heavy complexity.
- Obsidian-facing templates should live in local `TEMPLATES/`; common automation/process templates may live under `_COMMON/TEMPLATES/` and be symlinked into local `TEMPLATES/` only when intentionally exposed to Obsidian.
- Preferred local Obsidian configuration should point template creation to `TEMPLATES/`, unless the local brain explicitly documents another setup.
- The daily note template should stay minimal: keep only `tags` in frontmatter and track meaningful activity in the body. Contabilizable/facturable work belongs under `# Actions` → `* [[WORK]]:`, organized by project/context per `RULES-DAILY-NOTES.md`.

## Preferred Obsidian configuration direction
- New notes should preferably be captured into `INBOX/` so they can be reviewed and re-homed intentionally.
- Daily notes should preferably live in `JOURNAL/` using the common daily-note lifecycle rules.
- Templates should preferably live in `TEMPLATES/`.
- Attachments should preferably be created near the current note or in a predictable local `ATTACHMENTS/` folder, then maintained by attachment ownership rules.
- These are desired target conventions. If a brain's `.obsidian` settings differ, document that locally and avoid changing `.obsidian/` without explicit user approval.

## JOBS
- `JOBS.md` follows the structure defined in `_COMMON/JOBS.common.md`: sections for Daily, Session consolidation, Weekly, Monthly, and Yearly routines, each with Purpose, Trigger, and Tasks.
- Local wrappers may add brain-specific tasks. Execution state is recorded in a separate local `JOBS_LOGS.md`, not in `JOBS.md` itself.
- Session consolidation should be a separate manual routine from daily/end-of-day closure.
- Session consolidation may run multiple times in one day and should be idempotent.
- Jobs should be lightweight checklists with minimal execution state so future sessions can tell whether a routine already ran and whether rerunning needs confirmation.

## SCRIPTS
- `SCRIPTS/` holds deterministic common lifecycle scripts for setup/update/check-style operations.
- Runtime skill tools live under `SKILLS/obsidian/scripts/` and are exposed through installed agent runtimes, for example attachment audits, canvas repair, related-note lookup, and session bootstrap.
- Prefer scripts over LLM-driven procedures when the rules are stable enough to be codified.

## QUARANTINE
- `QUARANTINE/` holds items that need manual review before deciding their final disposition.
- `QUARANTINE/ATTACHMENTS/` is the destination for potential orphaned or ambiguous attachments found during reorganization or maintenance.
- `QUARANTINE/TRASH/` is the standard destination for notes or files that look safe to discard but must not be deleted automatically.
- `QUARANTINE/TRASH/` preserves traceability: move candidates there with `git mv`, record why they were moved, and let the user decide whether to delete them permanently later.
- Never delete quarantined items automatically; they require explicit human review.

## REPORTS
- `REPORTS/` can hold reporting / views / generated summaries that may depend on existing Obsidian plugins or queries.
- Do not reorganize it blindly.
- First understand which notes, plugins, or generated views depend on it.
- If a report belongs clearly to one specific context (client, project, etc.), prefer keeping it next to that context instead of in the generic `REPORTS/` area.

## Reorganization rules
- No information loss.
- Prefer move/rename/link/consolidate over delete.
- Agents must not delete brain content as a cleanup action. If something appears discardable, move it to `QUARANTINE/TRASH/` with `git mv` and document the reason.
- Preserve traceability when moving notes so prior knowledge can still be found.
- Reorganize in phases: define model, map current state, create destination structure, migrate carefully, then clean up only when safe.
- When moving notes in ways the user will review through Git, prefer `git mv` to preserve clearer traceability.
- When a source directory becomes empty after consolidation, remove it with a safe non-recursive directory removal rather than a cascading delete.

## Working model for future sessions
- Start from `WIP/WIP.md` once that structure exists.
- Use `WIP/SESSIONS/` for temporary per-session context.
- For project work, load the relevant project-specific WIP note instead of the whole brain.
- At the start of a session or day rollover, load `RULES-SESSION-LIFECYCLE.md` and follow its scenario logic.
- Review `INBOX/` as part of normal capture/consolidation flow and re-home notes when their proper destination is clear.
- Record meaningful day progress in `JOURNAL/`.
- Use session consolidation to push session outputs into WIP, JOURNAL, and MEMORY without assuming the day is finished.
- Use the Daily job only when the day itself should be considered closed.
- Promote lasting insights from WIP or JOURNAL into `MEMORY/` when they become reusable knowledge.
- When asked “where were we?” or “what next?”, answer from WIP first, then use JOURNAL and project notes to fill gaps.
