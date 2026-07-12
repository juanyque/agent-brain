# Boyscout Backlog

The backlog is a persistent Markdown file at `~/.boyscout/backlog.md` that
accumulates findings across sessions. It lets the boyscout skill group related
findings detected in different sessions and produce a single PR per logical target.

## Location

```
~/.boyscout/backlog.md
```

Global (not tied to any repo or worktree). Create the directory on first write:

```bash
mkdir -p ~/.boyscout
```

## File Format

```markdown
# Boyscout Backlog

<!-- Auto-managed by the boyscout skill. Edit manually with care. -->

## <repo> / <component>

### [effort][type] one-line summary
- status: pending
- detected: YYYY-MM-DD · session <branch-or-ticket>
- last_seen: YYYY-MM-DD · session <branch-or-ticket>
- times_seen: N
- location: path/to/file.ext (or skill-gap path)
- type: docs-gap
- effort: XS
- risk: low
- context: brief description of the main task when this was found
- how_found: how the issue was discovered (error output, code read, observation, etc.)
- action: What to do to fix this

---

## <repo> / <other-component>

### [effort][type] another finding
...
```

Each H2 section is one **target key** (`<repo> / <component>`). Each H3 under it
is one finding. Separate findings within the same target with `---`.

## Writing rules

**Never rewrite the entire file.** Always read the current file first, make the minimum targeted change, then write back. Preserve all other entries exactly — no reformatting, no reordering, no field renaming.

### Adding a new finding
1. Read `~/.boyscout/backlog.md`.
2. If `## <target>` already exists: insert the new `### ...` block (preceded by `---`) immediately before the next `##` heading, or at the end of the section if it is the last one.
3. If `## <target>` does not exist: append a blank line, the new `## <target>` heading, and the `### ...` block at the end of the file.
4. Write the full updated file back.

### Removing a finding
1. Read the current file.
2. Delete the H3 block. The block spans from the `### ` line through all property lines beneath it. The terminator depends on what follows the block in the file:
   - If a `---` separator immediately follows the property lines: delete through and including that `---`.
   - If another `### ` heading follows directly (no separator between them): delete up to (but not including) that next `### `.
   - If the H3 is the last entry in its `##` section: delete up to (but not including) the next `## ` heading, or to end-of-file if no more `## ` headings exist. Do NOT delete a blank line that belongs to the next section.
3. If the H2 section is now empty (no `### ` blocks remain under it), remove the H2 heading and its trailing blank line.
4. Write the file back.

### Updating `last_seen` / `times_seen` in place
1. Read the current file.
2. Locate the exact `- last_seen: ...` and `- times_seen: N` lines under the matching `### ` heading.
3. Replace only those two lines. Do not touch any other line in the file.
4. Write the file back.

## Lifecycle

| Event | Action |
|-------|--------|
| Boyscout scan finds a new finding | Write to backlog with `status: pending`, `times_seen: 1` |
| A later session independently detects the same finding | Update `last_seen` + increment `times_seen` (no duplicate) |
| User selects a finding → Fixed (PR created) | Remove from backlog |
| User selects a finding → Ticketed (Jira) | Remove from backlog (Jira is source of truth) |
| User skips a finding (was `new`) | Add to backlog as `pending` |
| User skips a finding (was already `pending`) | No change — leave as-is |

**Deep-mode coexistence.** Findings produced by `/boyscout deep` live in the same
`~/.boyscout/backlog.md`. They are distinguished by their `target` namespace (`claude-skills /
…`, `claude-config / …`, `claude-memory / …`, `claude-scripts / …`) and by their `type`
(`repeated-instruction`, `automation-opportunity`, `promotable-flow`). Lifecycle and dedup
rules are identical to codebase findings. Extra fields (see `finding-schema.common.md`) are
persisted as additional `- key: value` lines under the H3 block.

## Dedup matching

Two findings match when they share:
1. The same `target` key (H2 section header)
2. The same one-line summary (H3 heading text, ignoring `[effort][type]` prefix)

On a match: update `last_seen` + increment `times_seen`; do NOT create a duplicate entry.

## Staleness

A finding is **stale** when `last_seen` is more than 7 days before today. Stale
findings are shown as `[STALE?]` in the selection UI. They remain in the backlog
until the user explicitly selects and discards them — the skill never auto-deletes.

A finding with `times_seen` > 1 is less likely to be stale even if `last_seen` is
old: it was independently confirmed across multiple sessions.

## Example

```markdown
# Boyscout Backlog

<!-- Auto-managed by the boyscout skill. Edit manually with care. -->

## your-project / boyscout-skill

### [XS][skill-gap] allowed-tools missing gh for PR guard
- status: pending
- detected: 2026-04-23 · session PROJ-255
- last_seen: 2026-04-30 · session PROJ-260
- times_seen: 2
- location: user-skill/boyscout/SKILL.md
- type: skill-gap
- effort: XS
- risk: low
- context: reviewing PR #38 (boyscout persistent backlog)
- how_found: noticed allowed-tools list while reading SKILL.md diff
- action: Add `Bash(gh pr view:*)` to allowed-tools frontmatter

---

## your-project / card-simulator-claude-plugin

### [XS][docs-gap] cs_smoke_full missing from ZSH Wrappers table
- status: pending
- detected: 2026-04-16 · session PROJ-200
- last_seen: 2026-04-23 · session PROJ-255
- times_seen: 2
- location: card-platform-team/Card Simulator/claude-plugin/CLAUDE.md
- type: docs-gap
- effort: XS
- risk: low
- context: implementing PROJ-200 (Card Simulator workspace setup)
- how_found: ran cs_help and compared output against CLAUDE.md wrappers table
- action: Add row `| cs_smoke_full | Like cs_smoke but shows DB diffs per operation |`
```
