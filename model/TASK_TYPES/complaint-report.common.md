# Complaint report - task-type guide

Generate a complaint report from the evidence store for a given topic, then curate it into a factual, dated, evidence-backed record ready if HR, skip-level management, or legal channels request it. Separates facts (what happened) from interpretations (what it means). Carries the `sensitive` tag so maintenance jobs do not touch it without confirmation.

> Template: `TEMPLATES/TEMPLATE.complaint-report.common.md`. Conventions: `RULES-REVIEW-EVIDENCE.common.md` (especially the Sensitivity section). Store guide: `TASK_TYPES/evidence-management.common.md`.

## When this applies

- The user describes a pattern of behaviour from a colleague or manager that may require formal escalation.
- A specific incident occurs (harassment, discrimination, retaliation, serious misconduct) and the user wants to document it properly.
- The user is already in an HR or escalation process and needs to organize what they have.
- The user says they want to "build a case", "document this properly", "complain formally", or "show me evidence on this topic".

## Before starting

- [ ] Read `RULES-REVIEW-EVIDENCE.common.md` -> Sensitivity in full. Understand the `sensitive` tag implications and the git retention note.
- [ ] Confirm the person(s) involved have notes in `MEMORY/People/`. If not, create stubs with at minimum the basename and role.
- [ ] Decide whether this material belongs in the vault at all. The vault is git-versioned; if discovery or data-residency concerns make that unsuitable, the report stays offline and only a pointer lives in the vault. The user decides.

## Process

### Phase 1: Query the evidence store

1. Filter `WIP/evidence/` for notes where `kinds` includes `complaint` (or `incident`) and `topic` matches the target topic. This is a deterministic script operation.
2. The result is a chronological list of self-contained evidence notes, each with its own detail body and any transcribed attachment content.

### Phase 2: Generate the draft

3. From the filtered evidence, generate a draft using `TEMPLATES/TEMPLATE.complaint-report.common.md`. The LLM assembles:
   - **Summary**: subject, person(s), date range, current status, desired outcome.
   - **Timeline of incidents**: chronological, one entry per evidence note, each with date, what happened, where, who else was present, and a link to the evidence note + any attachment.
4. The timeline is **facts only** at this stage. Interpretation is added during curation.

### Phase 3: Curate (the human step)

5. Review the timeline for completeness. Add any missing context from memory (create backfilled evidence notes for items not yet in the store, then regenerate).
6. Write **Pattern and impact**: this is where interpretation belongs, separated from the factual timeline. Describe the pattern (what these incidents add up to), the impact (on work, wellbeing, team), and any comparison (how this differs from how others are treated).
7. Fill in **Actions taken**: every step you have taken, with dates. This protects you and shows good-faith effort.
8. Verify each timeline entry has its evidence linked: the atomic note (`[[YYYYMMDD-HHMMSS-slug]]`) and any attachment (`![[attachment]]`). The transcription in the evidence note body should be readable without the binary; the binary is the proof.

### Phase 4: Escalate

9. When ready to escalate, follow your organization's process. The complaint report is your supporting material.
10. Update frontmatter `filed:` to the date of formal filing.
11. Update `status: draft` -> `status: escalated` or `status: under investigation` as appropriate.
12. If new incidents occur after filing, add new evidence notes to the store and regenerate or append to the report.

### Phase 5: Close

13. When the complaint resolves, fill in **Outcome**: resolution, date closed, any follow-up conditions.
14. Update `status` to `resolved` or `closed`.
15. Do not move to `ARCHIVED/` automatically. Sensitive complaint reports should stay in `WIP/` (or be moved to `ARCHIVED/Reviews/` only on explicit user decision), because retention and destruction may be governed by HR policy.

## Note shape

The template (`TEMPLATES/TEMPLATE.complaint-report.common.md`) defines the shape. Key principles:

- **Facts and interpretations separated.** The timeline is facts only (from the evidence store). Pattern and impact is where interpretation lives. This separation matters if the record is reviewed by HR or legal.
- **Every claim evidenced.** Each timeline entry links to an evidence note, which in turn links its proof (attachment, daily entry, or witness).
- **Transcriptions in the store.** Evidence note bodies transcribe attachment content so the record is searchable without opening each file. The report references the evidence notes; it does not re-transcribe.
- **`sensitive` tag always set.** Maintenance jobs must not move, archive, or surface this note without explicit confirmation.

## Common gotchas

- **Mixing facts and interpretations in the timeline.** The timeline comes from the evidence store (facts). Put interpretations under Pattern and impact. A timeline that reads as a rant loses credibility.
- **No witnesses recorded.** Note who else was present in the evidence note, even if they seem unlikely to corroborate. Memory fades.
- **Evidence not in the store.** If an incident is described only in the report and has no corresponding evidence note, create one (backfilled if needed) so the store remains the single source of truth.
- **Attachment content not transcribed.** Every evidence note backing a complaint entry should have the attachment content transcribed in its body. If the screenshot is ever lost, the transcription stands.
- **Treating the report as a diary.** This is an evidence file, not a place to vent. Stay factual and measured.

## Sensitivity and safety

- The `sensitive` tag is mandatory. Maintenance jobs treat tagged notes as hands-off without explicit confirmation.
- If you are in immediate danger, contact appropriate emergency services or your organization's security team first. This report is for documentation, not for emergency response.
- Git preserves history indefinitely. If HR policy requires destruction of drafts after formalization, that is an explicit `git filter-repo` operation the user must run. The operating model never destroys content automatically.

## References

- `TEMPLATES/TEMPLATE.complaint-report.common.md` (note shape)
- `TASK_TYPES/evidence-management.common.md` (store: capture, harvest, backfill)
- `RULES-REVIEW-EVIDENCE.common.md` (conventions, especially Sensitivity)
- `RULES-FILE-NAMING.common.md` (date-first naming for attachments)
- `MEMORY/People/` (person notes this complaint references)
- Related task-types: `brag-report.common.md`, `feedback-report.common.md`
