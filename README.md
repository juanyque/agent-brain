# agent-brain

**Notes-agnostic second-brain operating model + multi-runtime agent config/memory versioning.**

agent-brain is a personal operating model for AI coding agents (Claude Code, OpenCode, Codex). It gives you:

- A **second-brain** knowledge structure (journal, WIP, memory, tasks) that the model builds on top of any folder of notes — Obsidian is one option, not a requirement.
- **Version-controlled runtime config & memory**: your `CLAUDE.md` / `AGENTS.md`, memory, and runtime settings live in a git-tracked *home* and are symlinked into each runtime (`~/.claude`, `~/.config/opencode`, …), so your agent configuration and memory travel with you across machines.
- A **session lifecycle** (daily notes, session notes, consolidation) driven by the `brain` skill.

## Status

**Early / work in progress.** This repo contains the operating model and the `brain` skill. The zero-touch `bootstrap-zero.sh` installer and the notes-agnostic refactor (`vault` → `home`, Obsidian-as-one-`notes_mode`) are landing in the next stage. The structure is in place; automated install is coming.

## Repository layout

```
agent-brain/
├── model/        # the operating model — what _COMMON symlinks to inside a home
│   ├── AGENTS.common.md, VAULT.common.md, RULES-*.common.md, JOBS.common.md
│   ├── TASK_TYPES/      TEMPLATES/
│   └── SCRIPTS/         home_setup.py, skill_setup.py (setup engines)
└── skills/       # runtime tooling (installed into ~/.<runtime>/skills/, never inside a home)
    └── brain/        session lifecycle, daily notes, home maintenance scripts
```

Files under `model/` keep the `.common.md` naming convention because they live inside a home (via `_COMMON`) and must stay link-safe for notes apps. `skills/` and the repo root use normal names.

## Origin

Evolved from `obsidian-vault-common` (private). This is the clean, notes-agnostic, multi-runtime rewrite.

## License

TBD.
