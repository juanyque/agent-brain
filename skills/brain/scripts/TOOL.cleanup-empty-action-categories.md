# cleanup_empty_action_categories.py

## Purpose
- Remove empty placeholder action categories from daily notes.
- Daily notes created from `TEMPLATE.daily-note.md` ship with scaffolding action categories (`* [[LEARN]]:`, `* [[READ]]:`, `* [[VIEWED]]:`, etc.). At end-of-day cleanup the unused ones should be removed while preserving categories with real content. See `VAULT.md` § JOURNAL: *"Empty template action categories should be cleaned when a day is closed, while preserving real content and metadata"*.

## Safety model
- **Dry-run by default.** Pass `--apply` to write changes.
- Operates only inside the `# Actions` section. Frontmatter, `# Sessions`, other sections, navigation links, and trailing newlines are preserved byte-for-byte.
- Files without a `# Actions` section are skipped (legacy daily shape, non-daily notes).
- A category is removed only if its child block is **empty** or contains **exclusively known placeholder lines** (substring-matched against the per-category list in `PLACEHOLDER_SUBSTRINGS`). If a category has any real child it is preserved entirely — individual placeholder children within a kept category are *not* dropped (too aggressive — risk of removing user content that looks like scaffolding).

## Usage

### Dry-run on every daily under `JOURNAL/`
```bash
python3 ~/.agents/skills/obsidian/scripts/cleanup_empty_action_categories.py --vault-root /path/to/vault
```

### Apply
```bash
python3 ~/.agents/skills/obsidian/scripts/cleanup_empty_action_categories.py --vault-root /path/to/vault --apply
```

### Narrow the glob (e.g. only today's daily)
```bash
python3 ~/.agents/skills/obsidian/scripts/cleanup_empty_action_categories.py \
  --vault-root /path/to/vault --glob "2026-05-25.md" --apply
```

### Other journal subdir
```bash
python3 ~/.agents/skills/obsidian/scripts/cleanup_empty_action_categories.py \
  --vault-root /path/to/vault --journal-subdir Daily --apply
```

## What counts as empty
A category line (`* [[NAME]]:` with `NAME` matching `[\w-]+`, e.g. `[[FAMILY-FRIENDS]]`) is followed by zero or more indented bullet children. Detection:

- **No children** → REMOVE.
- **Placeholder-only children** (all children match a `PLACEHOLDER_SUBSTRINGS[NAME]` entry) → REMOVE.
- **Any real child** → KEEP the whole group as-is.

Current placeholder map (extend in-place as the template grows):
- `OBJECTIVES`: `[[Objective from WIP/OBJECTIVES.md]]`
- `WORK`: `[[Project or context]]`, `Detailed work performed for that project/context today`

## When this runs
- **At day rollover** — invokable by the `/obsidian` skill during Flow 1 step 3 (*"Clean the previous existing daily note by removing empty action categories"*), scoped to the previous daily via `--glob <prev-date>.md`, once wired into the maintenance scheduler. Today still callable on demand.
- **As a batch pass** to clean up an accumulated stack of dailies.
- **On demand**, invoked manually by the user or agent.

## Known limitations
- Legacy-shape dailies (`## Daily Tasks`, `## Daily Objetives`) without `# Actions` are skipped. Migration is tracked separately (see `WIP/WIP.md` — JOURNAL legacy bulk migration task).
- Placeholder detection is substring-based per category. New template scaffolding lines require manual additions to `PLACEHOLDER_SUBSTRINGS`.
- Individual placeholder children inside a category that also has real content are NOT removed; the script's unit of removal is the full category, not the line.

## Logging
- Stdout only. No `.log` file is written; callers (or the user) capture stdout if needed.
