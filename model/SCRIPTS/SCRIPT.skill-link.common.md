# skill_link.sh

## Purpose
- Symlink a skill into runtime skills directories (`~/.agents/skills/`, `~/.claude/skills/`, etc.).
- Accept either an agent-brain skill name (`skills/<name>/`) or an explicit path to a skill owned by
  another repository.
- For manual installation of non-brain skills (boyscout, etc.). The brain skill is installed automatically by `bootstrap-zero.sh`.

## Safety model
- Dry-run by default; pass `--apply` to execute.
- Idempotent: skips if the target is already the correct symlink.
- Safe: backs up an existing target to `.backup-<ts>` if it is not our symlink.

## Usage

```bash
# Link into all detected runtimes (dry-run)
skill_link.sh boyscout

# Link a repo-owned external skill into all detected runtimes (dry-run)
skill_link.sh /path/to/project/skills/confold

# Link into one runtime only
skill_link.sh boyscout ~/.agents

# Execute
skill_link.sh boyscout ~/.agents --apply
```

An explicit source directory must contain `SKILL.md`. Its directory basename becomes the installed
skill name. The source remains owned by its project; runtime homes receive symlinks rather than copies.

## Legacy

`skill_setup.py` (203 lines, with ownership markers and per-file link mode) is deprecated. It remains in the repo only because `home_setup.py` still calls it — Backlog A removes that call and deletes the script. For all new manual skill installations, use `skill_link.sh`.
