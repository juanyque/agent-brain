# profile_overlays.py

## Purpose

Project standalone private resources declared by the selected environment profile into target
roots supplied by a runtime adapter. The public projector does not assume where a runtime stores
rules, skills, agents, or themes, and it never edits a monolithic runtime configuration file.

Each `runtime_overlays` item provides:

- `runtime`: a runtime id or `*`;
- `kind`: `rule`, `skill`, `agent`, or `theme`;
- `path`: a brain-relative source that must exist and remain inside the brain;
- `target`: a path relative to the target root supplied for that kind.

## Safety contract

- Dry-run is the default; `--apply` is required for writes.
- Sources and targets reject absolute paths, `..`, and symlink escapes.
- An existing correct symlink is unchanged.
- A conflicting target is moved to
  `INBOX/_PROFILE_OVERLAYS/<runtime>/<profile>/<kind>/<target>` before linking.
- Existing quarantine content is never overwritten.
- If linking fails after quarantine, the original target is restored.
- Reapplying the same projection produces no additional files or drift.

The projector does not stage brain changes or grant runtime permissions.

## Usage

The runtime adapter must provide a target root for every selected overlay kind:

```bash
python3 profile_overlays.py \
  --brain /path/to/brain \
  --runtime codex \
  --target-root rule=/path/to/runtime/rules \
  --target-root skill=/path/to/runtime/skills
```

After reviewing the plan:

```bash
python3 profile_overlays.py \
  --brain /path/to/brain \
  --runtime codex \
  --target-root rule=/path/to/runtime/rules \
  --target-root skill=/path/to/runtime/skills \
  --apply
```

Use `--profile <id>` for explicit selection or `--cwd <path>` to exercise project-rule
selection. The latest execution report is written to `profile_overlays.log`; it contains paths
and actions but never resource contents or secret values.
