# agent-brain

**Notes-agnostic second-brain operating model + multi-runtime agent config/memory versioning.**

agent-brain is a personal operating model for AI coding agents (Claude Code, OpenCode, Codex). It gives you:

- A **second-brain** knowledge structure (journal, WIP, memory, tasks) that the model builds on top of any folder of notes — Obsidian is one option, not a requirement.
- **Version-controlled runtime config & memory**: your `CLAUDE.md` / `AGENTS.md`, memory, and runtime settings live in a git-tracked *brain* and are symlinked into each runtime (`~/.claude`, `~/.config/opencode`, …), so your agent configuration and memory travel with you across machines.
- A **session lifecycle** (daily notes, session notes, consolidation) driven by the `brain` skill.
- A **boyscout** skill: silently spot improvement opportunities while you work, then fix them in isolated worktrees or route to tickets.

## Prerequisites

- **Python 3.x** (stdlib only — no pip dependencies)
- **git** on PATH
- At least one supported agent runtime installed:
  - [Claude Code](https://docs.anthropic.com/en/docs/claude-code) → `~/.claude/`
  - [OpenCode](https://opencode.ai/) → `~/.config/opencode/`
  - Shared agents dir → `~/.agents/`
  - Codex → TBD

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/juanyque/agent-brain/main/bootstrap-zero.sh | bash
```

This clones agent-brain to `~/.local/share/agent-brain` and runs the orchestrator, which
will ask for your brain path (an Obsidian vault, a notes folder, or a new empty dir). It
dry-runs by default — review the plan, then apply:

```bash
curl -fsSL https://raw.githubusercontent.com/juanyque/agent-brain/main/bootstrap-zero.sh \
  | bash -s -- --brain /path/to/brain --apply
```

### If `_COMMON` already exists

If your brain already has a `_COMMON` symlink pointing to a different model (e.g. a previous setup), the installer detects the conflict and refuses. Pass `--switch-model` to repoint (a `.backup-<ts>` of the old symlink is created):

```bash
curl -fsSL https://raw.githubusercontent.com/juanyque/agent-brain/main/bootstrap-zero.sh \
  | bash -s -- --brain /path/to/brain --switch-model --apply
```

### Flags

| Flag | Purpose |
|---|---|
| `--brain <path>` | Brain root path (skips interactive prompt) |
| `--apply` | Execute (default: dry-run) |
| `--switch-model` | Repoint `_COMMON` if it conflicts (D25) |
| `--update` | `git pull --ff-only` the repo before wiring |
| `--runtime claude,opencode` | Restrict to specific runtimes (default: all detected) |

## How it works

The installer is a thin orchestrator that delegates to two layers:

1. **`brain_state`** — state machine (`virgin` → `attached` → `initial` → `maintenance`). Determines what flow to run based on the brain's current state.
2. **`home_setup`** — structure: pre-cleanup, staging (for virgin brains), `_COMMON` symlink, wrapper files, templates.
3. **`runtime_manager`** — all runtime config: detects each runtime, ingests local config into the brain (Direction A), implants brain config into local (Direction B), handles conflicts, links skills.

Git is used as rollback anchor: a snapshot commit/tag is created before any mutation.

## Skills

Two skills ship with agent-brain, installed automatically by the bootstrap:

| Skill | Command | Purpose |
|---|---|---|
| **brain** | `/brain` | Connect to the brain, manage session lifecycle, daily notes, standardization |
| **boyscout** | `/boyscout` | Spot improvement opportunities silently, fix in worktrees or route to tickets |

Skills live outside the brain (in `~/.<runtime>/skills/`), symlinked to the repo. They use free filenames (no `.common.md` suffix).

## Repository layout

```
agent-brain/
├── bootstrap-zero.sh     # curl entry point (clones repo, dispatches to orchestrator)
├── model/                # the operating model — what _COMMON symlinks to inside a brain
│   ├── AGENTS.common.md  # shared agent instructions
│   ├── BRAIN.common.md   # brain structure & conventions
│   ├── RULES-*.common.md # daily notes, file naming, links, sessions, evidence
│   ├── JOBS.common.md    # recurring maintenance routines
│   ├── TASK_TYPES/       # how-to guides for recurring task types
│   ├── TEMPLATES/        # daily note, WIP, issue, report templates
│   └── SCRIPTS/
│       ├── brain_state.py       # state machine (shared)
│       ├── home_setup.py        # structure (cleanup, staging, _COMMON, wrappers)
│       ├── runtime_manager.py   # runtime config (Direction A/B, conflict, skill link)
│       ├── runtime_install.sh   # low-level symlink helper (called by runtime_manager)
│       └── skill_link.sh        # manual skill installer for non-default skills
└── skills/
    ├── brain/            # session lifecycle, daily notes, maintenance
    │   ├── SKILL.md
    │   ├── scripts/      # session_open.py, find_home.py, maintenance_scheduler.py, ...
    │   └── references/   # project-aware-loading, setup-and-attach, brain-maintenance, runtime-merge
    └── boyscout/         # improvement-spotting + backlog management
        ├── SKILL.md
        ├── scripts/      # backlog.py, doctor.py, fix-ceremony.sh
        └── references/   # finding-schema, detection guides, ticket backends, deep-mode, ...
```

Files under `model/` keep the `.common.md` naming convention because they live inside a brain (via `_COMMON`) and must stay link-safe for notes apps. `skills/` and the repo root use normal names.

## Origin

Evolved from `obsidian-vault-common` (private). This is the clean, notes-agnostic, multi-runtime rewrite.

## License

TBD.
