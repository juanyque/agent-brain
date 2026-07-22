# Setup and attachment workflows

Operations for locating the agent-brain checkout, attaching a brain to it, and installing or repairing the runtime skill. Use these when working with the model for the first time or repairing an existing setup.

## Locate the model checkout

If connected to a brain that already has `_COMMON`, resolve it from the brain root:

```bash
python3 - <<'PY'
from pathlib import Path
print((Path('<brain_path>') / '_COMMON').resolve())
PY
```

If `_COMMON` does not exist, use the canonical agent-brain checkout at `${AGENT_BRAIN_HOME:-$HOME/.local/share/agent-brain}` or ask for its path before applying changes.

## Attach or check a brain

Use the bootstrap in dry-run mode first:

```bash
bash <agent-brain>/model/SCRIPTS/bootstrap-zero.sh --brain <brain_path>
```

The bootstrap installs the skill for detected runtimes. Codex is detected through `~/.codex`, persists its user instructions and configuration at `_AGENTS/CODEX/AGENTS.runtime.codex.md` and `_AGENTS/CODEX/config.toml`, links them back to `~/.codex/AGENTS.md` and `~/.codex/config.toml`, and receives the user skill at `~/.agents/skills/brain`. If the private brain provides `_AGENTS/SHARED/memory/`, it is linked at `~/.agents/brain-memory` for lazy, indexed lookup. Codex's native `~/.codex/memories/` state is left untouched.

Only apply after the dry-run is safe:

```bash
bash <agent-brain>/model/SCRIPTS/bootstrap-zero.sh --brain <brain_path> --apply
```

This script creates `_COMMON` when missing and creates only missing local wrapper files. It must not overwrite existing brain-local files.

When `--skip-full-reorder` is not passed, the script also:

- Sweeps recursively-empty visible directories from the brain root before reading state. Useful after `git reset --hard` of a prior migration: git leaves empty dir shells that confuse subsequent state checks. Top-level dotfile dirs (`.git/`, `.obsidian/`, etc.) and symlinks are never touched.
- When `_COMMON` does not exist: scans the canonical external agent runtime homes (`~/.agents`, `~/.claude`, `~/.codex`, plus any `--runtime-home` path) for symlinks pointing into the brain. Each top-level brain directory referenced by such a symlink is moved into `_AGENTS/<name>/` with `git mv`, the external symlinks are re-pointed to the new location, and the originals are preserved as `.bak.<timestamp>` siblings. A per-migration WIP doc is written at `WIP/AGENTS_MIGRATION.<date>.md` describing every rewrite and the exact cleanup commands.
- When `_COMMON` does not exist: creates `_STAGING/` and moves all remaining non-hidden brain content into it using `git mv`. This signals initial reorganization mode.

For direct low-level repair, `home_setup.py` supports `--skip-full-reorder`; never choose it autonomously.

If the dry-run reports rewritten symlinks, surface the `WIP/AGENTS_MIGRATION.<date>.md` path to the user after apply so they can verify the new links resolve before deleting the `.bak` backups themselves.

## Install or repair the runtime skill

Use `skill_link.sh` in dry-run mode first. For Codex, use the official user-skill parent `~/.agents`:

```bash
bash <agent-brain>/model/SCRIPTS/skill_link.sh brain ~/.agents
```

Only apply after the dry-run is safe:

```bash
bash <agent-brain>/model/SCRIPTS/skill_link.sh brain ~/.agents --apply
```

The runtime should contain `~/.agents/skills/brain` as a symlink to `<agent-brain>/skills/brain`. Do not copy skill files when a symlink can be used.

For a skill owned by another repository, pass its source directory instead of an agent-brain skill
name. The same dry-run-first rule applies, and omitting `runtime_home` targets every detected runtime:

```bash
bash <agent-brain>/model/SCRIPTS/skill_link.sh /path/to/project/skills/confold
bash <agent-brain>/model/SCRIPTS/skill_link.sh /path/to/project/skills/confold --apply
```

The source directory must contain `SKILL.md`; its basename becomes the installed skill name. Runtime
homes receive symlinks, so updates remain owned and versioned by the source project.
