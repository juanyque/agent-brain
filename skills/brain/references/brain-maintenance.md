# Brain maintenance workflow

The full workflow triggered by `brain init`, `brain maintain`, `brain clean`, `brain order`, `brain standardize`, or natural-language requests like "ordena el brain", "haz mantenimiento", "limpia el brain".

The user should not need to know internal tool names. The skill resolves the brain, checks setup state, chooses the correct mode, runs safe deterministic tools, and presents decisions only when human judgment is needed.

"Reversible through Git" is NOT a license to auto-apply: every `git mv` is reversible by `git reset --hard`, yet a brain crowded with 900+ undeclared renames is unusable. The narrow set of actions the skill MAY apply without explicit per-action user approval is limited to:

- Read-only scripts (`find_home.py`, `standardize_assessment.py` in dry-run, `maintenance_scheduler.py` reports).
- `home_setup.py --apply` after the user explicitly answered the setup question in step 1.
- The setup-time `.DS_Store` sweep and empty-dir cleanup and `_AGENTS/` migration, all performed by `home_setup.py` itself under that same approval.
- `cleanup_ds_store.py --apply` as a maintenance-mode pre-check — `.DS_Store` removal does not destroy information.

Everything else — including any drain batch (mechanical or content-based), creation of operational scaffolding (`WIP/WIP.md`, `STANDARDIZE_PROCESS.md`), writing of today's daily note, template consolidation, attachment moves, canvas rewrites — requires explicit user confirmation via `AskUserQuestion` immediately before the operation. Reversibility through Git is the safety net for mistakes, not an authorization for the agent to act unilaterally.

The process supports two operational modes, determined by the presence of `_STAGING`:

## 1. Mechanical setup refresh

- Resolve the brain path.
- Check whether `_COMMON` exists in the brain root.
- If `_COMMON` already exists: run an idempotent setup refresh before mode detection:
  ```bash
  python3 <common_path>/SCRIPTS/home_setup.py --brain <brain_path> --apply
  ```
  This refreshes missing wrappers/templates and synchronizes the runtime skill installation via `skill_setup.py` unless `--skip-skill` is passed. Because `_COMMON` is already attached, `home_setup.py` must not move content into `_STAGING/`; it only applies its idempotent maintenance-safe setup steps.
- If `_COMMON` does not exist, **you MUST ask the user before running `home_setup.py --apply`**. The choice between full reorder and skipping the staging sweep is a user decision, not an agent decision.
  - **Required:** invoke `AskUserQuestion` with a question equivalent to: "¿Quieres hacer una ordenación completa del brain? (mueve todo el contenido a `_STAGING/` para drenar después por áreas vía `brain init`, además de migrar runtime-tied dirs a `_AGENTS/` y crear `_COMMON` + wrappers)". Offer at least two options: full reorder (default, recommended for new brains) and skip staging sweep.
  - **Forbidden:** do not assume the user wants to skip based on brain size, number of items at root, presence of existing organization, or any other heuristic. The default is full reorder; deviating from it requires the user's explicit answer to the question.
  - **After the answer:**
    - If the user chose **full reorder** → run `python3 <common_path>/SCRIPTS/home_setup.py --brain <brain_path> --apply` (no `--skip-full-reorder`).
    - If the user chose **skip staging sweep** → run `python3 <common_path>/SCRIPTS/home_setup.py --brain <brain_path> --skip-full-reorder --apply`. Claude Code's permission system requires explicit confirmation for this invocation; surface the resulting prompt to the user transparently and proceed only if they confirm again at the prompt.

## 2. Mode detection

- If `_STAGING/` exists and has content → **Initial mode**: the brain is being reorganized from scratch. The task is to drain `_STAGING/` area by area.
- If `_STAGING/` does not exist or is empty → **Maintenance mode**: the brain has been organized before. Run assessment and propose targeted improvements.

## 3. Initial mode: drain `_STAGING/`

**Hard rule: every batch in this drain — mechanical or content — requires explicit per-batch user confirmation via `AskUserQuestion` immediately before any `git mv` is executed. Reversibility through Git is not authorization. A single `brain init` session normally moves one batch and stops; the next batch belongs to the next session (or to an explicit "continue" answer from the user).**

### 3.1. Read prior state (no user confirmation needed; read-only)

- Read `WIP/STANDARDIZE_PROCESS.md` to see where the previous session left off. If it does not exist, plan to create it as part of the first batch — do NOT write it autonomously here; the write is part of a confirmed batch.
- Inventory top-level `_STAGING/` and the rest of the brain root to understand scope sizes and shapes.
- Surface the inventory to the user as part of the next step's question; do not store decisions only in agent memory.

### 3.2. Propose the next batch (REQUIRED `AskUserQuestion` gate)

- **Required:** invoke `AskUserQuestion` describing exactly ONE batch you propose to execute. The question MUST include:
  - The scope (e.g. "Journal/ daily notes by year", "ISSUES/Card Platform International/", "root SEAR-*.md tickets").
  - The kind of moves (purely mechanical date-based / content classification / scaffolding).
  - The destinations, file counts, and the specific classification decisions implied (e.g. "I propose treating Card Platform International as active → `WIP/`. Alternative: BACKLOG/ if it's not active right now.").
  - A way to opt out: at minimum offer "proceed", "redirect (different scope/destination)", "stop here for this session".
- **Forbidden:** chaining batches without a separate `AskUserQuestion` per batch. Do not present an N-batch plan and execute it on a single approval; each batch is its own gate.
- **Forbidden:** treating "mechanical" moves (e.g. daily notes by year) as exempt. The user must approve the SCOPE of even mechanical batches.

### 3.3. Execute the approved batch (only after explicit "proceed")

- Apply only the moves the user just approved. Use `git mv` (never copy-and-delete) when the brain is a Git repository.
- Never delete content. If something looks discardable, propose `QUARANTINE/TRASH/` with rationale in the same `AskUserQuestion` and only move on "proceed".
- For `MEMORY/` destinations, propose the concrete subdirectory (e.g. `Clients`, `Projects`, `People`, `Tools`, `Services`) in the same question, not as an afterthought.
- Stop the moves at the boundary the user approved. Do not bundle in adjacent files because they "look obviously related".

### 3.4. Post-batch follow-ups (each one is its own confirmation gate)

After a batch is applied, ask separately for any of the following before executing:

- **Attachments audit** (still requires user confirmation):
  ```bash
  python3 ~/.agents/skills/brain/scripts/attachments_audit.py --brain-root <brain_path> --scope-root <scope_path> --quarantine-dir QUARANTINE/ATTACHMENTS
  python3 ~/.agents/skills/brain/scripts/attachments_audit.py --brain-root <brain_path> --scope-root <scope_path> --quarantine-dir QUARANTINE/ATTACHMENTS --apply
  ```
  Run dry-run automatically (read-only is fine), but `--apply` only after a confirmation question with the audit report attached.
- **Canvas repair** (same pattern as attachments audit):
  ```bash
  python3 ~/.agents/skills/brain/scripts/canvas_path_repair.py --brain-root <brain_path> --scope-root <scope_path>
  python3 ~/.agents/skills/brain/scripts/canvas_path_repair.py --brain-root <brain_path> --scope-root <scope_path> --apply
  ```
- **Update `WIP/STANDARDIZE_PROCESS.md`** with: files moved, destinations and rationale, tool results, unresolved items, next recommended batch. The write itself is a small confirmation (the user usually says yes, but the question states what will be recorded).

### 3.5. Stop or continue (REQUIRED `AskUserQuestion` gate)

- After the batch and its follow-ups, ask the user whether to continue with the next batch in this session or stop. Default to **stop** — drain is multi-session by design.
- If the user says continue, return to step 3.2 with a fresh inventory and a fresh batch proposal. Do not skip the proposal step.

### 3.6. Session-spanning state

- The process can span many sessions and dates. State must live in `WIP/STANDARDIZE_PROCESS.md`, never only in agent memory.
- Suggested scope order (offer as default in 3.2, let the user override): old journal area first, then active-work areas, TODO/task dumps, domain folders (`Clients`, `Projects`, `People`, `Services`, `Tools`), assets/canvas folders, then weird/sensitive leftovers.
- `_STAGING/` is complete only when empty and all unresolved decisions are recorded in `WIP/STANDARDIZE_PROCESS.md`.

### 3.7. Special case: today's daily note during drain

- The general rule (create today's daily when missing) applies in Maintenance mode. **It is overridden during this drain.**
- During the drain, do not create today's daily note autonomously. The historical record (including any pre-existing `today.md`) may be in `_STAGING/Journal/` awaiting classification, and creating a new one would risk duplicating one about to be drained.
- Defer creation until the journal scope has been drained, or until the user explicitly asks for it. If the user wants to start logging today's work mid-drain, ask whether to (a) create today's daily now in `JOURNAL/`, (b) wait until the journal scope is drained, or (c) log to an existing daily that you've already moved out of `_STAGING/`.

### 3.8. Special case: daily-note template divergence

- If the user's brain has a local `TEMPLATES/Daily Note Template.md` that differs from the common source (`_COMMON/TEMPLATES/TEMPLATE.daily-note.md`), **do not auto-resolve the divergence**. Do not symlink the common over the local, do not create today's daily note using either shape silently, do not move on.
- Surface the diff to the user and propose unification: enrich the common template with the local additions, then collapse to a single shared template via symlink. This converges runtimes across brains instead of perpetuating per-brain divergence.
- Record the divergence + unification proposal in `WIP/STANDARDIZE_PROCESS.md` as a pending decision. Do not write today's daily note until the user has resolved this.

## 4. Maintenance mode: assessment

- First run the `.DS_Store` sweep — safe noise removal, runs automatically without per-action confirmation:
  ```bash
  python3 ~/.agents/skills/brain/scripts/cleanup_ds_store.py --brain-root <brain_path> --apply
  ```
  This is one of the few maintenance actions allowed to run without a confirmation gate: removing `.DS_Store` does not destroy information. Other maintenance actions still require per-action confirmation per the header's narrow auto-apply list.
- Then run the maintenance scheduler:
  ```bash
  python3 ~/.agents/skills/brain/scripts/maintenance_scheduler.py --brain-root <brain_path>
  ```
- Present due/review recurring jobs to the user before structural cleanup. Daily, Weekly, Monthly, and Yearly routines are maintenance; Session consolidation is event-triggered and should be reviewed when relevant. Execute clearly safe routine steps automatically when the rules define them; ask for decisions when judgment is required.
- Always record every maintenance or re-verification pass in today's daily note under `# Sessions`, including force-all test runs. Use the real session id or resume command, the maintenance scope, and a short outcome summary.
- For session consolidation, load `RULES-SESSION-LIFECYCLE.md` and apply its closing gate before moving any session note out of `WIP/SESSIONS/`. If a previous note has unchecked checklist items, either leave it as `stale-follow-up` or write the explicit reason why each unchecked item does not block closure.
- Only after recurring maintenance is reviewed, run an assessment of the full brain structure in dry-run mode:
  ```bash
  python3 ~/.agents/skills/brain/scripts/standardize_assessment.py --brain-root <brain_path>
  ```
- Compare with the common target structure: `INBOX/`, `WIP/`, `JOURNAL/`, `MEMORY/`, `BACKLOG/`, `REPORTS/`, `TEMPLATES/`, `SCRIPTS/`, and `QUARANTINE/` where needed.
- Generate or update `WIP/STANDARDIZE_PROCESS.md` only after reviewing the dry-run report:
  ```bash
  python3 ~/.agents/skills/brain/scripts/standardize_assessment.py --brain-root <brain_path> --apply
  ```
- The assessment must not move, delete, or rewrite brain content except for writing the report when `--apply` is passed.
- Present the assessment to the user before making semantic changes. Safe deterministic fixes may be applied automatically when they are reversible and non-destructive; ambiguous or destructive decisions require user approval.
