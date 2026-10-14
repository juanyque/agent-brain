# Storage and resume

## Persisted-state contract

Persist only what resuming needs: goal, items with id/type/state, `depends_on`, blocked reasons, the current item, the open prompt and parked reasons. Do not store card transcripts.

Rewrite the whole plan file after each state change (item done, plan edited, item parked/blocked). Before overwriting a file you did not create in this session, read it and confirm with the user.

## Backends

| Option | When | Notes |
|---|---|---|
| Connected brain | A brain skill was already invoked in this session, or the user names a brain | Store under `WIP/`. Ask once for the destination and the permitted update scope (plan + closing summary); follow the brain's own write rules. Do not run brain lifecycle workflows just for this. |
| Authorized notes tool | The user confirms one (project notes dir, Notion, ...) | Pin the file path or object id. Check authentication before the first write. |
| Local temp file | Nothing else | `mktemp -d`, write `plan.md` inside, print the absolute path. Ephemeral: cleanup or reboot can erase it. Offer to export the closing summary to durable notes and to delete the temp directory at close. |

Never use a predictable shared path such as a fixed `/tmp/<name>.md` (collisions, symlink tricks). Do not hunt for brains with scripts; if none is connected and the user named none, asking "which notes should I use?" is enough.

## Failure handling

If a write fails: report it, keep guiding from in-memory state, and propose one explicit migration target. Do not write to a second location unprompted.

## Resume

On `resume <path-or-object-reference>` or when the user points at an existing plan: fetch it with the matching capability and continue only if it matches the plan template (otherwise stop and say so). Keep the original pinned backend, state goal and position in one line, and **repeat the open prompt exactly**, without marking it answered. Resuming counts as consent to update that file (the pinned plan). Keep completed items as they are and accept edits to the remaining route before continuing.

If the plan is missing or invalid, say so. If only the chat history remains, rebuild a short plan from it and ask the user to confirm the list; never pretend there was persistence.

## Closing summary

One page: goal, items with final state, parked and blocked items with their reasons, suggested next steps. Persist it only if the user agrees and to the pinned backend. Create tickets or TODOs from leftovers only when asked.
