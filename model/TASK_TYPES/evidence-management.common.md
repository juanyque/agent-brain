# Evidence management - task-type guide

Maintain the continuous evidence store that feeds all review reports (brag, feedback, complaint). Evidence items are captured as they happen — primarily via daily note categories, then harvested into self-contained atomic notes — and queried on demand when a report is needed. This guide covers the store schema, the capture-and-harvest cycle, and the backfill protocol for historical evidence.

> Template: `TEMPLATES/TEMPLATE.evidence-note.common.md`. Conventions: `RULES-REVIEW-EVIDENCE.common.md`.

## When this applies

- You want to record an accomplishment, feedback, complaint incident, or learning item for future reference.
- Daily note categories (`[[BRAG]]`, `[[FEEDBACK]]`, `[[COMPLAIN]]`) have accumulated unlinked stubs and it is time to harvest them into atomic evidence notes.
- You need to backfill historical evidence (pre-dating the system, or remembered after the fact).
- You are about to generate a report and need to confirm the evidence store is up to date first.

## Before starting

- [ ] Confirm `WIP/evidence/` exists. Create it if not.
- [ ] Read `RULES-REVIEW-EVIDENCE.common.md` for naming, sensitivity, and lifecycle conventions.
- [ ] If capturing sensitive evidence (complaints, interpersonal incidents), confirm the `sensitive` tag will be set on the resulting note.

## The evidence store

### Location and granularity

- Atomic notes live in `WIP/evidence/`.
- One evidence item per file. The note body holds the full detail; frontmatter holds the structured metadata.
- Granularity is per-item, not per-month or per-year. A note is the atomic, addressable, wikilinkable unit.

### Naming

`YYYYMMDD-HHMMSS-<slug>.md`

- `YYYYMMDD`: the date the event occurred (not the capture date).
- `HHMMSS`: timestamp with seconds to disambiguate multiple items in the same minute.
- `<slug>`: lowercased, hyphenated short description of the event (2–6 words).

Examples:
- `20260715-103025-billing-rest-api-shipped.md`
- `20260315-140012-jane-arch-review-tone.md`
- `20150619-000000-nagrestconf-https-method.md` (backfilled, time unknown)

### Note schema

See `TEMPLATES/TEMPLATE.evidence-note.common.md` for the template. Frontmatter fields:

| Field | Type | Description |
|---|---|---|
| `date` | `YYYY-MM-DD` | Date the event occurred. |
| `kinds` | list | One or more of: `brag`, `feedback`, `complaint`, `incident`, `learning`. Open enum — other values allowed if needed. An item can carry multiple kinds (e.g. `[brag, incident]`). |
| `topic` | string | Slug for the project, theme, or subject area (e.g. `billing-api`, `architecture-review-conflict`). |
| `people` | list | Person slugs linking to `MEMORY/People/` notes (e.g. `["[[Rafael De Lucas Olmos]]"]`). Empty if no people involved. |
| `source` | string or null | Provenance: `[[YYYY-MM-DD]]` (daily note), `![[attachment.png]]` (screenshot/export), a URL, or `null` (memory only). |
| `backfilled` | bool | `true` if ingested directly (not via daily harvest). `false` if harvested from a daily note. |
| `sensitive` | bool | `true` for complaints, interpersonal incidents, or any content naming people in a negative context. Maintenance jobs treat tagged notes as hands-off. |
| `tags` | list | Always includes `evidence`. Add `sensitive` when `sensitive: true`. |

The note **body** is the `detail`: a self-contained prose account. A reader should understand the item without opening any linked source. For attachments (Slack screenshots, email exports), transcribe the relevant content in the body — the body is searchable, the attachment is the proof.

## Process

### Phase 1: Daily capture (the stubs)

1. Accomplishments, feedback, incidents, and learnings are first noted in the daily note under their action category:
   - `* [[BRAG]]:` — accomplishments, shipped work, recognitions.
   - `* [[FEEDBACK]]:` — feedback given or received.
   - `* [[COMPLAIN]]:` — incidents relevant to a complaint or interpersonal conflict.
2. Write a one-line stub per item. Do not elaborate yet — the detail is added during harvest.

```
* [[BRAG]]:
  * Shipped the new REST API for the billing service
* [[FEEDBACK]]:
  * Rafael said my PR refactor was the cleanest he's seen this quarter
* [[COMPLAIN]]:
  * Jane's dismissive tone in the architecture review meeting
```

3. Optionally, leave a note in parentheses if the item needs special handling at harvest time (e.g. "(has Slack screenshot)", "(-sensitive)").

### Phase 2: Harvest (stubs to atomic notes)

4. Run the harvest periodically (every few days, or when a report is needed). For each unlinked stub under `[[BRAG]]` / `[[FEEDBACK]]` / `[[COMPLAIN]]`:
   - If the bullet already contains a `[[wikilink]]` to an evidence note, skip it (idempotent).
   - Otherwise, create the atomic evidence note in `WIP/evidence/`:
     - Generate the filename from the current timestamp: `YYYYMMDD-HHMMSS-<slug>.md`.
     - Fill the frontmatter: map the daily category to the `kinds` value(s), set `date` to the daily note's date, `backfilled: false`, `source: [[YYYY-MM-DD]]`.
     - Write the `detail` body. This is where tokens are spent: expand the one-line stub into a self-contained account. Transcribe any supporting screenshots or exports referenced by the stub.
     - Set `sensitive: true` if the content names people in a negative context or relates to a complaint.
   - Rewrite the daily note line to link the new note: `* [[BRAG]]: [[20260715-103025-billing-rest-api-shipped]] Shipped the new REST API for the billing service`.
5. The daily note becomes the index of pointers; the atomic notes hold the detail.

### Phase 3: Backfill (historical evidence)

6. For evidence that predates the system, or that is remembered after the fact, append directly to the store:
   - Create the atomic note in `WIP/evidence/` with the event's real date.
   - Set `backfilled: true`.
   - Set `source` to whatever provenance exists (a URL, an attachment, or `null` if it is from memory).
   - Do **not** create a retroactive daily note. The daily note is for real-time capture; backfilled evidence goes straight to the store.
7. If a daily note for the event's date already exists, harvest from it normally instead of backfilling.

### Phase 4: Maintain the store

8. Evidence notes are append-only records. Do not edit the factual detail after creation; if the understanding changes, add a dated addendum to the body.
9. `sensitive` notes are never moved, renamed, or surfaced in generated summaries without explicit user confirmation (enforced by maintenance jobs respecting the tag).
10. People referenced in `people:` should have corresponding notes in `MEMORY/People/`. If a person note does not exist, create a stub.

## Division of labour: scripts vs LLM

| Layer | Who | Why |
|---|---|---|
| Daily stub capture | Human (typing in the daily) | Only the human knows what happened |
| Harvest: stub to atomic note (writing the `detail` body) | LLM | Expanding a stub into structured prose requires comprehension |
| Harvest: idempotency check, file creation, daily rewrite | Script (deterministic) | Mechanical: detect existing links, write files, rewrite lines |
| Report query and filter (by kind, date, topic, person) | Script (deterministic) | YAML frontmatter is machine-readable; `PyYAML` suffices |
| Report generation (assembling a coherent narrative) | LLM | Requires narrative coherence and section structure |
| Report curation (impact, reflection, themes) | Human | Irreplaceable judgement |

## Common gotchas

- **Stub rot.** If you never harvest, stubs accumulate in dailies and the detail is lost. Harvest within a few days while context is fresh.
- **Empty detail body.** An atomic note with just frontmatter and no body defeats the purpose. The body is the record; spend the tokens to write it.
- **Forgetting `sensitive`.** If an item names someone in a negative context and `sensitive` is not set, maintenance jobs may surface or move it. Set the flag at creation time.
- **Creating retroactive dailies for backfill.** Do not create a daily note for a date just to hold a backfilled item. Go directly to the store with `backfilled: true`.
- **Editing facts after creation.** Evidence notes are append-only. If new information arrives, add a dated addendum rather than rewriting the original account.

## References

- `TEMPLATES/TEMPLATE.evidence-note.common.md` (note shape)
- `RULES-REVIEW-EVIDENCE.common.md` (conventions: naming, lifecycle, sensitivity)
- `TASK_TYPES/brag-report.common.md`, `TASK_TYPES/feedback-report.common.md`, `TASK_TYPES/complaint-report.common.md` (report generation from the store)
- `RULES-DAILY-NOTES.common.md` (daily capture categories and cleanup)
- `MEMORY/People/` (person notes referenced by `people:` field)
