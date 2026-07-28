# AGENTS.md

## What this repo is

This is **not** an Obsidian brain. It is a shared library consumed by actual brains through a `_COMMON` symlink. Brains reference common files here; local wrappers inherit, add, override, or replace common sections.

Do not treat this repo as a brain. There are no daily notes, no WIP, no JOURNAL. Edits here affect every brain that depends on this common model.

This root `AGENTS.md` is maintainer-only repository guidance. It is not loaded into brain session context.

## Repository structure

```
AGENTS.common.md          — shared operating model consumed by brain-local AGENTS.md wrappers
BRAIN.common.md           — shared brain structure guide consumed by brain-local BRAIN.md wrappers
JOBS.common.md            — shared recurring maintenance job definitions
RULES-*.common.md         — granular rule files (file naming, links, daily notes, session lifecycle)
TEMPLATES/*.common.md     — shared note templates (daily note, WIP, WIP session, examples)
TASK_TYPES/               — shared task-type guides (generic procedures that apply across brains)
  TASK_TYPES.common.md      — catalog of available common task-types
  <name>.common.md          — individual task-type guide; brains create wrappers via home_setup.py
skills/brain/             — reusable brain agent skill + deterministic Python tools
  SKILL.md                  — the brain skill loaded by agent runtimes
  scripts/                  — Python tools (find_home, session_open, maintenance_scheduler, etc.)
  scripts/TOOL.*.common.md  — tool documentation
SKILLS/boyscout/          — Boy Scout Rule skill: spot improvement opportunities while working, fix or ticket them
  SKILL.boyscout.common.md  — the boyscout skill loaded by agent runtimes
  references/*.common.md    — workflow reference docs (finding schema, selection UI, worktree playbook, etc.)
SCRIPTS/                  — lifecycle setup scripts (home_setup.py, skill_link.sh)
```

## Naming conventions

- **Common Markdown files**: always use `.common.md` suffix — this avoids Obsidian link ambiguity when brains see these files through `_COMMON`.
- **Python scripts**: use CLI-oriented basenames (`home_setup.py`, `skill_link.sh`).
- **Script docs**: use `SCRIPT.<name>.common.md` pattern.
- **Skill tool docs**: use `TOOL.<name>.common.md` pattern.
- **Files inside dedicated subfolders** (`TASK_TYPES/`, `TEMPLATES/`, `SKILLS/<skill>/`): the folder already provides context, so individual files inside may use plain names (`<name>.common.md`) without a type prefix — unless an external consumer (Obsidian template plugin, runtime symlink) expects a specific filename pattern (e.g. `SKILL.<name>.common.md` for the runtime, `TEMPLATE.<name>.common.md` for templates).
- All new shared files must follow these conventions.

## Scripts

All scripts that create, move, link, or rewrite files are **dry-run by default**. Require `--apply` to make changes.

### Setup scripts (`SCRIPTS/`)

```bash
# Attach a brain to common (dry-run first)
python3 SCRIPTS/home_setup.py --brain /path/to/brain
python3 SCRIPTS/home_setup.py --brain /path/to/brain --apply

# Skip initial full reorder (no _STAGING creation)
python3 SCRIPTS/home_setup.py --brain /path/to/brain --skip-full-reorder --apply

# Install/repair runtime skill symlinks
SCRIPTS/skill_link.sh brain ~/.agents --apply
SCRIPTS/skill_link.sh brain ~/.claude --apply
```

Never overwrite brain-local files. `home_setup.py` creates only **missing** wrappers.

### Skill tools (`skills/brain/scripts/`)

Exposed through runtime symlinks (e.g. `~/.agents/skills/brain/scripts/`). Prefer runtime paths over local copies.

```bash
python3 ~/.agents/skills/brain/scripts/find_home.py [path]
python3 ~/.agents/skills/brain/scripts/session_open.py --brain-root <path> --session-id <id> --runtime <runtime>
python3 ~/.agents/skills/brain/scripts/maintenance_scheduler.py --brain-root <path>
python3 ~/.agents/skills/brain/scripts/standardize_assessment.py --brain-root <path>
python3 ~/.agents/skills/brain/scripts/attachments_audit.py --brain-root <path> --scope-root <scope>
python3 ~/.agents/skills/brain/scripts/canvas_path_repair.py --brain-root <path> --scope-root <scope>
python3 ~/.agents/skills/brain/scripts/find_related_notes.py --brain <path> --keywords "..."
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

## Editing rules for this repo

- **High blast radius**: every change to `.common.md` files propagates to all connected brains. Be conservative.
- Prefer surgical edits over full file rewrites. Edit only the lines that need to change.
- When editing rules or templates, verify that the change is genuinely common — brain-specific logic belongs in brain-local wrappers.
- `AGENTS.common.md` is the always-on guardrail for agents working in brains. `BRAIN.common.md` is the detailed structure guide. Keep them aligned.
- When adding a new rule file, follow the `RULES-<SCOPE>-<TOPIC>.common.md` naming pattern and add a trigger entry in `AGENTS.common.md` → "Rule triggers".
- When adding a new template, use the `TEMPLATE.<name>.common.md` pattern.
- When adding a new skill tool, add both the Python script and a `TOOL.<name>.md` doc, then update `skills/brain/SKILL.md` → "Available skill tools".
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

## Section Ownership

| Area | Owner | Context audience |
|---|---|---|
| Repository | `AGENTS.md` | maintainer-only, excluded from brain session context |
| Consumed model | `model/AGENTS.common.md` and `model/BRAIN.common.md` | brain-local wrappers through `_COMMON` |
| Brain-local wrappers | local brain `AGENTS.md`, `BRAIN.md`, `TASK_TYPES/TASK_TYPES.md` | brain-local |
| Runtime config | runtime homes and generated symlinks | user-owned runtime state |
| Local and CI gates | `.github/workflows/tests.yml`, `tests/fixtures/operating-model-qa-commands.json`, and `model/SCRIPTS/model_check.py` | maintainer verification |
| Rules | `model/RULES-*.common.md` | conditional route payloads |
| Jobs | `model/JOBS.common.md` | maintenance job payloads |
| Task types | `model/TASK_TYPES/*.common.md` | conditional task payloads |
| Templates | `model/TEMPLATES/*.common.md` | setup/template payloads |
| Scripts | `model/SCRIPTS/` and `skills/brain/scripts/` | deterministic tooling |
| Skills | `skills/brain/SKILL.md` and `skills/brain/references/` | runtime skill payloads |

## Test Commands

Run the focused operating-model contract first:

```bash
python3 -m unittest tests.test_operating_model_evidence.OperatingModelContractTests tests.test_model_check.OwnershipContractTests.test_missing_skills_audience_is_rejected -v
```

For broader verification, run the pinned baseline, full suite, strict checker, canonical JSON, compile, and diff checks described by `tests/fixtures/operating-model-qa-commands.json`.
