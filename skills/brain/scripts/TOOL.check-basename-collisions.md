# check_basename_collisions.py

## Purpose
- Detect `*.md` basename collisions across the vault.
- Same basename in different folders breaks Obsidian's `[[wikilink]]` resolution into a non-deterministic pick (same-folder first, then implementation-defined). The detector surfaces every collision, counts incoming `[[<stem>]]` references across `.md` and `.canvas` files, and proposes the right rename strategy per group.

## Safety model
- **Always read-only.** No `--apply` flag. The script never executes renames or rewrites wikilinks — those steps are owned by the user + agent acting on the report.
- Top-level dotfile dirs (`.git/`, `.obsidian/`, ...) and top-level symlinks (e.g. `_COMMON` → vault-common checkout) are skipped, mirroring `cleanup_ds_store.py`'s containment model. Everything else under visible top-level directories is walked.
- `--exclude-path` (repeatable) skips additional subtrees from BOTH the duplicate detection AND the wikilink count. Use for paths governed by external runtimes — see "Known false positives".

## Usage

```bash
python3 ~/.agents/skills/brain/scripts/check_basename_collisions.py --brain-root /path/to/brain
```

With exclusion (recommended for vaults using `_AGENTS/CLAUDE/memory/`):
```bash
python3 ~/.agents/skills/brain/scripts/check_basename_collisions.py \
  --brain-root /path/to/brain \
  --exclude-path _AGENTS/CLAUDE/memory
```

The full report is written to stdout. Pipe to a file if needed:
```bash
python3 ~/.agents/skills/brain/scripts/check_basename_collisions.py --brain-root /path/to/brain > collisions.md
```

## Reference kinds (the four counters)

Every reference is classified as one of four kinds:

| Label in output | Pattern | Example |
|---|---|---|
| **`wikilink-simple`** | `[[stem]]` and variants — alias `[[stem\|label]]`, anchor `[[stem#heading]]`, embed `![[stem]]` | `` `[[VAULT]]` `` |
| **`wikilink-path`** | `[[a/b/stem]]` and variants — path-qualified, including relative `../X/stem` | `` `[[../PROJ-305/analisis\|PROJ-305]]` `` |
| **`markdown-simple`** | `](stem)` or `](stem.md)` — markdown link, no path | `` `[label](README.md)` `` |
| **`markdown-path`** | `](a/b/stem.md)` and variants — markdown link with path | `` `[label](./folder/README.md)` `` |

Note the asymmetry between wikilink and markdown link syntax: Obsidian wikilinks omit `.md`; markdown links can include or omit it. The script's normalization strips `.md` when present so both forms map to the same stem.

## Output shape

Each duplicate group has a header showing instance count + per-kind reference counts:

```
## `WIP.md` — 3 instances · references: wikilink-simple=336 wikilink-path=223 markdown-simple=0 markdown-path=0 (total=559)
  Canonical - WIP/WIP.md   (created=2026-05-21, depth=1)
   - WIP/SESSIONS/old/WIP.md   (created=2026-05-22, depth=3)
   - MEMORY/Projects/old/WIP.md   (created=2026-05-22, depth=4)
    → suggest rename: WIP/SESSIONS/old/WIP.md → WIP/SESSIONS/old/WIP.old.md
    → suggest rename: MEMORY/Projects/old/WIP.md → MEMORY/Projects/old/WIP.old.md
```

For groups with **zero** references in all four kinds, the canonical concept doesn't apply — rename ALL:

```
## `plan.md` — 67 instances · references: wikilink-simple=0 wikilink-path=0 markdown-simple=0 markdown-path=0 (total=0)
  No incoming references found — safe to rename ALL.
   - WIP/.../PROJ-300/plan.md   (created=2026-05-22, depth=4)
   ...
    → suggest rename: WIP/.../PROJ-300/plan.md → WIP/.../PROJ-300/proj-300.plan.md
   ...
```

## Per-group decision logic
1. **Scan `.md` + `.canvas` files** vault-wide for `[[<stem>]]` references whose stem matches a duplicate basename. The match covers `[[stem]]`, `[[stem|alias]]`, `[[stem#section]]`, `[[stem#section|alias]]`, and embed `![[stem]]` variants. Path-qualified wikilinks (`[[folder/stem]]`) are NOT counted — they already disambiguate.
2. **`incoming == 0`**: no existing reference uses the bare basename, so renaming every instance is safe. Suggest a rename for every file.
3. **`incoming >= 1`**: existing references are basename-ambiguous. Pick a canonical (heuristic below) and rename the rest. Wikilinks may silently re-resolve to the canonical post-rename — review per non-canonical with the agent before applying.

### Canonical heuristic (only used when `incoming >= 1`)
1. **Oldest creation date** (`git log --diff-filter=A --reverse --format=%cI`; filesystem `st_birthtime` / ctime as fallback for untracked files). The original file usually exists first; collisions are almost always accidental later additions, and references probably meant the original.
2. **Shallowest depth** as tiebreaker.
3. **Lexicographic path** as final tiebreaker (deterministic ordering).

Wikilink-incoming COUNTS are not used to pick the canonical — `[[basename]]` references are ambiguous by construction and cannot point at a specific file. The count only gates "rename all vs canonical + rename rest".

## Known false positives
Some collision groups are governed by conventions outside Obsidian's wikilink scope; renaming would break the convention. Exclude these via `--exclude-path`.

- **`_AGENTS/CLAUDE/memory/`** — the Claude Code memory system reads `~/.claude/memory/projects/<X>/MEMORY.md` by hard-coded path (see global `CLAUDE.md` "Memoria"). Renaming any `MEMORY.md` under this subtree breaks the runtime. Always pass `--exclude-path _AGENTS/CLAUDE/memory` when the vault has this structure.

Add new entries here as they are discovered.

## Pattern-driven duplicates
For repeated-pattern duplicates (e.g. `plan.md` × 67 in per-ticket folders), the rename suggestions are technically correct but the right structural fix is the broader per-ticket consolidation tracked in `WIP/WIP.md`, not individual renames. The report's footer reminds the user.

## Listing references (interactive review)

To process a group with references, use `--show-refs <basename>` instead of writing ad-hoc grep commands. This reuses the script's own regex (single source of truth), so the references the agent finds are exactly the ones the counter found.

```bash
python3 ~/.agents/skills/brain/scripts/check_basename_collisions.py \
  --brain-root /path/to/brain \
  --exclude-path _AGENTS/CLAUDE/memory \
  --show-refs decisiones
```

Output: every reference categorized by the 4 kinds, each line is `path:line_no` followed by the matching line content. The agent uses this list to decide per-reference rewrites; the user confirms; the agent applies edits + `git mv`.

## Per-file attribution model

The script computes references at **two granularities**:

1. **Group level** (`refs:` line in the header): how many references exist of each kind for the group's basename, regardless of which file they actually target.
2. **Per-file level** (`refs→here:` next to each file): which file each reference actually resolves to.

Per-file resolution is best-effort:
- **Path-qualified refs** (`[[a/b/stem]]`, `[text](a/b/stem.md)`, including `./` and `../` relative paths): the path component is resolved against the containing file's folder; if it lands on exactly one file in the group, that's the target.
- **Bare refs in a containing folder that has a same-folder group file** (`[[stem]]` or `](stem.md)` written from `folder/foo.md` while `folder/stem.md` exists in the group): resolved to the same-folder file (Obsidian's default resolution).
- **Bare refs whose containing folder has no same-folder group file**: counted as "ambiguous" — we can't tell which group file they were intended for.

`Per-file attribution: A/T refs resolved` in the report tells you how many of the group's references resolved to a specific file (`A`) out of the total (`T`). The unresolved count (`T-A`) is the number of "ambiguous bare refs".

## Auto-apply (`--apply`)

```bash
python3 ~/.agents/skills/brain/scripts/check_basename_collisions.py \
  --brain-root /path/to/brain \
  --exclude-path _AGENTS/CLAUDE/memory \
  --apply
```

Auto-rename rule, applied per group:

1. Every file with **`refs→here: 0`** is auto-safe to rename (no specific reference targets it).
2. If the group has any **ambiguous bare refs** (`T-A > 0`), one auto-safe file must remain unrenamed to anchor those refs to the original basename — the script picks the **oldest auto-safe file** as the preservation anchor and prints it as `← preserved (anchors ambiguous bare refs)`.
3. All other auto-safe files are renamed via `git mv` (when the vault is a git repo) or plain `mv`.
4. Files with **`refs→here > 0`** are tagged `(needs edits)` and skipped — they require the interactive workflow below.

This handles even very large groups efficiently: e.g. `plan.md × 67` with 10 refs attributing to 4 specific files becomes 62 auto-renames + 4 interactive cases in a single `--apply` invocation.

## Default rename preference: Option A (full rename consistency)

For groups with references, two end-states are conceptually possible after cleanup:

- **Option A — full rename**: every instance ends up with `<discriminator>.<stem>.md`. After cleanup, **no file** in the vault has the original generic basename. Any future `[[stem]]` wikilink that someone writes will appear unresolved, which is the correct signal that the basename is generic and a more specific reference is needed.
- **Option B — preserve canonical**: rename only the duplicates; keep one canonical instance with the original basename. After cleanup, the canonical remains discoverable via `[[stem]]`.

The script's auto-apply implements a hybrid: rename auto-safe files, preserve one anchor only when bare refs require it. For the **interactive review** of `(needs edits)` files, the default convention is **Option A** — also rename the canonical, even if it requires updating its incoming refs, so the end-state is fully consistent.

If a specific group has a strong reason for Option B (e.g. the canonical is a widely-linked index file like `WIP.md` at vault root, and breaking inbound `[[WIP]]` links would be costly), explicitly choose Option B for that group via the interactive workflow.

## Wikilink-safety workflow

- **For groups with all counters = 0**: `--apply` renames the whole group safely. There are no incoming references to break.
- **For groups with any counter > 0** (per non-canonical file):
  1. Run `--show-refs <stem>` to get the deterministic reference list.
  2. Agent inspects each match, infers intent from the surrounding context (which version the link meant — usually obvious from path-qualified refs or the containing folder), proposes per-link rewrites.
  3. User confirms via AskUserQuestion (batched per group is fine).
  4. Agent applies the rewrites (Edit each referencing file) + `git mv` for the file itself.
  5. Re-run the detector to confirm the group is gone.

## When this runs
- **On demand** during vault hygiene reviews.
- Hookable into `maintenance_scheduler.py` (Weekly cadence is appropriate — read-only, low urgency).

## Known limitations
- No automated rename or wikilink rewriting. Intentional — see Safety model.
- Pattern-driven groups (10+ instances) produce technically correct but practically useless individual renames; the right fix is structural consolidation outside this tool's scope.
- Creation date comes from git when available; for vaults outside git or untracked files the filesystem timestamp is used, which is less reliable across machine transfers.
- Wikilink count covers `.md` and `.canvas`. Other Obsidian-aware formats (e.g. `.excalidraw`) are not scanned; extend `LINK_BEARING_EXTS` if needed.

## Edge case: `parent_slug` collision across projects

When two ticket folders share the same name across different parent projects (e.g. `team-tools/PROJ-275/plan.md` and `Demo App/PROJ-275/plan.md`), the script's `parent_slug()` heuristic produces the same discriminator (`proj-275`) for both. After auto-rename, both files end up as `proj-275.plan.md` → new collision in different folders.

**Detection**: re-run the detector after `--apply`. If a new collision appears whose suggested rename is `<discriminator>.<discriminator>.<stem>.md` (the discriminator repeated), this is the edge case.

**Manual fix recipe**:
1. For each colliding file, build a discriminator that includes the **grandparent** folder name:
   ```bash
   git mv "MEMORY/.../team-tools/PROJ-275/proj-275.plan.md" \
          "MEMORY/.../team-tools/PROJ-275/team-tools-proj-275.plan.md"
   git mv "MEMORY/.../Demo App/PROJ-275/proj-275.plan.md" \
          "MEMORY/.../Demo App/PROJ-275/demo-app-proj-275.plan.md"
   ```
2. Re-run the detector to confirm.

The script does not auto-disambiguate because the grandparent choice requires human context and the case is rare by construction.

## Documentation convention: prefer real-but-unique basenames in examples

When writing TOOL documentation, TASK_TYPE guides, or any doc that mentions Obsidian link syntax, use a basename that **exists in the brain and is unique** (e.g. `[[BRAIN]]`) instead of a fictional generic name (`[[plan]]`, `[[notes]]`).

**Why**:
- The link works for the reader (didactic).
- It cannot create a false-positive collision in this detector (no duplicate exists).
- It survives the strip-code-spans defense — even if you forget to wrap the example in `` ` `` backticks, the link is harmless.

The detector already strips code spans (inline `` `text` `` and triple-backtick fenced blocks), so any reference inside backticks is correctly ignored. The "real-but-unique basename" convention is defense in depth.

## Logging
- Stdout only. No `.log` file is written; callers (or the user) capture stdout if needed.
