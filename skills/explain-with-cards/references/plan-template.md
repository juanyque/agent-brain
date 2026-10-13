# Plan template and card format

## Contents
- Plan template
- Objective states
- Card format
- Check types
- Good and bad cards

## Plan template

Write the plan in the learner's language. Keep field labels stable so a resumed session can parse it.

```markdown
# Learning plan: <topic>
- Goal: <one sentence — what the learner should be able to do/explain at the end>
- Learner context: <prior knowledge, purpose, depth>
- Mode: session | topic
- Created: <date>  | Storage: <path or note id>

## Objectives
- [ ] O1 (pending) — After this you can <observable ability>
- [ ] O2 (pending) — ...

## Current
- Objective: O1
- Open check: <the question awaiting an answer, or none>
- Misconception seen: <or none>

## Parked questions
- (O2) <question> — <later | opened>

## Sources
- <file:line, ticket, doc link>
```

## Objective states

The checkbox is `[x]` only for `checked`; the state word in parentheses is authoritative on resume.

`pending` → `checked` (learner showed understanding) | `skipped` (learner chose to move on) | `needs-review` (answer was partial). Never set `checked` from `next` alone. The learner may add, remove or reorder remaining objectives at any time (`edit plan`); update the plan and confirm.

## Card format

One card per turn. Keep it under ~12 lines of content.

```
Card 3/6 · O3 — <short title>
<core idea, 3-5 lines>
Example: <concrete, from the real code/session when possible; mark as illustrative if invented>
Source: <pointer, only if it changed>
Check: <one question>
```

## Check types (vary them)

- **Own words:** "Explain X as you would to a teammate."
- **Mini-case:** "Given this snippet/ticket, what happens when ...?"
- **What-if:** "What would change if we removed Y?"
- **Predict:** "Before I show the output, what do you expect?"

Never ask a bare "got it?". Make "I don't get it" an easy answer: on it, retry with a simpler framing or a different example, and mark `needs-review` if still shaky.

## Evaluating the reply

Compare the answer to the objective, not to your wording. Correct → say what was right, update to `checked`. Partial → name the gap, give a smaller follow-up, mark `needs-review`. Wrong → find the misconception, record it under `Current`, set `needs-review`, reteach with a new example. A `needs-review` objective returns to `checked` only after a later answer demonstrates recovery; moving on with `next` leaves it `needs-review`.

## Good vs bad

- Good: one idea, one real example from the repo, a check that needs reasoning.
- Bad: three ideas in one card, a made-up example presented as fact, a check answerable by "yes".
