# File naming conventions

Apply across all projects and contexts. Choose the convention based on whether the file's date has intrinsic value.

## When date is NOT important

For code, scripts, configs, templates — files where creation date is metadata, not part of the identity.

**Pattern: systematic prefix naming**

When multiple related files serve different actions on the same domain, name them with a common prefix and an action suffix:

```
prefix-action.ext
```

**Examples:**
- ✅ `backup-create.sh`, `backup-download.sh`, `backup-restore.sh`
- ✅ `deploy-staging.sh`, `deploy-production.sh`
- ❌ `backup.sh`, `download-backup.sh`, `restore-backup.sh`

This keeps grouped files sorted together and makes their relationship obvious at a glance.

## When date IS important

For documents where the date has real value — invoices, communications, fines, contracts, etc.

**Pattern: date-first naming**

```
YYYYMMDD - SOURCE - DESTINATION/SCOPE - TOPIC - DETAIL.EXTENSION
```

**Fields:**
- `YYYYMMDD` — the date that matters (issue date, event date, period start)
- `SOURCE` — who sent or generated it
- `DESTINATION/SCOPE` — recipient or context (company, vehicle plate, project, etc.)
- `TOPIC` — what it is (Invoice, Fine, Contract, Communication, etc.)
- `DETAIL` — optional specifics (period, reference number, status like "payment")
- `.EXTENSION` — file extension

**Examples:**
```
20260505 - UtilityProvider - Household - Invoice - 20260401-20260501.pdf
20260101 - TrafficAuthority - VehiclePlate - Fine - 711.123456789.pdf
20260101 - TrafficAuthority - VehiclePlate - Fine - 711.123456789 - payment.pdf
```

This format sorts chronologically by default in any file manager, which is the intended behavior for document archives.

## When the file tracks an issue/ticket

For notes that track work on a single ticket from an external tracker (Jira, GitHub Issues, Linear, etc.).

**Pattern: ID-first naming with description, dash-separated**

```
TICKET_ID - SHORT_DESCRIPTION.md
```

**Examples:**
- ✅ `EXAMPLE-301 - Expose profile status API.md`
- ✅ `SEARCH-1205 - Re-index product catalog.md`
- ✅ `GH-1234 - Fix login timeout on mobile.md`
- ❌ `EXAMPLE-301.md` (no description — bad for Obsidian search)
- ❌ `Expose profile status API.md` (no ID — hard to cross-reference with the tracker)

The ID prefix keeps tickets grouped by tracker; the dash separator clarifies the boundary between ID and free-text description; the description makes Obsidian search useful when you don't remember the ID.

If a ticket grows heavy supporting artefacts (diagrams, large dumps, local attachments), promote the file to a folder with the same name, and keep the main note inside it:

```
TICKET_ID - SHORT_DESCRIPTION/
├── TICKET_ID - SHORT_DESCRIPTION.md   (the main note)
└── <attachments and supporting docs>
```

The folder form is opt-in. By default, one ticket = one file.

## Avoiding Obsidian basename collisions

Obsidian resolves `[[wikilinks]]` by basename, not by path. Two files with the same basename in different folders (`A/plan.md`, `B/plan.md`) make every `[[plan]]` reference non-deterministic — Obsidian picks one by an implementation-defined fallback. The same applies to `[text](plan.md)` markdown links when the containing file is not in the same folder as the intended target.

**Pattern: `<discriminator>.<stem>.md` for files that would otherwise share a basename**

Any auxiliary file inside a ticket folder, project folder, or other context-bearing parent that is at risk of name collision must include a discriminator, **prefixed before the stem**. Use the parent folder's slug:

- `<parent-folder-name>` lowercased, with non-alphanumeric characters replaced by `-`, collapsed.
- Example: parent `EXAMPLE-305` → discriminator `example-305` → file `example-305.plan.md`.
- Example: parent `EXAMPLE-80 Improve cache cleanup` → discriminator `example-80-improve-cache-cleanup` → file `example-80-improve-cache-cleanup.analysis.md`.

Discriminator-first reads as `<context>.<what>.md` ("the plan of EXAMPLE-305") and groups a folder's auxiliary files together by ticket when listed across mixed locations.

**Applies to**: any file whose basename matches a known shared name (`README.md`, `plan.md`, `analysis.md`, `analisis.md`, `estado.md`, `decisiones.md`, `notes.md`, `MEMORY.md`, etc.) when multiple instances exist in different folders across the brain.

**Detection / cleanup**: see `_COMMON/SKILLS/obsidian/scripts/TOOL.check-basename-collisions.common.md` for the detector + auto-rename workflow.

**Exception**: runtime-governed subtrees (e.g. `_AGENTS/CLAUDE/memory/projects/<X>/MEMORY.md` — paths hardcoded in agent runtime). Document the exception in the TOOL doc's "Known false positives" section.
