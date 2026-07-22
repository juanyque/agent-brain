# Finding schema

Each boyscout finding captures the following fields. Collect them during Step 1
(identify) and render them during Step 2 (selection form).

| Field | Purpose | Allowed values / notes |
|---|---|---|
| One-line summary | Shown in the fzf list and numbered fallback | ≤ 80 chars |
| Target | Logical grouping key — determines which findings share a PR | `<repo> / <component>` — see convention below |
| Location | File(s), line(s), function/test name | `path/to/file.py:42` or `module.function` (for `skill-gap`: see convention below) |
| Type | Tagged bucket for filtering and ticket labeling | `flaky-test` \| `test-isolation` \| `broken-script` \| `refactor` \| `missing-test` \| `dead-code` \| `docs-gap` \| `skill-gap` \| `tech-debt` \| `side-task` \| `repeated-instruction` \| `automation-opportunity` \| `promotable-flow` \| `other` |
| How found | Provenance — error message, observation, test failure, code review | Free text; persisted to backlog |
| Context | The main task or investigation that surfaced this finding | Free text, e.g. `"reviewing PR #38"`, `"implementing PROJ-258"`; persisted to backlog |
| Estimated effort | Feeds the Step 3 decision table | `XS` (<15 min) \| `S` (<1h) \| `M` (<1 day) \| `L` (>1 day) |
| Risk | Chance of regression or needing domain knowledge | `low` \| `medium` \| `high` |
| Impact | Value if fixed — orthogonal to effort/risk | `low` (cosmetic; marginal DX) \| `medium` (real friction scoped to one task type) \| `high` (recurrent cross-session pain; blocks work; or the agent makes important mistakes in its absence). Required for `repeated-instruction` and `automation-opportunity`; recommended for all findings. Enables value-based filtering (`grep "impact: high"`). |
| Confidence | Sureness that the proposed action is actually an improvement | `low` (pattern may be noise; OR action is speculative; OR could plausibly make things worse — discuss diagnosis before acting, never auto-fix) \| `medium` (pattern is clear; action requires judgement — A vs B vs C, or scope to be decided with the user) \| `high` (pattern is clear; evidence exists — cite a commit / a memory / a working analogous example; proposed action is mechanical). Required for `repeated-instruction`, `automation-opportunity`, and `promotable-flow`; recommended for all findings. `confidence: low` blocks auto-fix at Step 3. |
| Suggested action | What fixing it would look like | File edits, test changes, refactor outline |
| Status | Origin of this finding | `new` (found in this session) \| `pending` (loaded from backlog) |
| Detected | First detection date + session context | ISO date string, e.g. `2026-04-23 · session PROJ-255` — see **session label format** below |
| Last seen | Most recent session that independently detected this finding | ISO date string + session context; updated on dedup match |
| Times seen | Count of independent re-detections across sessions | Integer ≥ 1 |
| Source | Which scan mode produced this finding | `codebase` (default — `/boyscout` normal scan; omit field when this is the value) \| `deep-scan` (produced by `/boyscout deep` — interaction-context analysis of transcripts/memories/CLAUDE.md). Useful for triage filtering (`grep "source: deep-scan"`) and to distinguish escalation patterns: deep findings often match an existing memory (`existing_memory` field), which is the signal that the memory did not fire as intended. |

**Session label format:** `YYYY-MM-DD · session <ticket-or-tool-label>` where `<ticket-or-tool-label>` is one of:

- A ticket code when the scan happened during ticket work: `session PROJ-255`
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

- Use the repo short name (e.g. `your-project`, `demo-app`)
- Use a logical component name that maps to "what PR would fix all of these":
  - `boyscout-skill` → groups SKILL.md + references/*.md for the boyscout skill
  - `demo-app-agent-config` → groups AGENTS.md, scripts, and shell configuration for the Demo App
  - `demo-app-docs` → groups tooling.md and other docs in the example organization repository
- When in doubt, file-level granularity (`CLAUDE.md`) is acceptable — a PR touching one file is still a valid grouping
- Use the same target key for findings across multiple sessions that belong to the same logical fix

**Deep-mode target namespaces:** Findings produced by `/boyscout deep` use a distinct set of
namespaces that target the agent's configuration rather than the codebase. They live in the
same `~/.boyscout/backlog.md` and follow the same lifecycle. Use one of:

- `agent-skills / <plugin>/<skill>` — when the action updates a skill (e.g. `agent-skills / card-engineer/pr-review`).
- `agent-config / CLAUDE.md` — when the action updates a CLAUDE.md (clarify which one in `location`).
- `agent-memory / <memory-slug>` — when the action updates / promotes a memory entry.
- `agent-scripts / <script-name>` — when the action creates / updates a skill's script (script path goes in `location`).

**Extra fields by deep-mode type.** The three deep-mode types each carry additional fields beyond
the standard schema. See the detection reference files for full specifications:

| Type | Extra fields | Reference |
|---|---|---|
| `repeated-instruction` | `instruction_intent`, `occurrences`, `existing_memory` | `detection-repeated-instruction.md` |
| `automation-opportunity` | `pattern_summary`, `target_skill`, `proposed_script_name` | `detection-automation-opportunity.md` |
| `promotable-flow` | `flow_summary`, `proposed_skill_name`, `genericity_evidence` | `detection-promotable-flow.md` |

Extra fields are persisted alongside the standard fields in the backlog (as additional `- key: value`
lines under the H3 block) and surfaced in the fzf preview.

Cap at **10 new findings per run**. Pending findings from the backlog are added on top (no separate cap).
If more than 10 new findings exist, prioritize by estimated impact and note that others were omitted.
In `/boyscout deep` mode the cap is **shared across the three subagents** — not 10 per type. Each
subagent also independently caps at 10 (declared in its `detection-*.md` "Output cap" section),
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
YAML form that appears in the `detection-*.md` examples is the in-memory representation of the
finding object; the **backlog form is always flat**. The same rule applies to any future
list-valued extra field.

## Triage decision matrix (Step 3)

Suggested defaults when proposing attack-now vs ticket vs leave-in-backlog. The four dimensions
(`effort`, `risk`, `impact`, `confidence`) are defined in the field table above.

| Effort | Risk   | Impact | Confidence | Suggested action |
|--------|--------|--------|------------|------------------|
| XS / S | low    | high   | high       | **Attack now** (strong candidate; consume on success) |
| XS / S | low    | medium | high       | Backlog (or attack now if in-scope of active task) |
| XS / S | low    | low    | high       | Backlog (skip attack unless trivially in-scope) |
| XS / S | medium | high   | high       | Ask: attack now or ticket? |
| XS     | high   | any    | high       | Ask: attack now or ticket? |
| S      | medium | any    | high       | Ask: attack now or ticket? |
| S      | high   | any    | high       | Ticket (user can override) |
| M / L  | any    | any    | any        | Ticket |
| any    | any    | any    | **low**    | **Never auto-fix.** Discuss diagnosis with the user before any action. |

When ambiguous, ask explicitly, surfacing all four dimensions so the user chooses. Example:

> "Item 2: effort=S, risk=medium, impact=high, confidence=high. Fixable in ~30 min but touches
> shared auth code. Attack now in a worktree, or create a ticket?"
