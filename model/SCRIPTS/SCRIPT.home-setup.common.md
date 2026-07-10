# vault_setup.py

## Purpose
- Attach an Obsidian vault to `obsidian-vault-common` safely.
- Create the vault-local `_COMMON` symlink and missing wrapper files without overwriting local files.
- Create template symlinks in `TEMPLATES/` pointing to common template sources, only when no local file or symlink already exists.
- When `--skip-full-reorder` is not passed, run two pre-cleanup passes in order before reading vault state:
  1. **`.DS_Store` sweep** (`SKILLS/obsidian/scripts/cleanup_ds_store.py`): remove macOS noise files from visible content. Runs first so directories holding only `.DS_Store` are correctly detected as empty by the next pass.
  2. **Empty-dir sweep**: remove recursively-empty visible directories. Cleans shells left over from undone migrations (git does not track empty dirs).
- Both passes skip symlinks and top-level dotfile dirs (`.git`, `.obsidian`, etc.) and never touch them.
- When `_COMMON` does not exist and `--skip-full-reorder` is not passed:
  - Detect vault top-level directories referenced by external agent runtime symlinks (under `~/.agents`, `~/.claude`, `~/.codex`, plus any `--runtime-home` override) and move them into `_AGENTS/<name>/` using `git mv`.
  - Rewrite each detected external symlink so it points to the new location inside `_AGENTS/`. The original symlink is renamed to `<name>.bak.<timestamp>` and a per-migration WIP doc is generated under `WIP/AGENTS_MIGRATION.<date>.md` documenting the rewrites and the exact cleanup commands.
  - Move all remaining non-hidden vault content into `_STAGING/` using `git mv`. This puts the vault into initial reorganization mode.

## Safety model
- Dry-run by default.
- Existing local files are never overwritten.
- Refuses to modify `_COMMON` if it exists but is not the expected symlink.
- Refuses to modify `_STAGING` if it already exists with content.
- `_AGENTS/` is created on-demand only when at least one runtime-tied directory is detected. Existing destinations inside `_AGENTS/` are never overwritten.
- External symlink rewrites always rename the original symlink first as `<name>.bak.<timestamp>`, never delete it. The cleanup is left to the user, tracked in the generated WIP doc.
- The migration WIP doc is initially written to a hidden `.WIP_<timestamp>/` directory at the vault root so it is excluded from the `_STAGING/` sweep (which only moves non-hidden, non-operational items). After staging completes, the temp dir is renamed to `WIP/`. If `WIP/` already exists (unexpected post-staging), files are merged preserving any existing destination names.
- The `.DS_Store` sweep and the empty-directory sweep both run only when `--skip-full-reorder` is NOT passed. The `.DS_Store` sweep removes only files whose basename matches the `NOISE_FILE_NAMES` constant inside `cleanup_ds_store.py` (currently `.DS_Store`); the empty-dir sweep removes only directories with no files of any kind (recursively), processing bottom-up so parent dirs cascade after their leaves. Both skip symlinks and top-level dotfile dirs. With `--skip-full-reorder` the vault is left untouched as the user requested.
- Wrapper creation only happens when the local file is missing and the matching common source exists.
- Generated wrappers follow the local wrapper convention: if there are no local differences, the wrapper only points to the matching common file.
- Runtime skill setup is included by default for detected runtimes and still follows dry-run/apply mode. Use `--skip-skill` to disable it.
- `_AGENTS` and `_STAGING` are only created when `_COMMON` does not exist. If `_COMMON` already exists, the script skips both phases entirely.

## Managed files
- Wrappers: `AGENTS.md`, `VAULT.md`, `JOBS.md`, `RULES-FILE-NAMING.md`, `RULES-LINKS.md`, `RULES-DAILY-NOTES.md`, `RULES-SESSION-LIFECYCLE.md`.
- Template symlinks: `TEMPLATES/WIP Template.md`, `TEMPLATES/WIP Session Template.md`, `TEMPLATES/Daily Note Template.md`.
- Migration doc: `WIP/AGENTS_MIGRATION.<date>.md` (generated only when external symlinks were rewritten).

## Runtime-tied directory detection
- Scans the canonical external runtime homes that exist on disk: `~/.agents`, `~/.claude`, `~/.codex`.
- Extra homes can be added with `--runtime-home /path` (repeatable).
- For each symlink under a runtime home whose target resolves inside the vault, the top-level vault directory containing the target is marked runtime-tied.
- Operational top-level dirs (`_COMMON`, `_STAGING`, `_AGENTS`) are always excluded from detection.
- Detection is non-destructive: it only reports the mapping. Moves and rewrites happen only in apply mode (or full-reorder dry-run preview).

## Usage

### Dry-run
```bash
python3 SCRIPTS/vault_setup.py --vault /path/to/vault
```

### Apply
```bash
python3 SCRIPTS/vault_setup.py --vault /path/to/vault --apply
```

### Dry-run without runtime skill setup
```bash
python3 SCRIPTS/vault_setup.py --vault /path/to/vault --skip-skill
```

### Apply without runtime skill setup
```bash
python3 SCRIPTS/vault_setup.py --vault /path/to/vault --skip-skill --apply
```

### Apply without reordering vault content
```bash
python3 SCRIPTS/vault_setup.py --vault /path/to/vault --skip-full-reorder --apply
```

### Additional runtime skill directory
```bash
python3 SCRIPTS/vault_setup.py --vault /path/to/vault --runtime ~/.custom-agent/skills --skill obsidian
```

### Additional external runtime home for symlink detection
```bash
python3 SCRIPTS/vault_setup.py --vault /path/to/vault --runtime-home ~/.custom-agent
```

### Explicit common path
```bash
python3 SCRIPTS/vault_setup.py --vault /path/to/vault --common /path/to/obsidian-vault-common
```

## Recommended next steps after setup
- By default, `vault-setup` also runs runtime skill setup for detected runtimes such as `~/.agents/skills`, `~/.claude/skills`, and `~/.codex/skills` when their parent runtime directories exist.
- Use `--skip-skill` if runtime skill setup should be handled separately.
- If `_STAGING/` was created, the vault is in initial reorganization mode. Use `/obsidian init` to start draining it area by area.
- If `_STAGING/` was not created, the vault is in maintenance mode. Use `/obsidian init` to run an assessment and propose improvements.
- If `WIP/AGENTS_MIGRATION.<date>.md` was generated, verify that the rewritten external symlinks resolve correctly. When confirmed, delete the listed `.bak.<timestamp>` files using the commands in that doc.
- Open the vault or connect to it from another project with `/obsidian`.

## Logging
- Every run prints to the console.
- Every run overwrites the latest execution log at:
  - `SCRIPTS/vault_setup.log`

## Known limitations
- It only creates wrappers for the currently known top-level operating files.
- Template symlinks use relative paths and assume `_COMMON` is a sibling-relative symlink pointing to the common repo.
- It does not yet implement update/check/promote subcommands.
