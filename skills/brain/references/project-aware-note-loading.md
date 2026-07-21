# Project-aware note loading

After the brain is connected and WIP.md has been loaded, attempt to identify the project context from the current working directory. This avoids loading irrelevant notes and saves tokens.

## Step 1: Extract project keywords

Inspect the working directory path and derive 1-3 lowercase keywords that identify the project. Examples:

- `/Users/user/workspace/COMPANY/lerp` → `["lerp", "company"]`
- `/Users/user/projects/my-app` → `["my-app"]`
- `/Users/user/workspace/EXAMPLE-CO/lerp` → `["lerp", "example-co"]`

If the working directory does not clearly map to a project (e.g. the brain itself, a generic temp dir), skip this entire section and fall back to showing all WIP items equally.

## Step 2: Cross-reference with WIP

You already have WIP.md loaded. Mentally match the keywords against active WIP items. If one or more WIP items are clearly related, note them for priority display.

## Step 3: Search brain for related notes

Run the related-notes script to find additional notes beyond WIP:

```bash
python3 ~/.agents/skills/brain/scripts/find_related_notes.py --brain <brain_path> --keywords "lerp example-co"
```

This searches note filenames by default. The script returns JSON with matched notes (path, title, preview line).

## Step 4: Present selection to user

Combine results from Step 2 (WIP cross-reference) and Step 3 (script results). Present them to the user using the `question` tool:

- **Pre-selected**: WIP items that matched the keywords (these are likely relevant)
- **Also found**: Additional notes from the script search
- **Option**: "Search more notes by keyword" — if selected, ask the user for additional keywords, re-run the script with `--mode content`, and present the new results in a new selection form

Only load the notes the user selects. Do not read unselected notes.

## Step 5: Summarize

After loading selected notes, summarize:
1. Project-specific WIP context (highlighted first)
2. General brain status (briefly, if different from above)
3. Any additional notes the user chose to load

## Fallback

If no project keywords could be extracted from the working directory, or if the script returns zero results, show all WIP items equally (current behavior) and mention that no project-specific context was detected.
