# Scripts

Deterministic lifecycle helpers for the shared Obsidian vault model. Use these scripts for setup/install/repair operations instead of doing them manually.

Detailed per-script documentation lives next to each script as `SCRIPT.<name>.common.md`.

## Conventions

- Each script has a companion Markdown doc named `SCRIPT.<script-name>.common.md`.
- Python scripts and latest-run logs use simple CLI-oriented basenames; Markdown docs keep Obsidian-safe `.common.md` names. Example family: `home_setup.py`, `SCRIPT.home-setup.common.md`, and `home_setup.log`.
- Scripts that inspect or change state print to console and overwrite a latest-run log next to the script (`SCRIPTS/<script-name>.log`).
- Scripts that create, move, rename, link, or rewrite files are dry-run by default and require `--apply` for changes.
- Log files are execution artifacts and are gitignored.
- No script overwrites vault-local files automatically.

## `skill_link.sh`

Install a shared skill into an external agent runtime via symlinks. Full doc: `SCRIPT.skill-link.common.md`.

```bash
# Dry-run
SCRIPTS/skill_link.sh brain ~/.agents

# Apply
SCRIPTS/skill_link.sh brain ~/.agents --apply
```

Backs up an existing target before linking when `--apply` is passed.

## `home_setup.py`

Attach a brain to this common project by creating `_COMMON` and missing local wrappers. Full doc: `SCRIPT.home-setup.common.md`.

```bash
# Dry-run
python3 SCRIPTS/home_setup.py --brain /path/to/brain

# Apply
python3 SCRIPTS/home_setup.py --brain /path/to/brain --apply
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

## `model_check.py`

Read-only contract checker for the public operating model, local worktree gates, committed-range
gates, context budgets, route/set equality, ownership metadata, and brain compatibility. It is the
canonical script behind CI strict gates and the todo19 `complete-local-gate` QA-manifest alias.

```bash
python3 SCRIPTS/model_check.py --strict --format json
python3 SCRIPTS/model_check.py --strict --only worktree-scope,whitespace --format json
python3 SCRIPTS/model_check.py --strict --git-base "$MODEL_BASE" --only committed-scope --format json
```

The checker never fetches, pushes, stages, commits, or rewrites Git state. Callers must provide a
locally available committed base; CI proves that object with `git cat-file -e` before invoking the
committed-range gate.
