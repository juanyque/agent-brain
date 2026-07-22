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

## `runtime_health.py`

Verify the post-apply wiring for Claude, OpenCode, Agents, and Codex using the same mapping matrix
as `runtime_manager.py`. Full doc: `SCRIPT.runtime-health.common.md`.

```bash
python3 SCRIPTS/runtime_health.py --brain /path/to/brain
python3 SCRIPTS/runtime_health.py --brain /path/to/brain --runtime claude
python3 SCRIPTS/runtime_health.py --brain /path/to/brain --runtime codex --live-providers codex
```

The check is read-only. Inactive runtimes are skipped; broken mappings, skill links, shared-memory
links, private-file permissions, invalid profiles, and unavailable required live providers fail
with a non-zero exit code. Live MCP discovery is opt-in and sanitizes runtime output.

## `profile_overlays.py`

Project standalone private rules, skills, agents, and themes declared by the selected environment
profile. Full doc: `SCRIPT.profile-overlays.common.md`.

```bash
python3 SCRIPTS/profile_overlays.py \
  --brain /path/to/brain \
  --runtime codex \
  --target-root rule=/path/to/runtime/rules
```

The command is dry-run by default. `--apply` creates brain-sourced symlinks and first moves any
conflicting runtime target into `INBOX/_PROFILE_OVERLAYS/`; it never overwrites quarantine data.

## `profile_secrets.py`

Check name-only availability for environment, keychain, and runtime-native secret references.
Full doc: `SCRIPT.profile-secrets.common.md`.

```bash
python3 SCRIPTS/profile_secrets.py --brain /path/to/brain
python3 SCRIPTS/profile_secrets.py --brain /path/to/brain --keychain macos
```

The preflight never returns a secret value. Required unresolved references fail closed; optional
references remain visible without failing the command.
