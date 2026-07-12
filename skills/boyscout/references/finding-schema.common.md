# Finding schema

Each boyscout finding captures the following fields. Collect them during Step 1
(identify) and render them during Step 2 (selection form).

| Field | Purpose | Allowed values / notes |
|---|---|---|
| One-line summary | Shown in the fzf list and numbered fallback | ≤ 80 chars |
| Target | Logical grouping key — determines which findings share a PR | `<repo> / <component>` — see convention below |
| Location | File(s), line(s), function/test name | `path/to/file.py:42` or `module.function` (for `skill-gap`: see convention below) |
| Type | Tagged bucket for filtering and ticket labeling | `flaky-test` \| `broken-script` \| `refactor` \| `missing-test` \| `dead-code` \| `docs-gap` \| `skill-gap` \| `tech-debt` \| `side-task` \| `repeated-instruction` \| `automation-opportunity` \| `promotable-flow` \| `other` |
| How found | Provenance — error message, observation, test failure, code review | Free text; persisted to backlog |
| Context | The main task or investigation that surfaced this finding | Free text, e.g. `"reviewing PR #38"`, `"implementing PROJ-258"`; persisted to backlog |
| Estimated effort | Feeds the Step 3 decision table | `XS` (<15 min) \| `S` (<1h) \| `M` (<1 day) \| `L` (>1 day) |
| Risk | Chance of regression or needing domain knowledge | `low` \| `medium` \| `high` |
| Suggested action | What fixing it would look like | File edits, test changes, refactor outline |
| Status | Origin of this finding | `new` (found in this session) \| `pending` (loaded from backlog) |
| Detected | First detection date + session context | ISO date string, e.g. `2026-04-23 · session PROJ-255` — see **session label format** below |
| Last seen | Most recent session that independently detected this finding | ISO date string + session context; updated on dedup match |
| Times seen | Count of independent re-detections across sessions | Integer ≥ 1 |

**Session label format:** `YYYY-MM-DD · session <ticket-or-tool-label>` where `<ticket-or-tool-label>` is one of:

- A Jira ticket code when the scan happened during ticket work: `session PROJ-255`
- The literal `boyscout` for standalone scans not tied to a ticket: `session boyscout`
- Either of the above with a parenthetical when context helps: `session boyscout (PROJ-275 wrap-up)`, `session PROJ-260 PR review`

Use the most specific form that fits; the parenthetical is optional. The label is informational and not parsed by the skill — consistency helps humans grep the backlog.

**`skill-gap` location convention:** The Location field for `skill-gap` findings MUST include the
fully-qualified skill path — `<plugin-name>/<skill-name>/SKILL.md`
(e.g. `card-engineer/pr-review/SKILL.md`) or for user skills:
`user-skill/<skill-name>/SKILL.md` (e.g. `user-skill/boyscout/SKILL.md`).
Never use just `SKILL.md` — it is ambiguous when multiple skills are installed.
The `<plugin-name>` is the directory prefix under the skills folder (e.g. `card-engineer`,
`user-skill`); it corresponds to the namespace before the colon in the skill's display name
(e.g. `card-engineer` in `card-engineer:pr-review`).
Note: strip the `_<username>` suffix from the filesystem directory name — use
only the base skill name (e.g. `boyscout`, not `boyscout_juan.garcia`).

**Target key convention:** The `target` field is the logical grouping key used to
batch related findings into a single PR. Format: `<repo> / <component-name>`.

- Use the repo short name (e.g. `consumer-eng-tools`, `all-the-things`)
- Use a logical component name that maps to "what PR would fix all of these":
  - `boyscout-skill` → groups SKILL.md + references/*.md for the boyscout skill
  - `card-simulator-claude-plugin` → groups CLAUDE.md, scripts, zshrc for the Card Simulator plugin
  - `card-simulator-docs` → groups tooling.md and other docs in all-the-things
- When in doubt, file-level granularity (`CLAUDE.md`) is acceptable — a PR touching one file is still a valid grouping
- Use the same target key for findings across multiple sessions that belong to the same logical fix

**Deep-mode target namespaces:** Findings produced by `/boyscout deep` use a distinct set of
namespaces that target the agent's configuration rather than the codebase. They live in the
same `~/.boyscout/backlog.md` and follow the same lifecycle. Use one of:

- `claude-skills / <plugin>/<skill>` — when the action updates a skill (e.g. `claude-skills / card-engineer/pr-review`).
- `claude-config / CLAUDE.md` — when the action updates a CLAUDE.md (clarify which one in `location`).
- `claude-memory / <memory-slug>` — when the action updates / promotes a memory entry.
- `claude-scripts / <script-name>` — when the action creates / updates a skill's script (script path goes in `location`).

**Extra fields by deep-mode type.** The three deep-mode types each carry additional fields beyond
the standard schema. See the detection reference files for full specifications:

| Type | Extra fields | Reference |
|---|---|---|
| `repeated-instruction` | `instruction_intent`, `occurrences`, `existing_memory` | `detection-repeated-instruction.common.md` |
| `automation-opportunity` | `pattern_summary`, `target_skill`, `proposed_script_name` | `detection-automation-opportunity.common.md` |
| `promotable-flow` | `flow_summary`, `proposed_skill_name`, `genericity_evidence` | `detection-promotable-flow.common.md` |

Extra fields are persisted alongside the standard fields in the backlog (as additional `- key: value`
lines under the H3 block) and surfaced in the fzf preview.

Cap at **10 new findings per run**. Pending findings from the backlog are added on top (no separate cap).
If more than 10 new findings exist, prioritize by estimated impact and note that others were omitted.
In `/boyscout deep` mode the cap is **shared across the three subagents** — not 10 per type. Each
subagent also independently caps at 10 (declared in its `detection-*.common.md` "Output cap" section),
so the worst-case fan-in to the parent is 3 × 10 = 30; the parent then applies the final joint
cap of 10 after the fan-out returns.

## List-valued extra fields — serialization

Some deep-mode extra fields are lists (notably `occurrences` for `repeated-instruction`). The
backlog uses flat `- key: value` lines, not nested YAML, so list values are serialised on a
single line with **semicolon-separated entries**, each entry collapsed to its most informative
form:

```
- occurrences: 2026-05-18 (PROJ-298); 2026-05-19 (PROJ-300)
```

This keeps the H3 block grep-friendly and consistent with the existing flat format. The nested
YAML form that appears in the `detection-*.common.md` examples is the in-memory representation of the
finding object; the **backlog form is always flat**. The same rule applies to any future
list-valued extra field.
