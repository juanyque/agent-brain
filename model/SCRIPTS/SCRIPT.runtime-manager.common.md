# runtime_manager.py

## Purpose

All runtime wiring for a brain (D21/D26). Replaces the runtime logic previously in `home_setup.py` (removed in A.2).

## What it does

1. **Discovery** — detects local runtimes (`~/.claude/`, `~/.config/opencode/`, `~/.codex/`) and brain-side config (`_AGENTS/<RT>/`).
2. **Decision matrix** per mapped file or directory:

   | Brain `_AGENTS/<RT>/` | Local `~/.<RT>/` | Action |
   |---|---|---|
   | yes | no | **Direction B** — implant via `runtime_install.sh` |
   | no | yes | **Direction A** — ingest local → brain, then implant |
   | yes | yes (unmanaged) | **Conflict** — quarantine local → `INBOX/_RUNTIME/<RT>/`, implant brain |
   | yes | yes (symlinked) | **OK** — already wired |
   | no | no | Skip |

3. **Old-layout migration** — detects external symlinks pointing into the brain, moves targets to `_AGENTS/`, rewrites symlinks.
4. **Skill link** — symlinks each runtime's user skill location to `agent-brain/skills/brain`. Codex uses the official user location `~/.agents/skills/brain`.

## Usage

```bash
python3 runtime_manager.py --brain <path> [--common <model_path>] [--apply] [--runtime claude] [--runtime-home ~/.foo]
```

## Direction A (ingest)

When the local runtime has config but the brain doesn't:
1. Copy local config files → `_AGENTS/<RT>/` (using the mapping table).
2. `git add` the new files in the brain.
3. Remove local originals.
4. Create symlinks local → brain (Direction B).

## Conflict handling

When both sides have unmanaged config:
1. Copy local config → `INBOX/_RUNTIME/<RT>/` (quarantine).
2. Stage the quarantine as part of the deterministic safety snapshot workflow.
3. Implant brain version (Direction B).
4. Post-process: agent offers an interactive merge per the brain skill's runtime-merge reference.

## Runtime configs

| Runtime | Local dir | `_AGENTS/` subdir | Mappings |
|---|---|---|---|
| claude | `~/.claude/` | `CLAUDE/` | `CLAUDE.runtime.claude.md→CLAUDE.md`, `settings.json`, `memory` |
| opencode | `~/.config/opencode/` | `OPENCODE/` | `AGENTS.runtime.opencode.md→AGENTS.md`, `opencode.json`, `oh-my-openagent.json` |
| codex | `~/.codex/` | `CODEX/` | `AGENTS.runtime.codex.md→AGENTS.md`, `config.toml`; skill at `~/.agents/skills/brain` |

If `_AGENTS/SHARED/memory/` exists, Codex also receives a read-only discovery link at
`~/.agents/brain-memory`. The installer does not replace or relocate Codex's native,
generated `~/.codex/memories/` state.
