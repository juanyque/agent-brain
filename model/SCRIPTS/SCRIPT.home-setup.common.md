# home_setup.py

## Purpose

Attach a brain to the agent-brain model — **structure only** (D21). Creates the `_COMMON` symlink, wrapper files, and template symlinks. Handles staging for virgin brains. All runtime logic is in `runtime_manager.py`.

## What it does

1. **Pre-cleanup** — removes `.DS_Store` files and recursively-empty directories (so state detection is accurate).
2. **Staging** (virgin brains only) — moves all non-hidden content into `_STAGING/` for later standardization.
3. **`_COMMON` attachment** — creates the `_COMMON` symlink pointing to the model root. Handles conflicts per D25 (see below).
4. **Wrappers** — creates missing local wrapper files (`AGENTS.md`, `BRAIN.md`, `JOBS.md`, `RULES-*.md`) that point to their `.common.md` sources in `_COMMON/`. Existing files are never overwritten.
5. **Template symlinks** — creates missing `TEMPLATES/` symlinks to daily-note, WIP, and issue templates. Existing managed symlinks are validated against the selected model and stale or broken targets are relinked through `_COMMON`; regular local template files are preserved.

## What it does NOT do

- Runtime config wiring (Direction A/B, `_AGENTS/` migration) → `runtime_manager.py`
- Brain skill linking → `runtime_manager.py`
- Standardization (draining `_STAGING/`) → the brain skill's standardize workflow

## D25 — `_COMMON::conflict`

When `_COMMON` exists but points to a different model (or is not a symlink):

- **Without `--switch-model`**: refuses and prints the current vs expected target.
- **With `--switch-model`**: backs up the existing `_COMMON` to `_COMMON.backup-<ts>` and creates the new symlink.

Conflict output names the entry type and keeps both sides distinct:

```text
_COMMON:
  status: conflict-wrong-target
  current: symlink -> ../old-model (resolves to /path/to/old-model)
  desired: symlink -> ../agent-brain/model (resolves to /path/to/agent-brain/model)
```

Broken symlinks retain their raw and resolved target with `target missing`; regular files and
directories are identified as non-symlink entries instead of being described as pointers.

## Usage

```bash
python3 home_setup.py --brain <path> [--common <model_path>] [--apply] [--switch-model] [--skip-full-reorder]
```

- `--brain` (required): path to the brain root.
- `--common`: path to the model root. Defaults to this script's `../` (the `model/` directory).
- `--apply`: execute (default: dry-run).
- `--switch-model`: repoint `_COMMON` on conflict (D25).
- `--skip-full-reorder`: skip the staging sweep (only attach `_COMMON` + wrappers).

## States (via brain_state.py)

| State | `_COMMON` | Markers | `_STAGING` | Action |
|---|---|---|---|---|
| virgin | missing | absent | — | Full flow: stage → attach |
| attached-link-missing | missing | present | — | Re-create `_COMMON` + wrappers, no staging |
| initial | ok | — | has content | No re-stage; standardize drains `_STAGING` |
| maintenance | ok | — | absent | No re-order; idempotent refresh |
| conflict | wrong target | — | — | D25: ask switch / `--switch-model` |
