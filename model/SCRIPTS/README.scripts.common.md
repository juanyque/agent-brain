# Scripts

Deterministic lifecycle helpers for the shared Obsidian vault model. Use these scripts for setup/install/repair operations instead of doing them manually.

Detailed per-script documentation lives next to each script as `SCRIPT.<name>.common.md`.

## Conventions

- Each script has a companion Markdown doc named `SCRIPT.<script-name>.common.md`.
- Python scripts and latest-run logs use simple CLI-oriented basenames; Markdown docs keep Obsidian-safe `.common.md` names. Example family: `skill_setup.py`, `SCRIPT.skill-setup.common.md`, and `skill_setup.log`.
- Scripts that inspect or change state print to console and overwrite a latest-run log next to the script (`SCRIPTS/<script-name>.log`).
- Scripts that create, move, rename, link, or rewrite files are dry-run by default and require `--apply` for changes.
- Log files are execution artifacts and are gitignored.
- No script overwrites vault-local files automatically.

## `skill_setup.py`

Install a shared skill into an external agent runtime via symlinks. Full doc: `SCRIPT.skill-setup.common.md`.

```bash
# Dry-run
python3 SCRIPTS/skill_setup.py --runtime ~/.agents/skills --skill obsidian

# Apply
python3 SCRIPTS/skill_setup.py --runtime ~/.agents/skills --skill obsidian --apply
```

Refuses to modify an existing unmarked runtime skill directory unless `--force-adopt` is passed.

## `vault_setup.py`

Attach an Obsidian vault to this common project by creating `_COMMON` and missing local wrappers. Full doc: `SCRIPT.vault-setup.common.md`.

```bash
# Dry-run
python3 SCRIPTS/vault_setup.py --vault /path/to/vault

# Apply
python3 SCRIPTS/vault_setup.py --vault /path/to/vault --apply
```

Creates `_COMMON` when missing and creates only missing wrapper files. Existing local files are reported and never overwritten.
