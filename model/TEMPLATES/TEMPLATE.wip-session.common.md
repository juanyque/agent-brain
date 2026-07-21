---
tags: [session, wip]
---
# Session <date> / <topic> / <id>

## State
- Status: open
- Allowed values: open, handoff-only, consolidated, stale-follow-up

## Resume command
- The exact command depends on your agent runtime.
- Working directory: `/absolute/path/used-to-launch-the-session`.
- Example (OpenCode): `cd /path/to/project && opencode -s ses_abc123` — get the id via `opencode session list`.
- Example (Claude Code): `cd /path/to/project && claude --resume ses_abc123`.
- Example (Codex): `cd /path/to/project && codex resume <uuid>` — get the id from the runtime-provided `$CODEX_THREAD_ID` when available.

## Current objective
-

## Decisions taken
-

## Working assumptions
-

## Open questions
-

## Immediate next step
-

## Consolidation checklist
- [ ] `WIP/WIP.md` updated if needed
- [ ] Project-specific WIP note updated if needed
- [ ] `JOURNAL/` updated if needed
- [ ] `MEMORY/` updated if needed
- [ ] Session ID written in daily note
- [ ] Durable state preserved outside this session note
- [ ] This session is not being resumed or continued
- [ ] Any unchecked item has an explicit written reason
- [ ] Session note can be moved to `QUARANTINE/TRASH/` after consolidation
