# AGENTS.common.md

Audience: brain-local wrappers
Purpose: shared operating guardrail

This common model is consumed through brain-local `AGENTS.md` wrappers. Repository maintainer guidance lives in the root `AGENTS.md`; keep this file focused on rules that must be loaded by agents working inside brains.

## Wrapper convention

Local brain files (AGENTS.md, BRAIN.md, etc.) are wrappers that reference this common model. Each section declares its relationship:

- **Inherits**: section omitted in local → use common as-is.
- **Adds to "Section Name"**: local points appended to common.
- **Overrides in "Section Name"**: local points replace specific common points.
- **Replaces "Section Name"**: entire common section replaced by local.
- **New section**: local-only, no common counterpart.

Never duplicate common content verbatim in a wrapper. Omit unchanged sections entirely.

## Writing style

When agents produce prose for brains (notes, drafts, comments, summaries), avoid em-dash and en-dash characters (`—`, `–`) as sentence separators. Real people rarely type them; agent output stands out as machine-generated when it leans on them. Use natural punctuation instead: a period to end a clause, a comma when the thought continues, parentheses for asides, a colon when introducing a list or definition, a semicolon when joining two related independent clauses. The same applies to text agents draft for users to paste elsewhere (Google Docs comments, Jira tickets, PR descriptions, Slack messages). Identifier formatting (backticks, code fences) and hyphenated compound words (`day-one`, `cross-issuer`) are unaffected; the rule targets only the long-dash separator.

## Rule triggers

Load the narrow rule payload before acting when a trigger matches:

| Route | Scenario | Trigger | Load |
|---|---|---|---|
| rule.attachments | scenario.attachments | Creating, moving, auditing, or repairing attachments | model/RULES-ATTACHMENTS.common.md |
| rule.daily-notes | scenario.daily-notes | Changing daily-note structure or cleanup logic | model/RULES-DAILY-NOTES.common.md |
| rule.file-naming | scenario.file-operations | Creating, renaming, or moving files | model/RULES-FILE-NAMING.common.md |
| rule.issue-docs | scenario.issue-work | Starting implementation work on a tracker ticket or equivalent issue | model/RULES-ISSUE-DOCS.common.md |
| rule.links | scenario.links | Adding or correcting internal Obsidian links | model/RULES-LINKS.common.md |
| rule.optional-capabilities | scenario.optional-capability | Project WIP context references an optional capability registry or descriptor | model/RULES-OPTIONAL-CAPABILITIES.common.md |
| rule.review-evidence | scenario.review-evidence | Creating, updating, or archiving review evidence | model/RULES-REVIEW-EVIDENCE.common.md |
| rule.session-lifecycle | scenario.session-lifecycle | Changing session start, rollover, or consolidation logic | model/RULES-SESSION-LIFECYCLE.common.md |
| task-types.index | scenario.task-types | User describes a task that may match a known task-type | model/TASK_TYPES/TASK_TYPES.common.md |

## Safety rules

- Scripts must never overwrite existing brain-local files.
- Never delete content during brain standardization — move to `QUARANTINE/TRASH/`.
- `.obsidian/` is out of scope unless explicitly requested.
- All destructive operations require `--apply` flag.

## Git ownership for brains

- Git repository state is user-owned.
- Git operations require explicit user authorization.
- Agents may edit, move, or create brain content when the task requires it, but must leave Git workflow decisions to the user unless explicitly asked for a Git operation.
- Do not stage, unstage, commit, amend, reset, stash, branch, rebase, merge, push, force-push, run `git mv`, or otherwise mutate Git repository state during normal brain maintenance or documentation work.
- Do not run commands that change the Git index, such as `git add`, `git restore --staged`, `git reset`, interactive staging, or equivalent tooling, unless the user explicitly requests that Git action.
- It is acceptable to report relevant Git state when useful, but the user decides what to stage, review, commit, or push.

## Managed infrastructure access

- For user-managed machines, servers, network devices, storage arrays, and production-like infrastructure, agents must not execute commands directly on the equipment unless the user explicitly asks them to do so for that specific action.
- The default workflow is: the agent proposes exact commands, explains whether they are read-only or state-changing, the user runs them, and the agent analyzes the pasted output.
- This applies even to diagnostic commands over SSH or web-accessible admin endpoints. Treat direct execution on managed infrastructure as an explicit opt-in, not as a default action.

## Determinism rule

`AskUserQuestion` is for branching decisions the user alone can make (which option, which path, which tradeoff to accept). It is never for fields the protocol can derive deterministically from observable state (cwd, branch name, session label, file presence, ticket key, etc.). If a rule's step list does not include a "pick X" decision, do not introduce one. Ask only when the rule itself reaches a fork — never to fill in a slot the agent can compute. When a deterministic source exists, use it and let the user override after the fact.
