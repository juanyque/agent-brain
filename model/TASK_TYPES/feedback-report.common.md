# Feedback report - task-type guide

Generate a feedback report from the evidence store for a given person and/or review cycle, then curate it into structured, concrete feedback. The report keeps feedback specific (situation, behavior, impact) rather than generic, and links back to the person's note in `MEMORY/People/`.

> Template: `TEMPLATES/TEMPLATE.feedback-report.common.md`. Conventions: `RULES-REVIEW-EVIDENCE.common.md`. Store guide: `TASK_TYPES/evidence-management.common.md`.

## When this applies

- A peer review cycle is opening and you need to write feedback for one or more colleagues.
- You received feedback (formally or informally) and want to consolidate it for reflection.
- The user mentions writing a review for someone, giving feedback, peer review, 360 review, or similar.

## Before starting

- [ ] Confirm the person has a note in `MEMORY/People/`. If not, create one (at minimum the basename and a one-line role/context).
- [ ] Read `RULES-REVIEW-EVIDENCE.common.md` for naming and sensitivity conventions.
- [ ] Identify the cycle label the brain uses (H1/H2, Q1..Q4, or a local label). Keep it consistent across feedback reports.

## Process

### Phase 1: Query the evidence store

1. Filter `WIP/evidence/` for notes where `kinds` includes `feedback` and `people` includes the target person. Narrow by date range if the cycle is period-scoped. This is a deterministic script operation.
2. The result is a list of self-contained evidence notes about interactions with this person during the period.

### Phase 2: Generate the draft

3. From the filtered evidence, generate a draft using `TEMPLATES/TEMPLATE.feedback-report.common.md`. Determine the direction from the evidence: feedback you are **giving** (your observations about them), or feedback you **received** (their observations about you).
4. Sort observations into **Strengths** (keep doing this) and **Growth areas** (do this differently). The LLM assembles each entry following situation-behavior-impact from the evidence note bodies.

### Phase 3: Curate (the human step)

5. For each theme, verify the situation-behavior-impact is concrete. "Great to work with" is useless; "unblocked me within an hour when I flagged the auth bug, which let the demo ship on time" is useful. Replace generic entries with specific ones from the evidence.
6. For growth areas, add **what differently would look like**. Criticism without a constructive alternative is less useful.
7. Link each entry to the evidence note and/or daily entry where it was first recorded.
8. For feedback received: capture it as-is (factual summary or quote), then add what you took from it and any follow-up action. Do not edit received feedback to soften it; the value is in preserving what was actually said.

### Phase 4: Deliver or file

9. For feedback you are giving: deliver it through the cycle's normal channel. Update `status: draft` -> `status: delivered`.
10. For feedback received: no delivery step. Update `status: draft` -> `status: filed` once you have reflected and captured any follow-up.

### Phase 5: Archive

11. After the cycle closes, a maintenance job proposes moving the report to `ARCHIVED/Reviews/report-feedback-<date>-<slug>.md` via `git mv`.

## Note shape

The template (`TEMPLATES/TEMPLATE.feedback-report.common.md`) defines the shape. Key principles:

- Concrete over generic. Specific situations and impacts beat abstract praise or criticism.
- Behavior over character. "In the retro on YYYY-MM-DD, X cut me off three times" is feedback; "X is dismissive" is a judgment.
- Both directions captured. Feedback given and feedback received are both valuable over time.
- Person link always present. Link to `[[<person>]]` in `MEMORY/People/` so the person's note accumulates a review history via backlinks.

## Common gotchas

- **Generic praise.** "Great team player" helps no one. Replace with a specific example from the evidence.
- **Vague criticism.** "Could communicate better" is unactionable. Specify the situation and the alternative.
- **Confusing given with received.** Keep them in separate sections; the audience and purpose differ.
- **Not linking to the person note.** Without the link, the person's `MEMORY/People/` note has no review history.
- **Deleting after delivery.** Keep the report. It becomes part of your archive of how you have worked with this person, useful for future cycles.

## References

- `TEMPLATES/TEMPLATE.feedback-report.common.md` (note shape)
- `TASK_TYPES/evidence-management.common.md` (store: capture, harvest, schema)
- `RULES-REVIEW-EVIDENCE.common.md` (conventions)
- `MEMORY/People/` (person notes this feedback references)
- Related task-types: `brag-report.common.md` (your own accomplishments), `complaint-report.common.md` (escalation evidence)
