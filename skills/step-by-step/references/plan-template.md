# Plan template and card format

## Contents
- Plan template
- Item types
- Item states
- Card format
- Good and bad cards

## Plan template

Write the plan in the user's language. Keep field labels stable so a resumed session can parse them.

```markdown
# Step-by-step plan: <goal in one line>
- Created: <date> | Storage: <path or note id> | Language: <es|en|...>

## Items
- [ ] I1 (pending, decide) — <title>
- [ ] I2 (pending, execute, approval: required) — <title> | depends_on: I1
- [ ] I3 (blocked, answer) — <title> | blocked_on: <who/what> | resume_when: <condition>
- [x] I4 (done, inform) — <title>

## Current
- Item: I1
- Open prompt: <the question or action awaiting the user, or none>

## Parked (derived view; the state word in Items is authoritative)
- I5 — <why parked / what is needed>

## Notes
- <ticket keys, file:line pointers; no secrets or customer data>
```

Add only the fields that matter (`depends_on`, `approval`, `blocked_on`, `resume_when`); do not store card transcripts.

## Item types

| Type | Card content | Ends with |
|---|---|---|
| `decide` | The decision, 2-4 options, your recommendation | `1 / 2 / other` |
| `answer` | A draft reply the user can accept or edit | `ok / edit: ...` |
| `execute` | `Action:` what you will do, where, `Expected result:` | `Authorize?` |
| `inform` | One-sentence acknowledgement or fact | `seen` (or nothing to answer) |

Every `execute` item is `approval: required` by default; only read-only actions and edits to a local draft are exempt. Email, Slack, Jira, Notion, push, merge and deploy are always required. The plan's approval never substitutes for it.

## Item states

`pending` → `done` | `parked` | `blocked` | `dropped`

- The checkbox is `[x]` only for `done`; the state word in parentheses is authoritative on resume.
- `parked`: the user postponed it (`park it`, `skip`) or it needs information not available now. Keep a reason.
- `blocked`: waiting on a third party or condition; needs `blocked_on` and `resume_when`. It returns to `pending` when the user reports the condition is met.
- `dropped`: only by explicit user decision.
- Items with an unresolved `depends_on` are not presented.

## Card format

One card per turn, about 6 lines. Free text is always accepted; options are a shortcut, not a requirement. Never compress a risk or needed context just to fit.

```
3/8 · Decide — <short title>          (pending: 5 · parked: 1 · blocked: 1)
<why this matters, 1-2 lines>
Recommendation: <option and reason>
1 <option> · 2 <option> · other: write it
```

`n` is the position of the item in the active list (not the done count) and `N` the number of active items; show the parked/blocked counters only when non-zero so the bar never implies a straight line. For `execute`, replace the options with `Action:` and `Expected result:` and end with "Authorize?". After the user answers, confirm in one line what was recorded, then show the next card only on the next turn.

## Good vs bad

- Good: one item, one question, a clear recommendation, an easy short reply.
- Bad: two questions in one card, options without a recommendation, a plan approval treated as permission to send or change something external, marking `done` after `next`.
