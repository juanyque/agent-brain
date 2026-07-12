# Brag report - task-type guide

Generate a brag report from the evidence store for a given date range, then curate it into a narrative a manager or peer reviewer can use. The report follows Julia Evans's brag-document section structure (Projects, Collaboration, Learning, Outside of work, Reflection) but is assembled from structured evidence notes rather than maintained as a standing annual document.

> Template: `TEMPLATES/TEMPLATE.brag-report.common.md`. Conventions: `RULES-REVIEW-EVIDENCE.common.md`. Store guide: `TASK_TYPES/evidence-management.common.md`.

## When this applies

- Performance review season is approaching and you need a brag document for the cycle.
- You want to reflect on what you accomplished over a period (quarter, half, fiscal year — any date range).
- The user asks for a "brag document", "what did I do this year", "prepare for review", or similar.

## Before starting

- [ ] Confirm `WIP/evidence/` exists and has harvested items (run the harvest first if dailies have unlinked stubs — see `TASK_TYPES/evidence-management.common.md`).
- [ ] Determine the date range for the report. This is driven by your review cycle, not by calendar year. If your fiscal year starts in July, a report covering Jul 2025–Jun 2026 is correct.
- [ ] Read `RULES-REVIEW-EVIDENCE.common.md` for naming and lifecycle conventions.
- [ ] If the brain has `WIP/OBJECTIVES.md`, have it open. The report should reflect progress against objectives.

## Process

### Phase 1: Query the evidence store

1. Filter `WIP/evidence/` for notes where `kinds` includes `brag` and `date` falls within the target range. This is a deterministic script operation over YAML frontmatter — no LLM needed.
2. Optionally narrow by `topic` if the report should focus on specific projects.
3. The result is a list of evidence notes, each self-contained (the detail body has the full context).

### Phase 2: Generate the draft

4. From the filtered evidence notes, generate a draft report using `TEMPLATES/TEMPLATE.brag-report.common.md` as the shape. The LLM assembles the evidence into the section structure:
   - **Projects**: group evidence by `topic`, write a contribution + status entry per project.
   - **Collaboration and mentorship**: filter for topics suggesting helping, mentoring, code review.
   - **Design and documentation**: filter for design docs, docs authored.
   - **Company building**: filter for interviewing, process work, cross-team.
   - **What I learned**: filter evidence where `kinds` includes `learning`.
   - **Outside of work**: filter for blog, talks, open source, industry recognition.
5. The draft is mechanical output — it lists what the evidence says, grouped and sorted. It is not yet ready to share.

### Phase 3: Curate (the human step)

6. Read the draft end to end. For each project entry, go back and fill in the **impact**. "Shipped X" becomes "Shipped X, which Y" once you know Y. Impact is not in the evidence store — it is subjective and audience-dependent, so it is added here during curation.
7. Fill in **Goals for this period** from `WIP/OBJECTIVES.md` if it exists. Show how the accomplishments connect to what you were working toward.
8. Write the **Reflection** section: what work you feel most proud of, themes (security, performance, mentorship), what you wish you were doing more of, which projects had the effect you wanted.
9. Build the **Evidence index**: link each report section back to the evidence notes and daily entries that back it. This preserves the retrieval path.

### Phase 4: Share

10. Share the report with your manager. Share with peer reviewers if your team's norm supports it.
11. Update `status: draft` -> `status: submitted` in frontmatter once shared.

### Phase 5: Archive

12. After the review cycle closes and the report is no longer actively referenced, a maintenance job proposes moving it to `ARCHIVED/Reports/report-brag-<date>-<slug>.md` via `git mv`. The evidence store remains unchanged; only the report moves.

## Note shape

The template (`TEMPLATES/TEMPLATE.brag-report.common.md`) defines the shape. Key principles:

- Be specific. "Was the primary contributor to X new feature that is now used by 60% of customers" beats "worked on X".
- Include the fuzzy work. Code review culture, on-call improvements, process work, mentorship. This is the work most likely to be invisible if not written down.
- Separate goals, projects, collaboration, learning, and outside-of-work. A reviewer scanning the document should find each kind quickly.
- The Evidence index is the retrieval path back to the store. Group by project or by quarter.

## Common gotchas

- **Skipping curation.** A generated draft without impact, reflection, or narrative coherence is a filtered list, not a brag document. The curation step is what makes it useful.
- **Leaving impact blank.** "Shipped X" without the follow-on is the most common gap. Go back and fill it in during curation.
- **Omitting fuzzy work.** Mentorship, code review depth, process improvements. Check the evidence store for items that might not obviously be "brag" material but represent real contribution.
- **Confusing brag with objectives.** Objectives are forward-looking; brag is backward-looking. An entry can feed both, but the framing differs.
- **Not sharing it.** The report only helps if your manager and peer reviewers see it. Managers rarely object; it makes their job easier.

## References

- `TEMPLATES/TEMPLATE.brag-report.common.md` (note shape)
- `TASK_TYPES/evidence-management.common.md` (store: capture, harvest, schema)
- `RULES-REVIEW-EVIDENCE.common.md` (conventions)
- `RULES-DAILY-NOTES.common.md` -> Objectives tracking (the forward-looking counterpart)
- `WIP/OBJECTIVES.md` (if the brain uses it)
- Source concept: https://jvns.ca/blog/brag-documents/
- Related task-types: `feedback-report.common.md` (feedback for others), `complaint-report.common.md` (escalation evidence)
