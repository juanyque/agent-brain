# AGENTS.md

## What this repo is

This is **not** an Obsidian brain. It is a shared library consumed by actual brains through a `_COMMON` symlink. Brains reference common files here; local wrappers inherit, add, override, or replace common sections.

Do not treat this repo as a brain. There are no daily notes, no WIP, no JOURNAL. Edits here affect every brain that depends on this common model.

## Repository structure

```
AGENTS.common.md          — shared operating model consumed by brain-local AGENTS.md wrappers
BRAIN.common.md           — shared brain structure guide consumed by brain-local BRAIN.md wrappers
JOBS.common.md            — shared recurring maintenance job definitions
RULES-*.common.md         — granular rule files (file naming, links, daily notes, session lifecycle)
TEMPLATES/*.common.md     — shared note templates (daily note, WIP, WIP session, examples)
TASK_TYPES/               — shared task-type guides (generic procedures that apply across brains)
  TASK_TYPES.common.md      — catalog of available common task-types
  <name>.common.md          — individual task-type guide; brains create wrappers via brain_setup.py
SKILLS/obsidian/          — reusable agent skill + deterministic Python tools
  SKILL.obsidian.common.md  — the obsidian skill loaded by agent runtimes
  scripts/                  — Python tools (find_brains, session_bootstrap, maintenance_scheduler, etc.)
  scripts/TOOL.*.common.md  — tool documentation
SKILLS/boyscout/          — Boy Scout Rule skill: spot improvement opportunities while working, fix or ticket them
  SKILL.boyscout.common.md  — the boyscout skill loaded by agent runtimes
  references/*.common.md    — workflow reference docs (finding schema, selection UI, worktree playbook, etc.)
SCRIPTS/                  — lifecycle setup scripts (brain_setup.py, skill_setup.py)
```

## Naming conventions

- **Common Markdown files**: always use `.common.md` suffix — this avoids Obsidian link ambiguity when brains see these files through `_COMMON`.
- **Python scripts**: use CLI-oriented basenames (`brain_setup.py`, `skill_setup.py`).
- **Script docs**: use `SCRIPT.<name>.common.md` pattern.
- **Skill tool docs**: use `TOOL.<name>.common.md` pattern.
- **Files inside dedicated subfolders** (`TASK_TYPES/`, `TEMPLATES/`, `SKILLS/<skill>/`): the folder already provides context, so individual files inside may use plain names (`<name>.common.md`) without a type prefix — unless an external consumer (Obsidian template plugin, runtime symlink) expects a specific filename pattern (e.g. `SKILL.<name>.common.md` for the runtime, `TEMPLATE.<name>.common.md` for templates).
- All new shared files must follow these conventions.

## Scripts

All scripts that create, move, link, or rewrite files are **dry-run by default**. Require `--apply` to make changes.

### Setup scripts (`SCRIPTS/`)

```bash
# Attach a brain to common (dry-run first)
python3 SCRIPTS/brain_setup.py --brain /path/to/brain
python3 SCRIPTS/brain_setup.py --brain /path/to/brain --apply

# Skip initial full reorder (no _STAGING creation)
python3 SCRIPTS/brain_setup.py --brain /path/to/brain --skip-full-reorder --apply

# Install/repair runtime skill symlinks
python3 SCRIPTS/skill_setup.py --runtime ~/.agents/skills --skill obsidian --apply
python3 SCRIPTS/skill_setup.py --runtime ~/.claude/skills --skill obsidian --apply
```

Never overwrite brain-local files. `brain_setup.py` creates only **missing** wrappers.

### Skill tools (`SKILLS/obsidian/scripts/`)

Exposed through runtime symlinks (e.g. `~/.agents/skills/obsidian/scripts/`). Prefer runtime paths over local copies.

```bash
python3 ~/.agents/skills/obsidian/scripts/find_brains.py [path]
python3 ~/.agents/skills/obsidian/scripts/session_bootstrap.py --brain-root <path>
python3 ~/.agents/skills/obsidian/scripts/maintenance_scheduler.py --brain-root <path>
python3 ~/.agents/skills/obsidian/scripts/standardize_assessment.py --brain-root <path>
python3 ~/.agents/skills/obsidian/scripts/attachments_audit.py --brain-root <path> --scope-root <scope>
python3 ~/.agents/skills/obsidian/scripts/canvas_path_repair.py --brain-root <path> --scope-root <scope>
python3 ~/.agents/skills/obsidian/scripts/find_related_notes.py --brain <path> --keywords "..."
```

All moving/rewriting tools are dry-run by default. Apply only after reviewing the printed plan.

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

## Editing rules for this repo

- **High blast radius**: every change to `.common.md` files propagates to all connected brains. Be conservative.
- Prefer surgical edits over full file rewrites. Edit only the lines that need to change.
- When editing rules or templates, verify that the change is genuinely common — brain-specific logic belongs in brain-local wrappers.
- `AGENTS.common.md` is the always-on guardrail for agents working in brains. `BRAIN.common.md` is the detailed structure guide. Keep them aligned.
- When adding a new rule file, follow the `RULES-<SCOPE>-<TOPIC>.common.md` naming pattern and add a trigger entry in `AGENTS.common.md` → "Rules and conventions".
- When adding a new template, use the `TEMPLATE.<name>.common.md` pattern.
- When adding a new skill tool, add both the Python script and a `TOOL.<name>.common.md` doc, then update `SKILL.obsidian.common.md` → "Available skill tools".
- Log files (`*.log`) are execution artifacts and are gitignored. Never commit them.

## Rule triggers

When editing this repo, the granular rule files are the source of truth for their domain. Load the relevant one before making changes:

| Trigger | Load |
|---|---|
| Creating, renaming, or moving files | `RULES-FILE-NAMING.common.md` |
| Adding or correcting internal Obsidian links | `RULES-LINKS.common.md` |
| Changing daily-note structure or cleanup logic | `RULES-DAILY-NOTES.common.md` |
| Changing session start/rollover/consolidation logic | `RULES-SESSION-LIFECYCLE.common.md` |
| Project WIP context references an optional capability registry or descriptor, such as Graphify | `RULES-OPTIONAL-CAPABILITIES.common.md` |
| Creating, updating, or archiving review evidence (evidence store, brag/feedback/complaint reports) | `RULES-REVIEW-EVIDENCE.common.md` |
| Starting implementation work on a tracker ticket (Jira / GitHub issue / equivalent) — intent-based, not surface-based (slash command, NL phrase, session resume all count) | `RULES-ISSUE-DOCS.common.md` |
| User describes a task that may match a known task-type (basename collision cleanup, dead-code detection, a project migration, a Monte Carlo monitor, etc.) | `TASK_TYPES/TASK_TYPES.md` in the brain — scan one-liner index for matches, deep-read the specific note if a match is found |

## Safety rules

- Scripts must never overwrite existing brain-local files.
- Never delete content during brain standardization — move to `QUARANTINE/TRASH/`.
- `.obsidian/` is out of scope unless explicitly requested.
- All destructive operations require `--apply` flag.

## Git ownership for brains

- The brain's Git repository is controlled by the user. Git is the user's review and approval mechanism for agent-made brain changes.
- Agents may edit, move, or create brain content when the task requires it, but must leave Git workflow decisions to the user unless explicitly asked for a Git operation.
- Do not stage, unstage, commit, amend, reset, stash, branch, rebase, merge, push, force-push, or otherwise mutate Git repository state during normal brain maintenance or documentation work.
- Do not run commands that change the Git index, such as `git add`, `git restore --staged`, `git reset`, interactive staging, or equivalent tooling, unless the user explicitly requests that Git action.
- It is acceptable to report relevant Git state when useful, but the user decides what to stage, review, commit, or push.

## Managed infrastructure access

- For user-managed machines, servers, network devices, storage arrays, and production-like infrastructure, agents must not execute commands directly on the equipment unless the user explicitly asks them to do so for that specific action.
- The default workflow is: the agent proposes exact commands, explains whether they are read-only or state-changing, the user runs them, and the agent analyzes the pasted output.
- This applies even to diagnostic commands over SSH or web-accessible admin endpoints. Treat direct execution on managed infrastructure as an explicit opt-in, not as a default action.

## Determinism rule

`AskUserQuestion` is for branching decisions the user alone can make (which option, which path, which tradeoff to accept). It is never for fields the protocol can derive deterministically from observable state (cwd, branch name, session label, file presence, ticket key, etc.). If a rule's step list does not include a "pick X" decision, do not introduce one. Ask only when the rule itself reaches a fork — never to fill in a slot the agent can compute. When a deterministic source exists, use it and let the user override after the fact.
