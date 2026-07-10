# agent-brain

**Notes-agnostic second-brain operating model + multi-runtime agent config/memory versioning.**

agent-brain is a personal operating model for AI coding agents (Claude Code, OpenCode, Codex). It gives you:

- A **second-brain** knowledge structure (journal, WIP, memory, tasks) that the model builds on top of any folder of notes — Obsidian is one option, not a requirement.
- **Version-controlled runtime config & memory**: your `CLAUDE.md` / `AGENTS.md`, memory, and runtime settings live in a git-tracked *home* and are symlinked into each runtime (`~/.claude`, `~/.config/opencode`, …), so your agent configuration and memory travel with you across machines.
- A **session lifecycle** (daily notes, session notes, consolidation) driven by the `brain` skill.

## Status

**Early / work in progress.** The operating model and `brain` skill are in place, and the
`bootstrap-zero.sh` installer now wires a HOME end-to-end for the **implant** direction
(machine has a HOME with `_AGENTS/<runtime>/`; bootstrap symlinks runtimes + brain skill
into place). The **ingest** direction (adopt existing local config into a new HOME) and
the semantic `vault` → `home` refactor are still TODO. boyscout skill is deferred.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/juanyque/agent-brain/main/bootstrap-zero.sh | bash
```

This clones agent-brain to `~/.local/share/agent-brain` and runs the orchestrator, which
will ask for your HOME path (an Obsidian vault, a notes folder, or a new empty dir). It
dry-runs by default — re-run with `--apply` (passed through the pipe) once the plan looks
right. See `model/SCRIPTS/bootstrap-zero.sh -h` for flags.

> ⚠️ Piping to `bash` runs the dry-run plan only (the orchestrator defaults to dry-run).
> To apply, review the plan first, then run with `-- --home <path> --apply`:
> ```bash
> curl -fsSL https://raw.githubusercontent.com/juanyque/agent-brain/main/bootstrap-zero.sh | bash -s -- --home /path/to/home --apply
> ```

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
