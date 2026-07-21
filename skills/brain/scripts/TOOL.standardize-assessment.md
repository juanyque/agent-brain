# standardize_assessment.py

## Purpose
- Assess a vault against the `obsidian-vault-common` structure in maintenance mode.
- Generate a reviewable `WIP/STANDARDIZE_PROCESS.md` report without moving or deleting content.

## Scope
- Top-level structure and required operational files.
- `_STAGING/` mode detection.
- JOURNAL daily-note placement and non-daily note detection.
- WIP dashboard/session-note structure.
- Counts for `INBOX/`, `BACKLOG/`, `WIP/`, `MEMORY/`, `REPORTS/`, and `QUARANTINE/`.
- Attachment and canvas presence.
- Filename-based sensitivity-review candidates.

## Safety model
- Dry-run by default.
- Never moves, deletes, or rewrites vault content.
- `--apply` only writes the assessment report to `WIP/STANDARDIZE_PROCESS.md` or the provided `--output` path.

## Usage

### Dry-run
```bash
python3 ~/.agents/skills/obsidian/scripts/standardize_assessment.py --vault-root .
```

### Write assessment report
```bash
python3 ~/.agents/skills/obsidian/scripts/standardize_assessment.py --vault-root . --apply
```

### Custom output path
```bash
python3 ~/.agents/skills/obsidian/scripts/standardize_assessment.py --vault-root . --output WIP/STANDARDIZE_PROCESS.md --apply
```

### Extra sensitivity terms
By default, the filename-sensitivity scan flags `credential`, `credentials`, `password`, `secret`, `token`, and `access`. Pass additional case-insensitive terms specific to your stack via `--sensitive-extra`:

```bash
python3 ~/.agents/skills/obsidian/scripts/standardize_assessment.py --vault-root . --sensitive-extra terraform openwisp ollama
```

## Known limitations
- It does not semantically classify note content.
- It does not detect broken markdown links.
- Sensitive review is filename-based only and intentionally conservative.
- It reports proposed review areas; an agent/user must decide actual moves.
- Candidates that appear discardable should be moved to `QUARANTINE/TRASH/`, never deleted automatically.
