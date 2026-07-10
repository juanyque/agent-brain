# skill_setup.py

## Purpose
- Install shared `obsidian-vault-common` skills into an external agent runtime using symlinks.
- Keep the common repository Obsidian-safe while still materializing runtime-required names such as `SKILL.md`.

## Safety model
- Dry-run by default.
- Uses symlinks instead of copies so common repo changes apply immediately.
- Refuses to modify an existing runtime skill directory unless it has the ownership marker or `--force-adopt` is passed.
- Writes an ownership marker at `.obsidian-vault-common-link.json` in the runtime skill directory.

## Usage

The `--skill` argument selects which skill from `SKILLS/<skill>/` to install. Available skills today: `obsidian`, `boyscout`.

### Dry-run
```bash
python3 SCRIPTS/skill_setup.py --runtime ~/.agents/skills --skill obsidian
python3 SCRIPTS/skill_setup.py --runtime ~/.claude/skills --skill boyscout
```

### Apply
```bash
python3 SCRIPTS/skill_setup.py --runtime ~/.agents/skills --skill obsidian --apply
python3 SCRIPTS/skill_setup.py --runtime ~/.claude/skills --skill boyscout --apply
```

### Adopt an existing unmarked runtime directory
```bash
python3 SCRIPTS/skill_setup.py --runtime ~/.agents/skills --skill obsidian --force-adopt --apply
python3 SCRIPTS/skill_setup.py --runtime ~/.claude/skills --skill boyscout --force-adopt --apply
```

## Logging
- Every run prints to the console.
- Every run overwrites the latest execution log at:
  - `SCRIPTS/skill_setup.log`

## Known limitations
- It currently installs one skill at a time.
- It does not yet auto-discover runtime directories such as `~/.agents/skills` or `~/.claude/skills`.
