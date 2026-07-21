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

**The path MAY be a symlink.** `~/.boyscout/backlog.md` is often a symlink to a shared document (e.g. an Obsidian vault note), so the backlog is one shared file across every session and machine view. Two consequences:

- **The Claude Code harness refuses `Edit`/`Write` through a symlink.** Editing the backlog via the harness's file tools fails or silently targets the link, not the target. Use `scripts/backlog.py` (plain Python file I/O, which follows the link transparently) for every mutation, or resolve the real path first (`readlink -f`).
- **Concurrency: the backlog is shared mutable state.** Parallel sessions may edit it at the same time, and a backlog snapshot read at session start can be stale by the time Post-action writes. Re-read immediately before mutating, and prefer the narrowest `backlog.py` subcommand (`touch`, `remove`, `add`) over a full-file rewrite so concurrent edits to *other* entries are not clobbered.

## Tooling — `scripts/backlog.py` owns the format

All mutations go through `scripts/backlog.py`, which owns the parse/serialize contract so the LLM never hand-edits the file with prose rules (the failure mode that once orphaned an entry):

| Need | Command |
|------|---------|
| Check integrity before/after a change | `backlog.py validate` (non-zero on a broken `###`/property structure or banned provenance) |
| Show findings (filter/JSON) | `backlog.py list [--target T] [--type T] [--stale] [--json]` |
| Add a pending finding | `backlog.py add --target … --summary … --type … --effort … --risk … [--impact … --confidence … --location … --context … --how-found … --action …]` |
| Consume / ticket-remove a finding | `backlog.py remove --target … --summary …` |
| Dedup bump (Step 1c) | `backlog.py touch --target … --summary … [--date YYYY-MM-DD]` |
| Report/remove stale entries | `backlog.py sweep [--days N] [--remove]` |
| Detect duplicate (target, summary) | `backlog.py dedup-check` (non-zero if any) |

`--file PATH` overrides the default `~/.boyscout/backlog.md` (used for tests against a fixture — never test against the real shared backlog). As a least-privilege guard, writes are refused for a `--file` that resolves outside `$HOME` or the system temp dir unless `--allow-foreign-file` is passed (the real backlog — including a vault symlink — resolves under `$HOME`, and fixtures live in temp, so normal use is unaffected). The skill must **never** pass `--allow-foreign-file` autonomously — it exists only for explicit human/test use; normal operation always targets the default backlog or a temp fixture. The hand-written surgical-edit recipes below remain the **specification** `backlog.py` implements; read them to understand the format, but call the script to apply changes.

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
- impact: medium
- confidence: high
- context: brief description of the main task when this was found
- how_found: how the issue was discovered (error output, code read, observation, etc.)
- action: What to do to fix this

---

Notes on the example:
- `impact` and `confidence` are recommended for all findings and required for the three deep-mode types (`repeated-instruction`, `automation-opportunity`, `promotable-flow`) — see `finding-schema.md` for per-level heuristics. `confidence: low` blocks auto-fix at Step 3 of the SKILL workflow.
- `source` is omitted when the value is `codebase` (the default for normal `/boyscout` scans). `/boyscout deep` adds `- source: deep-scan` to its findings.
- Deep-mode types also carry type-specific extra fields (`instruction_intent`, `occurrences`, `pattern_summary`, `target_skill`, `proposed_script_name`, `flow_summary`, `proposed_skill_name`, `genericity_evidence`) as additional `- key: value` lines under the H3. See `finding-schema.md`.

## <repo> / <other-component>

### [effort][type] another finding
...
```

Each H2 section is one **target key** (`<repo> / <component>`). Each H3 under it
is one finding. Separate findings within the same target with `---`.

## Writing rules

**Never rewrite the entire file.** Always read the current file first, make the minimum targeted change, then write back. Preserve all other entries exactly — no reformatting, no reordering, no field renaming. In practice this means calling `scripts/backlog.py` (see above) rather than editing by hand.

**Anti-provenance rule.** Do not annotate backlog entries with provenance metadata that git history and session notes already cover. Concretely:

- No HTML comments inside a finding block (`<!-- added in session X -->`, `<!-- TODO -->`, etc.). The only sanctioned comment is the top-of-file `<!-- Auto-managed… -->` banner.
- No stamp fields: `version`, `session`, `session_id`, `added_by`, `author`, `commit`. The schema's `detected` / `last_seen` *session labels* are detection provenance and are allowed; a standalone provenance field is not.

`backlog.py validate` enforces this — it exits non-zero on an in-block HTML comment or a banned field, so the rule is checked, not just documented.

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
| Boyscout scan finds a new finding | Write to backlog with `status: pending`, `times_seen: 1` (default — no decision pressure) |
| A later session independently detects the same finding | Update `last_seen` + increment `times_seen` (no duplicate) |
| User opts into attack-now on a backlog entry → PR landed | **Consume** — remove from backlog (see "Consume on attack" below) |
| User opts into attack-now on a `new` finding (never written) → PR landed | No removal needed — nothing to consume |
| User selects a finding → Ticketed (Jira) | Remove from backlog (ticket tracker is source of truth) |
| User explicitly leaves a `pending` finding in the backlog | No change — leave as-is |

**Deep-mode coexistence.** Findings produced by `/boyscout deep` live in the same
`~/.boyscout/backlog.md`. They are distinguished by their `target` namespace (`agent-skills /
…`, `agent-config / …`, `agent-memory / …`, `agent-scripts / …`) and by their `type`
(`repeated-instruction`, `automation-opportunity`, `promotable-flow`). Lifecycle and dedup
rules are identical to codebase findings. Extra fields (see `finding-schema.md`) are
persisted as additional `- key: value` lines under the H3 block.

## Backward compatibility — legacy pending entries without `impact` / `confidence`

Pending entries written before these fields were introduced (e.g. the `source: deep-scan` batch logged on the first deep-scan run) remain valid without them. When Step 3 of the SKILL workflow encounters a legacy entry, treat the missing fields as follows:

- missing `confidence` → behave as `confidence: medium` (the decision matrix's "ambiguous → ask explicitly" path);
- missing `impact` → behave as `impact: medium` for matrix lookup.

Never auto-fix a legacy entry without confirming the missing dimensions with the user first — the matrix's clear-action rows all require `confidence: high` explicitly. Existing entries gain `impact` / `confidence` incrementally as they get touched (attacked, ticketed, or dedup-updated with a richer detection), not via bulk backfill.

## Consume on attack

The "consume on attack" pattern lets the backlog stay clean as findings are resolved. When a user opts into attack-now on a backlog entry and the fix lands successfully (PR opened, or commit pushed to an existing PR), the entry is **deleted** from the backlog — not updated, not marked done in-place. The Jira / Git history (PR title referencing the target, commit messages) carry the provenance from that point on.

**Trigger condition (all must be true):**

1. The attack started from a `pending` finding (the entry exists in `~/.boyscout/backlog.md`).
2. The fix completed successfully — PR landed in `OPEN` state, or a follow-up commit pushed to an existing PR under review.
3. The user did not request the entry be kept (rare; e.g. they may want to track a partial fix as a continuing finding).

**Surgical-edit recipe (same rules as "Removing a finding"):**

1. Read `~/.boyscout/backlog.md`.
2. Locate the H3 block by `target` (H2 section) + one-line summary (H3 heading).
3. Delete the block per the boundary rules in "Removing a finding" above.
4. If the H2 section is now empty, remove the H2 heading and its trailing blank line.
5. Write the file back.

**When the attack starts from a `new` finding (never written to the backlog):** no removal is needed — there is nothing to consume. The finding simply transitions from `new` to resolved without ever entering the backlog file.

**When attack fails or PR is closed unmerged:** do NOT consume. The finding stays as `pending` (write it to the backlog if it was `new`); on the next boyscout scan the dedup logic will catch it and increment `times_seen`.

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
