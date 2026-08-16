# attachments_audit.py

## Purpose
- Audit every file recursively below `ATTACHMENTS/` folders under a chosen vault scope.
- Determine whether each attachment should stay where it is, move with the notes that reference it, or be quarantined for manual review.
- Treat subdirectories below `ATTACHMENTS/` as non-conforming input to flatten safely, never as information structure to preserve.

## Scope
- The script accepts one root path and audits **all `ATTACHMENTS/` folders found under that path**.
- If the root path is an `ATTACHMENTS/` folder or a subtree below one, that exact path is the audit boundary. This permits a narrow repair without scanning sibling projects or active-process trees.
- It scans **all markdown notes in the vault** for references, but only proposes actions for attachments inside the discovered `ATTACHMENTS/` folders under the chosen scope.
- Use the narrowest completed scope. Do not include a subtree still owned by an active process.

## Safety rules
- Dry-run by default.
- Never deletes anything.
- Automatic moves only happen in `--apply` mode and only for clearly safe cases.
- Any ambiguity stays unresolved and is reported for manual review.
- If the vault is a Git repository, safe moves in `--apply` mode should use `git mv` for better traceability.

## Current decision model
- `KEEP_LOCAL`: all referencing notes live in the same folder as the audited attachment directory.
- `RELOCATE_CANDIDATE`: all referencing notes live in a single other folder, so the attachment can move to that folder's `ATTACHMENTS/` directory.
- `ORPHAN_CANDIDATE`: no references found; proposed destination is `QUARANTINE/ATTACHMENTS/`.
- `CONFLICT_MULTI_NOTE`: references exist from notes in multiple folders, so there is no safe automatic destination.
- `CONFLICT_DUPLICATE_BASENAME`: multiple files under one audited `ATTACHMENTS/` root share a basename, so basename-only Obsidian references cannot identify a safe automatic source.

## Destination policy
- Attachments belong near the notes that reference them.
- The destination is based on the **actual folder of the referencing note**, not only on a top-level area.
- Destination `ATTACHMENTS/` directories are flat. Nested source paths are not reproduced at the destination.
- Examples:
  - `JOURNAL/2023/note.md` -> `JOURNAL/2023/ATTACHMENTS/`
  - `Clients/Cheerfy.md` -> `Clients/ATTACHMENTS/`
  - `MEMORY/Clients/Cheerfy/note.md` -> `MEMORY/Clients/Cheerfy/ATTACHMENTS/`

## Usage

### Dry-run
```bash
python3 ~/.agents/skills/brain/scripts/attachments_audit.py --brain-root . --scope-root JOURNAL --quarantine-dir QUARANTINE/ATTACHMENTS
```

### Apply safe moves
```bash
python3 ~/.agents/skills/brain/scripts/attachments_audit.py --brain-root . --scope-root JOURNAL --quarantine-dir QUARANTINE/ATTACHMENTS --apply
```

### Scope a single ATTACHMENTS folder explicitly
```bash
python3 ~/.agents/skills/brain/scripts/attachments_audit.py --brain-root . --scope-root JOURNAL/ATTACHMENTS --quarantine-dir QUARANTINE/ATTACHMENTS
```

### Scope one non-conforming subtree without auditing its siblings
```bash
python3 ~/.agents/skills/brain/scripts/attachments_audit.py --brain-root . --scope-root 'WIP/ATTACHMENTS/<project>' --quarantine-dir QUARANTINE/ATTACHMENTS
```

## Logging
- Every run prints to the console.
- Every run also overwrites the latest execution log at:
  - `~/.agents/skills/brain/scripts/attachments_audit.log`

## Apply-mode behavior
- Safe relocation and quarantine moves are applied only with `--apply`.
- Empty nested directories and their empty source `ATTACHMENTS/` root are removed after safe moves.

## Known limitations
- It only understands markdown `[[...]]` references by attachment filename.
- It does not rewrite note contents; it assumes Obsidian's link resolution by filename remains valid after a move.
- It does not auto-resolve duplicate names or multi-folder ownership conflicts.
- It is intentionally conservative.
