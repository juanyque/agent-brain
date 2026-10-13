# Storage and resume

## Persisted-state contract

Persist only what resuming needs: goal, learner context, objective ids and states, current objective, open check, misconception, parked questions, source pointers. Do not store card transcripts.

Write the whole plan file after each state change (objective checked, plan edited, question parked). Before overwriting a file you did not create in this lesson, read it and confirm with the learner.

## Backends

| Option | When | Notes |
|---|---|---|
| Connected brain | A brain skill was already invoked in this session, or the learner names a brain | Store under `WIP/` as a note linked from the session note. Ask once for the destination and the permitted update scope (plan + closing summary); follow the brain's own write rules. Do not run brain lifecycle workflows just for this. |
| Authorized notes tool | Learner confirms one (project notes dir, Notion, ...) | Pin the file path or object id. Check authentication before the first write. |
| Local temp file | Nothing else | Create a private directory with `mktemp -d` (it lands under the platform temp dir), write `plan.md` there, print the absolute path. Ephemeral: cleanup or reboot can erase it, and remote runtimes may not share the filesystem. Offer to export the closing summary to durable notes, and offer to delete the temp directory at close. |

Never pick a predictable shared path such as a fixed `/tmp/<name>.md`: collisions and symlink tricks.

Do not hunt for brains with scripts. If none is connected and the learner did not name one, skip to the next option; asking "which notes should I use?" is enough.

## Failure handling

If a write fails: report it, keep teaching from in-memory state, and propose one explicit migration target. Do not write to a second location unprompted.

## Resume

On `resume <path-or-object-reference>` or when the learner points at an existing plan: fetch it with the matching capability (file read, Notion fetch, ...) and continue only if it matches the plan template (otherwise stop and say so); keep the original pinned backend, restate goal and `where are we`, re-present the open check or the next pending objective, and accept learner edits to the remaining route before continuing. If the file is missing, say so; rebuild a short plan from the conversation only with the learner's agreement.

## Closing summary

One page: goal, objectives with final state, misconceptions that surfaced, deferred questions, suggested next steps. Persist it only if the learner agrees and to the pinned backend. Create tickets or TODOs from gaps only when asked.
