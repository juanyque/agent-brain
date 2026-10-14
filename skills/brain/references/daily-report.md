# Daily report workflow

The workflow triggered by `brain daily [--date YYYY-MM-DD]` or a natural request such as "give me the report for the daily" or "qué hice desde el viernes". It produces a structured report of what the user did over a date range, to be said aloud in a stand-up, and stores it in today's daily note.

The report is a reading of what the brain already records. It never invents activity: the quality of the report is the quality of the notes, so a gap in the notes is reported as a gap.

## Range

- `--date` is the **first** day. The range always ends today (inclusive).
- Without `--date`, the first day is the latest daily note dated before today. A Monday run therefore starts on the previous working day with a daily; pass `--date` with the Friday to include weekend work.
- Re-running with another date **replaces** the previous report: a daily note holds at most one report, and the latest run wins.
- The report is optional. Days without a stand-up simply have no report.

## Procedure

1. **Connect.** Resolve the brain and run `session_open.py` as for any session start (see `session-lifecycle-routing.md`). If today's daily note is missing, finish that rollover first; the report is stored in today's note.
2. **Dump, without closing (optional).** Open sessions in the range may hold facts that exist only in their conversations. Offer to prepare the dump prompt below for each session the user names. You cannot message another runtime, so present the prompt to the user to paste; do it yourself for the current session. A dump is **not** a session close: never set `Status: consolidated`, never archive, never tick the consolidation checklist. Wait for the user to say the sessions answered, or to skip the step.
3. **Collect.** Run `daily_report_collect.py --brain-root <brain> [--from <date>]` and read its JSON (see `TOOL.daily-report-collect.md`). Do not re-derive what it already attributes to a day. If you read the JSON in a single step, do not save it; if you need it across steps, save it under `WIP/scratch/daily-report/`.
4. **Resolve gaps with the user.**
   - An issue with an empty `work_type`: ask once whether it is `sprint` or `unplanned` (or another value) and, once answered, write only that frontmatter field. See "Work type" in `RULES-ISSUE-DOCS.md`.
   - A ticket worked on in a session or a WORK entry that has no issue note: propose creating it per `RULES-ISSUE-DOCS.md`, and create it only with approval. Pure PR reviews do not need an issue note or a session note unless they produced further work.
5. **Compose** the report in the language of the conversation (see "Report format").
6. **Show it, then write it.** Present the report in the conversation first. Write it into today's daily note only after the user approves (see "Storing the report").

## Report format

Sections, in this order. Omit a section that has nothing to say, except Blockers: if there are none, say so.

- **Sprint** — tickets whose issue note has `work_type: sprint`.
- **Unplanned work** — tickets with `work_type: unplanned`. Any other value gets its own section named after it.
- **Reviews** — pull requests the user reviewed, one line each: ticket, PR, verdict, and whether anything was published.
- **In progress** — what the user is on right now: open sessions' next steps and the issue notes' current status.
- **Blockers** — the most important section. Group by ticket: waiting on third parties, failing or pending CI and reviews, missing access, and **decisions pending from the user**, listed apart so they are easy to see.

Each Sprint / Unplanned item reads:

```
**TICKET / ACTIVITY-SLUG — PR #n:** the goal of this task is <one sentence>.
- detail (one bullet per distinct piece of work, newest information last)
```

- The goal sentence comes from the issue note's summary line or the session's current objective. Mark it `(inferred)` when you had to compose it from other evidence.
- When the range spans several days, name the day of each detail (for example `Fri 10-09:`), using the issue notes' dated entries rather than the session note's file date.
- Use exact identifiers (ticket, PR, commit, build) as recorded. Do not round numbers or soften unresolved items.
- Say what is verified and what is not; never claim a test, check or deployment that the notes do not record.
- Finish with `Unattributed files:` when the collector returned generated files that no issue note references, and with `Sources:` listing the wikilinks of the notes the report was built from.
- Spoken length: enough to cover everything the user may want to mention, not more. The user decides what to say; a shorter or translated version is a separate request.

## Storing the report

Today's daily note holds the report in a `# Daily report` section, delimited by markers so it can be replaced:

```
# Daily report
<!-- daily-report range=2026-10-09..2026-10-13 -->
...report...
<!-- /daily-report -->
```

- Save the approved report body to a scratch file under `WIP/scratch/daily-report/` (see `WIP/scratch/` in `BRAIN.md`; not `/tmp`). Write each section title as a `## ` heading (never bold text, never a top-level `# ` heading, which would end the `# Daily report` section) and leave the markers out; the tool adds them. Then run `daily_report_write.py --brain-root <brain> --report-file <file> --range <first>..<today>`. It is a dry-run until you add `--apply`; run the dry-run, check the `action:` line, then apply. See `TOOL.daily-report-write.md`.
- The tool writes only today's note, replaces a previous report, and refuses to touch content it does not own. If it refuses, tell the user why instead of editing the note by hand.
- Never edit the report in any other day's note.
- The `# Daily report` section is generated content: other brain procedures leave it alone, and the rollover cleanup removes it only when it is empty.

## Dump prompt

Present this to the user to send to each open session, translated into the language of the conversation and with the placeholders filled. Never leave a placeholder unfilled: ask the user for any value you do not know.

```
Dump what you have done and know in this session into the brain, WITHOUT closing it: the session stays open and I will keep working in it. This is not the session-close flow: do not set Status: consolidated, do not archive the session note, and do not tick the consolidation checklist.

Goal: nothing that lives only in this conversation is lost, and the daily report can be built from the brain.

1. Session note: update it with the real state (current objective, decisions, open questions, immediate next step, evidence). Only verified facts.
2. Issue note for <TICKET> (WIP/<project>/<repo>/<TICKET - title>/<TICKET - title>.md): create it from the issue template if missing, otherwise update it without overwriting content. Include the one-sentence goal, context, decisions, current status under a dated heading (### YYYY-MM-DD), blockers (who or what blocks) and next steps.
3. work_type: <sprint | unplanned | other>.
4. WIP/WIP.md and today's daily note: add only what is missing.
5. MEMORY: do not write new memory without proposing it to me first.
6. Files outside the brain (scripts, logs, analyses): list where they are and propose where they should live next to the issue note. Do not move them without my confirmation.
7. Do not change the tracker, create tickets, commit or push.

When done, reply with: what you wrote and where, what is still undocumented and why, current in-progress items and blockers (one line each), and the decisions you need from me.
```
