# feature-development
<!-- content-boundary: {"kind":"task-index-entry","owner":"model/TASK_TYPES/TASK_TYPES.common.md"} -->

## When this applies

- Building a new feature or a substantial change, from an initial idea through to a mergeable
  change, where the work benefits from an explicit spec before touching code.
- Especially valuable for a solo operator: without natural peer review, a self-authored spec
  needs an independent check before it can be trusted as ready.
- Skip this for small, obvious fixes where writing a PRD/ADR would cost more than the change
  itself.
- If the current environment already has a broader, more specific development lifecycle
  defined (its own PRD/spec/review process, its own task tracker conventions), defer to that
  instead of this generic guide.

## Before starting

- Confirm where finished work is tracked (a task tracker — see
  `SOURCE_TYPES/task-tracker.common.md`) and where source-code changes are proposed for review
  (a version-control review request: a pull request, a merge request, or the local equivalent).
- Check whether an existing spec or design already covers this idea before writing a new one
  from scratch.

## Process

1. **Idea** — state the problem and the intended outcome, one sentence each.
2. **PRD** — write what to build and why. Keep it a decision-and-scope document, not an
   implementation plan.
3. **Design (Spec-Driven Design, SDD)** — work out the how before writing code: architecture,
   interfaces, data shape, key tradeoffs and the alternatives considered. The design is written
   down and reviewed before implementation starts, not discovered while coding.
4. **Architecture decision records** — capture each consequential decision made during design,
   with the alternatives considered and why they were rejected. One record per decision, not
   one record for the whole design.
5. **Adversarial verification, before implementation starts** — do not treat a single
   self-review of the PRD/design as sufficient evidence it is ready. A spec can look complete to
   its own author and still hide an unresolved conflict (an ownership question, a date, a
   dependency) that only surfaces under independent scrutiny. Run an adversarial pass: one or
   more independent reviewers whose job is to disprove each claim and decision against real
   evidence, not to confirm it. If a skill or tool for adversarial document verification is
   already available in this environment, reuse it; otherwise, at minimum, have a different
   reviewer (a human, or a separate agent instance with no stake in the original draft) attempt
   to refute the spec before treating it as ready.
6. **Task-tracker item(s)** — break the verified design into trackable work items.
7. **Implementation (Test-Driven Development, TDD)** — write the failing test before the code
   that makes it pass, for each unit of work.
8. **Review request** — open it referencing the PRD, the ADRs, and the task-tracker item(s) it
   implements, so the chain from decision to change stays traceable without manual archaeology.

## Note shape

- One note for the PRD, and one note per ADR — do not merge multiple decisions into a single
  ADR note.
- Link each task-tracker item and review request back to the PRD/ADR notes that justify it.

## Common gotchas

- Treating a single run of self-review (by the same author, or the same agent that wrote the
  spec) as sufficient evidence the spec is ready — it is not. See step 5.
- Skipping the design step for something that looks small, then discovering the real
  complexity mid-implementation.
- Writing implementation detail into the PRD instead of the design step, which makes the PRD
  harder to review for decision-relevant content.

## References

- `SOURCE_TYPES/task-tracker.common.md` for what counts as a task tracker.
