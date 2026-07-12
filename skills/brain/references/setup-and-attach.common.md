# Setup and attachment workflows

Operations for locating the shared common checkout, attaching a brain to it, and installing or repairing the runtime skill installation. Use these when working with the common model for the first time or repairing existing setup.

## Locate the common checkout

If connected to a brain that already has `_COMMON`, resolve it from the brain root:

```bash
python3 - <<'PY'
from pathlib import Path
print((Path('<brain_path>') / '_COMMON').resolve())
PY
```

If `_COMMON` does not exist, use the known common checkout path if the user provided one, or ask for the path before applying changes.

## Attach or check a brain

Use `brain-setup` in dry-run mode first:

```bash
python3 <common_path>/SCRIPTS/home_setup.py --brain <brain_path>
```

By default, `brain-setup` also verifies or installs the runtime skill for detected runtimes such as `~/.agents/skills`, `~/.claude/skills`, and `~/.codex/skills` when their parent runtime directories exist. Use `--skip-skill` if the user wants to skip runtime skill setup.

Only apply after the dry-run is safe:

```bash
python3 <common_path>/SCRIPTS/home_setup.py --brain <brain_path> --apply
python3 <common_path>/SCRIPTS/home_setup.py --brain <brain_path> --skip-skill --apply
```

This script creates `_COMMON` when missing and creates only missing local wrapper files. It must not overwrite existing brain-local files.

When `--skip-full-reorder` is not passed, the script also:

- Sweeps recursively-empty visible directories from the brain root before reading state. Useful after `git reset --hard` of a prior migration: git leaves empty dir shells that confuse subsequent state checks. Top-level dotfile dirs (`.git/`, `.obsidian/`, etc.) and symlinks are never touched.
- When `_COMMON` does not exist: scans the canonical external agent runtime homes (`~/.agents`, `~/.claude`, `~/.codex`, plus any `--runtime-home` path) for symlinks pointing into the brain. Each top-level brain directory referenced by such a symlink is moved into `_AGENTS/<name>/` with `git mv`, the external symlinks are re-pointed to the new location, and the originals are preserved as `.bak.<timestamp>` siblings. A per-migration WIP doc is written at `WIP/AGENTS_MIGRATION.<date>.md` describing every rewrite and the exact cleanup commands.
- When `_COMMON` does not exist: creates `_STAGING/` and moves all remaining non-hidden brain content into it using `git mv`. This signals initial reorganization mode.

Pass `--skip-full-reorder` to skip the empty-dir cleanup, the `_AGENTS/` migration, and the `_STAGING/` sweep — only the common structure is created.

If the dry-run reports rewritten symlinks, surface the `WIP/AGENTS_MIGRATION.<date>.md` path to the user after apply so they can verify the new links resolve before deleting the `.bak` backups themselves.

## Install or repair the runtime skill

Use `skill-setup` in dry-run mode first:

```bash
python3 <common_path>/SCRIPTS/skill_setup.py --runtime ~/.agents/skills --skill obsidian
```

Only apply after the dry-run is safe:

```bash
python3 <common_path>/SCRIPTS/skill_setup.py --runtime ~/.agents/skills --skill obsidian --apply
```

The runtime should contain symlinks to common sources and an `.obsidian-vault-common-link.json` marker. Do not manually copy skill files when symlinks can be used.
