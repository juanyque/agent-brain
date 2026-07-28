# Documentation And Classification

<!-- agent-brain-reference
{"downstream_rules":["Load the brain-local daily-note rule before writing daily notes.","Load project AGENTS.md/CLAUDE.md only to discover a declared Documentation home.","Split mixed project-knowledge and session-trace material into separate destinations."],"route_id":"skill.documentation","scenario_id":"scenario.documentation","schema_version":"agent-brain-skill-reference/v1","source_ranges":["range.skill.documentation"],"trigger_rules":["Load when deciding whether durable content belongs in the brain, project documentation, WIP, MEMORY, or online asset storage."]}
-->

## Trigger Rules

- Load when deciding whether durable content belongs in the brain, project documentation, WIP, MEMORY, or online asset storage.

## Downstream Rules

- Load the brain-local daily-note rule before writing daily notes.
- Load project AGENTS.md/CLAUDE.md only to discover a declared Documentation home.
- Split mixed project-knowledge and session-trace material into separate destinations.

## Copied Source Ranges

## Documenting activity

Document **meaningful** session activity in the brain — not everything, only what has lasting value:

- **Daily-note rule pre-check**: before writing to a daily note, read the brain-local `RULES-DAILY-NOTES.md` if it exists, otherwise read `_COMMON/RULES-DAILY-NOTES.common.md`. Validate the planned edit against cleanup timing, `# Sessions` traceability, and project-section uniqueness before writing.
- **Daily note**: record significant progress, decisions, and next actions in today's daily note under `JOURNAL/`. Create it if it does not exist, following the brain's daily note template and linking conventions.
- **WIP updates**: if the session touches active WIP items, update the relevant WIP notes.
- **WIP dashboard invariant**: every active non-session note under `WIP/` must be linked
  from `WIP/WIP.md`. After creating or activating one, run `brain_check.py --wip-note
  <brain-relative-path>`; do not report completion if the check fails.
- **Session note**: if the brain uses session notes (`WIP/SESSIONS/`), create or update the session note.
- **New notes**: only create new notes when the session produces knowledge worth preserving beyond the current task.
- **Post-apply truth**: write durable notes from the resulting state, not the approval plan.
  Completed checks are evidence rather than TODOs, and temporary handoffs are sources,
  not durable references unless the user explicitly promotes them.

Follow all formatting conventions, frontmatter schemas, and linking patterns defined in the brain's `AGENTS.md` and `BRAIN.md`. Do not invent new conventions — match what already exists.

## Content classification: brain vs project documentation

When the session is connected to both a brain and a project (repo, workspace, etc.), apply these rules to decide where each piece of content belongs.

### Classification rule

Ask one question per piece of content:

> **"Would another person need this to operate, understand, or plan the project?"**
> → Goes to the **project's documentation home**.

> **"Does this answer what I did, when, why, or how I got here?"**
> → Goes to the **brain** (daily notes, sessions, WIP).

MEMORY only if the content provides **reusable value** beyond historical trace (e.g. installation steps, configuration recipes). Pure activity logs do not belong in MEMORY.

### Project documentation home

Each project declares its documentation home in its `AGENTS.md`, `CLAUDE.md`, or equivalent runtime config file. Look for a `## Documentation home` section at brain resolution time.

| Declaration | Meaning |
|---|---|
| `## Documentation home` → this repo | Project documentation lives in the project's own repository. |
| `## Documentation home` → external tool (Notion, Confluence, wiki) | Project documentation lives in the named external tool. Include link. |
| No declaration | **Default: the brain** is the project's documentation home. |

When in doubt, default to the brain. The brain is always a valid destination; the project's declared home may or may not exist.

### Heavy assets rule

Images, evidence files, and other large binary assets must go to **accessible online storage** (S3-compatible, object storage, or equivalent). The documentation home (repo, brain, or external tool) should **link** to the asset's permanent location, not store the binary itself.

While online storage is not yet set up, the brain may temporarily hold assets in `ATTACHMENTS/` — but this is explicitly temporary. Track the migration in the project's WIP.

### When a note answers both questions

If a single note contains both "what another person needs" and "what I did", split it:
- Extract the operational/project knowledge → project documentation home.
- Keep the personal trace (decisions, timeline, reasoning) → brain.

## Concepts

Key terms used throughout the maintenance and setup workflows below:

- **`_COMMON`** — brain-local symlink pointing to the `model/` directory of the agent-brain checkout that serves the installed skill. Only that exact resolved target signals a current-model brain; a link to another or legacy model is a conflict.
- **`_STAGING/`** — temporary directory in the brain root used during initial standardization to hold all original content before it is classified and moved into the target structure (`JOURNAL/`, `WIP/`, `MEMORY/`, etc.). Its presence signals Initial mode; its absence signals Maintenance mode.
- **`_AGENTS/`** — on-demand home (created by `home_setup.py`) for brain-internal directories that act as the source of truth for an external agent runtime (e.g. `_AGENTS/CLAUDE/`, referenced via symlinks under `~/.claude/`). Sits alongside `_COMMON` and `_STAGING` as an operational top-level directory, never as content.
- **`QUARANTINE/TRASH/`** — destination for content that looks discardable but must never be deleted automatically. Items remain there until the user explicitly approves permanent deletion.
- **`WIP/STANDARDIZE_PROCESS.md`** — durable state file tracking brain standardization progress across sessions. Update it after each batch of moves; never rewrite from scratch.
- **`WIP/AGENTS_MIGRATION.<date>.md`** — generated by `home_setup.py` when it rewrites external runtime symlinks to point into `_AGENTS/`. Lists every rewritten symlink, its `.bak.<timestamp>` backup, and the exact `rm` commands to clean up the backups once the user has verified the new symlinks resolve correctly.
