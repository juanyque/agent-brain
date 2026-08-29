# Setup and attachment workflows

Operations for locating the agent-brain checkout, attaching a brain to it, and installing or repairing the runtime skill. Use these when working with the model for the first time or repairing an existing setup.

## Locate the model checkout

If connected to a brain that already has `_COMMON`, resolve it from the brain root:

```bash
python3 - <<'PY'
from pathlib import Path
print((Path('<brain_path>') / '_COMMON').resolve())
PY
```

If `_COMMON` does not exist, use the canonical agent-brain checkout at `${AGENT_BRAIN_HOME:-$HOME/.local/share/agent-brain}` or ask for its path before applying changes.

## Attach or check a brain

Use the bootstrap in dry-run mode first:

```bash
bash <agent-brain>/model/SCRIPTS/bootstrap-zero.sh --brain <brain_path>
```

The bootstrap installs the skill for detected runtimes. Codex is detected through `~/.codex`, persists its user instructions and configuration at `_AGENTS/CODEX/AGENTS.runtime.codex.md`, `_AGENTS/CODEX/config.toml`, and `_AGENTS/CODEX/hooks.json`, links them back to `~/.codex/AGENTS.md`, `~/.codex/config.toml`, and `~/.codex/hooks.json`, and shares the user skill at `~/.agents/skills/brain` with OpenCode. Claude uses `~/.claude/skills/brain`. Antigravity CLI is skill-only and uses `~/.gemini/antigravity-cli/skills/brain`. If the private brain provides `_AGENTS/SHARED/memory/`, it is linked at `~/.agents/brain-memory` for lazy, indexed lookup. Codex's native `~/.codex/memories/` state is left untouched.

### Offer the SessionStart brain-connect hook

Ask the user explicitly, per detected runtime, whether they want the brain to connect automatically when a session starts inside it. This is a real behavior change (something executes on every session start), not a passive config link like the mappings above, so it is opt-in, never assumed -- a "no" for one runtime, or for all of them, is a legitimate answer.

If they say yes, wire `model/SCRIPTS/session_start_hook.py` -- portable, discovers the active brain from the hook's own `cwd` via `find_home.py`; no per-installation customization needed, and it fails safe (prints `{}`) for any cwd outside a brain:

- **Claude Code**: add an entry to the `SessionStart` array already inside the brain-managed `settings.json` (`_AGENTS/CLAUDE/settings.json`, symlinked to `~/.claude/settings.json` per the mapping above): `{"hooks": [{"type": "command", "command": "python3 <agent-brain>/model/SCRIPTS/session_start_hook.py --runtime claude", "timeout": 5}]}`. No separate trust step exists for Claude Code hooks.
- **Codex**: add the equivalent entry to `_AGENTS/CODEX/hooks.json`'s `SessionStart` array (symlinked to `~/.codex/hooks.json` via `runtime_install.sh codex --brain <brain_path> --apply`, now that `hooks.json` is a managed mapping): `{"hooks": [{"type": "command", "command": "/usr/bin/env python3 <agent-brain>/model/SCRIPTS/session_start_hook.py --runtime codex", "timeout": 10}]}`. Codex requires each hook to be explicitly trusted (a SHA-256 pinned per event+index in `config.toml`'s `[hooks.state]`) before it actually fires -- tell the user their next real interactive Codex session inside the vault will prompt for this. `--dangerously-bypass-hook-trust` exists for one-off testing only, never as a standing substitute for the user's own approval.

Both runtimes share the same `hookSpecificOutput.additionalContext` response contract (verified empirically against Codex CLI 0.150.1, 2026-08-29) -- do not assume this holds for a future runtime without checking its own hook documentation first.

Only apply after the dry-run is safe:

```bash
bash <agent-brain>/model/SCRIPTS/bootstrap-zero.sh --brain <brain_path> --apply
```

When setup is entered through the public `curl | bash` command, use the exact
public apply command printed at the end of the dry-run. It includes the resolved
brain path and any selected runtime filter or symlink policy.

This script creates `_COMMON` when missing and creates only missing local wrapper files. It must not overwrite existing brain-local files.

When `--skip-full-reorder` is not passed, the script also:

- Sweeps recursively-empty visible directories from the brain root before reading state. Useful after `git reset --hard` of a prior migration: git leaves empty dir shells that confuse subsequent state checks. Top-level dotfile dirs (`.git/`, `.obsidian/`, etc.) and symlinks are never touched.
- When `_COMMON` does not exist: scans the canonical external agent runtime homes (`~/.agents`, `~/.claude`, `~/.codex`, plus any `--runtime-home` path) for symlinks pointing into the brain. After the required setup decision, each top-level brain directory referenced by such a symlink is moved into `_AGENTS/<name>/` with `git mv` under the bounded standing authorization in `_COMMON/AGENTS.common.md`, the external symlinks are re-pointed to the new location, and the originals are preserved as `.bak.<timestamp>` siblings. A per-migration WIP doc is written at `WIP/AGENTS_MIGRATION.<date>.md` describing every rewrite and the exact cleanup commands.
- When `_COMMON` does not exist: after the required full-reorder decision, creates `_STAGING/` and moves all remaining non-hidden brain content into it using `git mv` under the same bounded standing authorization. This signals initial reorganization mode.

If the dry-run reports `symlink_policy: required`, show the listed top-level
links and their resolved targets to the user before apply:

- Recommend `--symlink-policy copy`, which ingests each valid target as regular
  content in `_STAGING/` and preserves the external source.
- Offer `--symlink-policy keep` only for links that do not occupy a canonical
  scaffold directory. Kept links remain at the brain root and are outside the
  model's staging and drain workflow.
- A link named `INBOX`, `WIP`, `JOURNAL`, `MEMORY`, `BACKLOG`, `ARCHIVED`,
  `REPORTS`, `OUTBOX`, `QUARANTINE`, `TEMPLATES`, or `TASK_TYPES` cannot be kept
  because the model needs that path. The user must choose `copy` or stop setup.

Pass the selected policy through `bootstrap-zero.sh` or directly to
`home_setup.py`. Never infer `keep` from the link target.

For direct low-level repair, `home_setup.py` supports `--skip-full-reorder`; never choose it autonomously.

If the dry-run reports rewritten symlinks, surface the `WIP/AGENTS_MIGRATION.<date>.md` path to the user after apply so they can verify the new links resolve before deleting the `.bak` backups themselves.

## Install or repair the runtime skill

Use `skill_link.sh` in dry-run mode first. For Codex or OpenCode, use the shared user-skill parent `~/.agents`:

```bash
bash <agent-brain>/model/SCRIPTS/skill_link.sh brain ~/.agents
```

Only apply after the dry-run is safe:

```bash
bash <agent-brain>/model/SCRIPTS/skill_link.sh brain ~/.agents --apply
```

The selected store should contain its `skills/brain` entry as a symlink to `<agent-brain>/skills/brain`. Automatic detection targets the shared `~/.agents` store once, plus Claude and Antigravity CLI when present. It does not install into legacy Gemini CLI paths. Do not copy skill files when a symlink can be used.

For a skill owned by another repository, pass its source directory instead of an agent-brain skill
name. The same dry-run-first rule applies, and omitting `runtime_home` targets every detected runtime:

```bash
bash <agent-brain>/model/SCRIPTS/skill_link.sh /path/to/project/skills/confold
bash <agent-brain>/model/SCRIPTS/skill_link.sh /path/to/project/skills/confold --apply
```

The source directory must contain `SKILL.md`; its basename becomes the installed skill name. Runtime
homes receive symlinks, so updates remain owned and versioned by the source project.
