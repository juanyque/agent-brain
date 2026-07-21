# canvas_path_repair.py

## Purpose
- Audit Obsidian `.canvas` files for broken `type: "file"` node paths after note moves.
- Repair only those broken paths that can be resolved uniquely and safely.

## Safety model
- Dry-run by default.
- Never guesses when multiple candidates exist.
- Only rewrites a node when the missing target can be matched to exactly one markdown file in the vault by basename.

## Scope
- Accepts one root path and scans all `.canvas` files under it.

## Status meanings
- `OK`: the file node path already exists.
- `REWRITE_CANDIDATE`: the path is broken, but one unique replacement was found.
- `MISSING`: no replacement found.
- `AMBIGUOUS`: multiple possible replacements found.

## Usage

### Dry-run
```bash
python3 ~/.agents/skills/obsidian/scripts/canvas_path_repair.py --vault-root . --scope-root .
```

### Apply safe rewrites
```bash
python3 ~/.agents/skills/obsidian/scripts/canvas_path_repair.py --vault-root . --scope-root . --apply
```

## Logging
- Every run prints to the console.
- Every run overwrites the latest execution log at:
  - `~/.agents/skills/obsidian/scripts/canvas_path_repair.log`

## Known limitations
- It only repairs canvas nodes of `type: "file"`.
- It resolves by markdown basename only, not by semantic similarity.
- It does not yet try to repair embedded image/file references inside markdown notes.
