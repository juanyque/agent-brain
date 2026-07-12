# agent-brain

**Notes-agnostic second-brain operating model + multi-runtime agent config/memory versioning.**

agent-brain is a personal operating model for AI coding agents (Claude Code, OpenCode, Codex). It gives you:

- A **second-brain** knowledge structure (journal, WIP, memory, tasks) that the model builds on top of any folder of notes — Obsidian is one option, not a requirement.
- **Version-controlled runtime config & memory**: your `CLAUDE.md` / `AGENTS.md`, memory, and runtime settings live in a git-tracked *brain* and are symlinked into each runtime (`~/.claude`, `~/.config/opencode`, …), so your agent configuration and memory travel with you across machines.
- A **session lifecycle** (daily notes, session notes, consolidation) driven by the `brain` skill.

## Status

**Early / work in progress.** The operating model and `brain` skill are in place. The
`bootstrap-zero.sh` installer wires a brain end-to-end via a 3-layer architecture:
`brain_state` (state machine) + `home_setup` (structure) + `runtime_manager` (runtime config).
Direction B (implant: brain → local) works; Direction A (ingest: local → brain) and
conflict quarantine are implemented. boyscout skill is deferred.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/juanyque/agent-brain/main/bootstrap-zero.sh | bash
```

This clones agent-brain to `~/.local/share/agent-brain` and runs the orchestrator, which
will ask for your brain path (an Obsidian vault, a notes folder, or a new empty dir). It
dry-runs by default — re-run with `--apply` (passed through the pipe) once the plan looks
right. See `model/SCRIPTS/bootstrap-zero.sh -h` for flags.

> ⚠️ Piping to `bash` runs the dry-run plan only (the orchestrator defaults to dry-run).
> To apply, review the plan first, then run with `-- --brain <path> --apply`:
> ```bash
> curl -fsSL https://raw.githubusercontent.com/juanyque/agent-brain/main/bootstrap-zero.sh | bash -s -- --brain /path/to/brain --apply
> ```

## Repository layout

```
agent-brain/
├── model/        # the operating model — what _COMMON symlinks to inside a brain
│   ├── AGENTS.common.md, BRAIN.common.md, RULES-*.common.md, JOBS.common.md
│   ├── TASK_TYPES/      TEMPLATES/
│   └── SCRIPTS/         brain_state.py, home_setup.py, runtime_manager.py, runtime_install.sh
└── skills/       # runtime tooling (installed into ~/.<runtime>/skills/, never inside a brain)
    └── brain/        session lifecycle, daily notes, brain maintenance scripts
```

Files under `model/` keep the `.common.md` naming convention because they live inside a brain (via `_COMMON`) and must stay link-safe for notes apps. `skills/` and the repo root use normal names.

## Origin

Evolved from `obsidian-vault-common` (private). This is the clean, notes-agnostic, multi-runtime rewrite.

## License

TBD.
