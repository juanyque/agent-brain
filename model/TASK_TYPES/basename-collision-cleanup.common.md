# Basename collision cleanup — task-type guide

Resolve `*.md` basename collisions in the vault. Obsidian resolves `[[wikilinks]]` by basename, not by path, so duplicates make wikilinks non-deterministic. This task uses the deterministic detector + auto-rename script to clean them up, with surgical edits for the references that can't be auto-handled.

> Tooling: `_COMMON/SKILLS/obsidian/scripts/check_basename_collisions.py` + `TOOL.check-basename-collisions.common.md`. The script is the single source of truth for ref-detection regex; never hand-write ad-hoc grep for the same purpose.

## When this applies

- User invokes `/obsidian` and the detector surfaces collision groups.
- User explicitly asks to clean up basename collisions, deduplicate filenames, or unblock `[[wikilink]]` resolution.
- Periodic vault hygiene pass (Weekly job).

## Before starting

- [ ] Vault is a git repo. Renames must use `git mv` to preserve history; revert via `git checkout -- .` is the safety net.
- [ ] Branch / working tree state is clean OR the user accepts mixing this work with in-progress changes.
- [ ] Identify any runtime-governed subtrees that need exclusion (`_AGENTS/CLAUDE/memory/` is the canonical case — agent runtime hardcodes the paths).
- [ ] Read `_COMMON/RULES-FILE-NAMING.common.md` → "Avoiding Obsidian basename collisions" to confirm the target naming convention (`<stem>.<parent-folder-slug>.md`).

## Process

### Phase 1 — Survey

1. Run the detector in dry-run mode:
   ```bash
   python3 ~/.claude/skills/obsidian/scripts/check_basename_collisions.py \
     --vault-root /path/to/vault \
     --exclude-path _AGENTS/CLAUDE/memory
   ```
2. Note the counters:
   - `safe groups` — all four ref counters = 0. Can be `--apply`-ed without thinking.
   - `interactive groups` — at least one ref counter > 0. Per-file attribution determines how many files inside the group are still auto-renamable vs needing edits.
3. Skim the report. For each interactive group, check `Per-file attribution: A/T refs resolved` — `A` is how many references can be auto-handled by the script; `T-A` are ambiguous bare refs that anchor one file as canonical.

### Phase 2 — Auto-rename pass (`--apply`)

4. Re-run with `--apply`:
   ```bash
   python3 ~/.claude/skills/obsidian/scripts/check_basename_collisions.py \
     --vault-root /path/to/vault \
     --exclude-path _AGENTS/CLAUDE/memory \
     --apply
   ```
5. Auto-rename behavior:
   - **Safe groups** (`total == 0`): every file in the group is renamed.
   - **Interactive groups**: each file with `refs→here: 0` is renamed unless the group has unresolved bare refs, in which case the oldest auto-safe file is preserved as the anchor (printed as `← preserved`).
   - **Files with `refs→here > 0`** (needs edits): skipped, listed at the bottom of each group as `(needs edits)`.
6. Verify via `git status` — every change should be an `R` (rename) entry. Spot-check one or two renames in Obsidian to confirm Obsidian's UI also handles the rename gracefully (the script does NOT update Obsidian's link index — Obsidian re-indexes on next open).

### Phase 3 — Interactive review (per "needs edits" group)

For each group still surfaced after `--apply`:

7. Get the deterministic reference list:
   ```bash
   python3 ~/.claude/skills/obsidian/scripts/check_basename_collisions.py \
     --vault-root /path/to/vault \
     --exclude-path _AGENTS/CLAUDE/memory \
     --show-refs <basename-without-md>
   ```
   This uses the same regex as the counter — guaranteed alignment between what the counter saw and what you're about to rewrite.
8. For each ref in the output:
   - Read the file at the printed line (use the line content as your locator; the surrounding 1-3 lines as context).
   - Decide which file in the group the ref intended. Most of the time it's obvious from the path-qualified target or the containing folder for bare md-links.
   - Plan a rewrite: link target + (optionally) link label updated to match the new filename.
9. Default rename preference: **Option A — full rename consistency**. Every duplicate (including the canonical) gets `<stem>.<discriminator>.md`. Update incoming refs to the new name. End-state: no generic basename remains in the vault.
10. Confirm the batch with the user via `AskUserQuestion` if there's any non-trivial decision (label updates, ambiguous intent, etc.).
11. Apply: `Edit` each referencing file → `git mv` each group file.
12. Re-run `--show-refs <stem>` to confirm `total references: 0`.

### Phase 4 — Verify and close

13. Re-run the detector (no `--apply`) — the processed groups should be gone.
14. `git status` summary — count `R` entries vs ` M` entries; should match the work performed.
15. User commits when ready.

## Reference kinds the detector tracks

| Label in output | Pattern | Example |
|---|---|---|
| `wikilink-simple` | `[[stem]]` and variants — alias `[[stem\|label]]`, anchor `[[stem#heading]]`, embed `![[stem]]` | `` `[[VAULT]]` `` |
| `wikilink-path` | `[[a/b/stem]]` and variants, including relative `../X/stem` | `` `[[../Demo App/PROJ-305/analisis\|PROJ-305]]` `` |
| `markdown-simple` | `](stem)` or `](stem.md)` — markdown link, no path | `` `[VAULT](VAULT.md)` `` |
| `markdown-path` | `](a/b/stem.md)` — markdown link with path | `` `[detail](./README.obsidian-vault-common.md)` `` |

Note the asymmetry: Obsidian wikilinks omit `.md`; markdown links can include or omit it. The script's normalization strips `.md` when present so both forms map to the same stem.

## Common gotchas

- **Self-references**: a file may reference itself (`[file.md](file.md)` inside `file.md`). After rename, the self-ref also needs updating.
- **Multi-ref lines**: one line may contain multiple references to different files in the same group. The script's `--show-refs` lists each match with its specific stem; treat each as a separate edit.
- **URL-encoded markdown links**: Obsidian writes `[text](Three%20laws%20of%20motion.md)` for filenames with spaces. The script's `--show-refs` decodes these when categorizing.
- **`..` in wikilink paths**: `[[../X/stem|label]]` is valid and supported. Resolution is relative to the containing file's folder.
- **Per-file safety vs bare-ref anchoring**: in interactive groups with unresolved bare refs, the script preserves one auto-safe file as the canonical anchor. If you rename it during interactive review, the bare refs become unresolved — proceed only if you've also accounted for those refs (Option A).
- **`parent_slug` collision across projects** (rare): two ticket folders with the same name in different parent projects (e.g. `team-tools/PROJ-275/` + `Demo App/PROJ-275/`) auto-rename to the same `<stem>.proj-275.md` and create a new collision. Detector spots it on re-run; fix manually with `git mv` using a grandparent-included discriminator (`<stem>.team-tools-proj-275.md` and `<stem>.demo-app-proj-275.md`). See TOOL doc § "Edge case: `parent_slug` collision across projects".

## Documentation convention

When writing this guide, the detector's TOOL doc, or any doc that mentions Obsidian link syntax, use a basename that **exists in the vault and is unique** for examples — `[[VAULT]]`, `[[README.obsidian-vault-common]]`, `[[AGENTS]]`, etc. — instead of fictional generic names like `[[plan]]`. The link works for the reader (didactic) and cannot create a false-positive collision in the detector. The script's `strip_code_spans` already ignores references inside backticks, but the convention is defense in depth.

## Known false positives

Add new entries to `_COMMON/SKILLS/obsidian/scripts/TOOL.check-basename-collisions.common.md` → "Known false positives" when you find them. The canonical case today:

- `_AGENTS/CLAUDE/memory/projects/<X>/MEMORY.md` — Claude Code memory system reads these by hardcoded paths. Always pass `--exclude-path _AGENTS/CLAUDE/memory`.

## References

- `_COMMON/SKILLS/obsidian/scripts/check_basename_collisions.py` — the detector
- `_COMMON/SKILLS/obsidian/scripts/TOOL.check-basename-collisions.common.md` — tool documentation
- `_COMMON/RULES-FILE-NAMING.common.md` → "Avoiding Obsidian basename collisions" — the naming convention this task enforces
