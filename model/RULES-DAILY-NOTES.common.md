# Daily note rules

Use this rule when creating, rolling over, cleaning, or correcting daily notes in `JOURNAL/`.

## Source of truth

- The canonical daily-note structure is `TEMPLATES/Daily Note Template.md`.
- Do not redefine the full daily-note shape in this rule. If the structure needs to change, update the template first, then keep this rule aligned with the intent.

## Activity organization

- Daily activity belongs under `# Actions` → `* [[WORK]]:`.
- Inside `[[WORK]]`, organize entries by project or context, not by session. Sessions are execution traces; projects and contexts are the retrieval axis for the day's work.

## Sessions section

- Use `# Sessions` for compact traceability only:
  - paste-ready recovery command containing the real session id and original working directory
  - project/context touched
  - short outcome summary
- Let `session_open.py` own registration in this section. Its update is an idempotent
  upsert keyed by the full session id: re-running it must leave exactly one entry and
  preserve any user-edited summary while correcting the recovery command and the link
  to the selected active session note.
- Keep detailed work under `# Actions` → `* [[WORK]]:`.

## Cleanup timing

- Structural cleanup of a daily note (removing empty sections or categories and finalizing rollover) may only run when the day has ended — i.e. the date of the note is **not** today's date.
- The current day's content remains live: entries may be added, corrected, completed, consolidated elsewhere, or removed when they no longer carry useful information. Preserve the note's structural placeholders until rollover even when their content becomes empty.
- Re-running the Daily maintenance job on the current day must NOT remove empty structure or finalize the note. It may still verify the note and make justified semantic content updates.
- Rollover cleanup of day N may happen starting day N+1.
- Objectives review (see "Objectives tracking" below) must run **before** the empty-category cleanup, otherwise newly-added evidence would be wiped along with the empty placeholder.

## TODO carryover

- Unfinished `* [[TODO]]:` items are **not** simply deleted when a day closes. At day rollover they are **migrated forward** — carried into the new day's `* [[TODO]]:`, or promoted to `WIP/`/`BACKLOG/` when they are real tasks with context — so intended work is never lost in a closed day's note.
- The migration is reviewed with the user (same review-first pattern as the Objectives review), and runs **before** the empty-category cleanup. The previous day's `* [[TODO]]:` is then cleaned only if it ends up empty.
- The operational steps live in `RULES-SESSION-LIFECYCLE.md` Flow 1 (and are referenced from Flow 2 Scenario B, which closes the previous day when today's note is missing).

## Project section uniqueness

- Under `# Actions` → `* [[WORK]]:`, each project or context heading (e.g. `[[Project Name]] [Project:: Tag]`) must appear **exactly once** per daily note.
- When multiple sessions or maintenance runs touch the same project in the same day, merge their activity bullets under the single existing heading — do not create a duplicate heading.
- This applies even if the work was done in separate maintenance passes or by different agents.
- When appending your session's workstream under an existing project heading, **match the exact indentation of the sibling workstream bullets** (read the note first) — do not nest the new bullet under the previous workstream's last child. After writing, **re-read and verify the indentation**: a Markdown linter may re-nest a mis-indented bullet one level deeper than intended.

## Objectives tracking

- The `* [[OBJECTIVES]]:` item under `# Actions` is the place to record daily evidence of progress against the recurring objectives listed in `WIP/OBJECTIVES.md` (see `BRAIN.common.md` → WIP → Objectives tracking).
- When evidence is recorded, use the shape `* [[<objective name>]] — <short evidence>` so the daily backlinks to the relevant objective node in `WIP/OBJECTIVES.md`.
- If the `* [[OBJECTIVES]]:` item is empty at end-of-day cleanup, remove it like any other empty action category. Days with real entries keep them, so cumulative evidence stays trackable via backlinks to `[[OBJECTIVES]]`.
- This item is optional: if the brain has no `WIP/OBJECTIVES.md`, it stays empty and is always cleaned up.

### Objectives review (close-day / close-session)

When closing a session or closing the day, before the empty-category cleanup runs, the agent should perform an objectives-review pass against `WIP/OBJECTIVES.md`:

1. Read the active objectives listed in `WIP/OBJECTIVES.md`.
2. Gather candidate evidence from both passive and active sources:
   - **Passive** (retrospective scan): the day's `* [[WORK]]:` entries, `# Sessions` summaries, `INBOX/` activity, and any newly added MEMORY entries.
   - **Active** (signals from the current session context): what the agent observed happening during the session itself, even if it did not land in the daily — for example, code review/PR comments the user asked for (Team CR), code edits/refactors/tests authored (Improve codebase), docs/MEMORY/template refinements (Improve documentation), exploratory reading or debugging of unfamiliar areas (Learn), Slack messages drafted to people outside the team or cross-team threads pasted in (Talk to other teams), pairing/coaching/explanations to the user (Support Others).
3. For each plausible match, propose it to the user with a one-line description of the evidence and ask yes/no. Do not infer evidence silently — the value of this section is that entries are real, not auto-generated.
4. For confirmed items, add a bullet under `* [[OBJECTIVES]]:` in the shape `* [[<objective>]] — <short evidence with link to the work bullet, session, or external artifact>`.
5. After the review, run the standard empty-category cleanup: the OBJECTIVES item is removed only if it stayed empty.

This review is a checklist step in the Daily and Session-consolidation jobs (`JOBS.common.md`). It is a no-op when the brain has no `WIP/OBJECTIVES.md`.

## Continuing session across days

- If a session continues across multiple days, it may appear in both days' `# Sessions`, but detailed work still belongs under the correct day's `# Actions` → `* [[WORK]]:` project/context entry.
