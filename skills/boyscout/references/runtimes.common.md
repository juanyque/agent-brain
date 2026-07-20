# Runtime-aware paths

Deep mode reads transcripts, memories, and config files from agent runtime directories. The paths differ by runtime:

## Transcript paths

| Runtime | Path | Format |
|---|---|---|
| Claude Code | `transcript files (see runtimes.common.md for paths)*/*.jsonl` | JSONL session transcripts |
| OpenCode | `~/.local/share/opencode/sessions/` | Session data (check runtime docs) |
| Codex | TBD | TBD |

## Memory paths

| Runtime | Path |
|---|---|
| Claude Code | `~/.claude/memory/` |
| OpenCode | `~/.config/opencode/` (runtime-specific) |
| Codex | TBD |

## Config paths

| Runtime | Config file |
|---|---|
| Claude Code | `CLAUDE.md` (project-level), `~/.claude/CLAUDE.md` (global) |
| OpenCode | `AGENTS.md` (project-level), `~/.config/opencode/AGENTS.md` (global) |
| Codex | `AGENTS.md` or equivalent |

## Detection

At runtime, detect which agent runtimes are present by checking for the directories above. Deep mode scans all detected runtimes, not just the current one — findings may reference context from sessions held in other runtimes or repos.

## Scope note

Transcripts include sessions from every project on the machine, filtered by `mtime`. Combined with the PII guardrail (see detection references), all cross-repo context is redacted to patterns; no verbatim content from another project's transcripts reaches the backlog or a ticket.
