# Session id resolver

`resolve_session_id.py` resolves the current OpenCode, Codex, or Claude Code session id
through runtime-specific deterministic signals, never by history list order.
It is the executable form of the "Identify the current session id" rule in
`RULES-SESSION-LIFECYCLE.common.md`.

```bash
python3 ~/.agents/skills/brain/scripts/resolve_session_id.py \
  --runtime opencode \
  --cwd "$(pwd)"
```

For Codex, prefer the runtime-provided `$CODEX_SESSION_ID`, the session-tree
id used by `codex resume`. Do not substitute `$CODEX_THREAD_ID`: a forked
thread's id may differ from its session-tree id. If the session environment
variable is unavailable, query the local App Server and require one loaded
thread in the current directory; the resolver reads that thread's
authoritative `thread.sessionId` field:

```bash
python3 ~/.agents/skills/brain/scripts/resolve_session_id.py \
  --runtime codex \
  --cwd "$(pwd)"
```

For Claude Code, read `$CLAUDE_CODE_SESSION_ID` on every call: the id can rotate
mid-conversation, so re-resolve instead of caching it. The resolver never guesses
from the newest transcript file:

```bash
python3 ~/.claude/skills/brain/scripts/resolve_session_id.py \
  --runtime claude \
  --cwd "$(pwd)"
```

Resolution chain (first hit wins):

Claude Code:

1. `claude_session_id_env` — `$CLAUDE_CODE_SESSION_ID`, injected by Claude Code.
2. unresolved — exit 3 with `ask_user` true when the variable is unset.

Codex:

1. `codex_session_id_env` — `$CODEX_SESSION_ID`, injected by the Codex runtime.
2. `app_server_loaded_thread` — query loaded threads and return
   `thread.sessionId` only when exactly one thread matches `--cwd`.

OpenCode:
1. `plugin_env` — `$OPENCODE_SESSION_ID`, injected into every shell execution
   by the `brain-session-env` plugin (opencode `shell.env` hook). Authoritative.
2. `launch_flag` — the `-s`/`--session` value in `ps -p $OPENCODE_PID -o command=`.
3. `liveness_probe` — the session owning the newest `part` write in the
   OpenCode SQLite DB (discovered via `opencode db path`), restricted to
   `--cwd`, requiring recency (`--max-age-seconds`, default 900) and a lead
   over the same-directory runner-up (`--margin-seconds`, default 5). This
   distinguishes the live session from recently-finished peers and subagents.
4. unresolved — exit 3; stdout carries `candidates` (id, title, updated,
   directory) for the ask-the-user fallback.

Exit codes: `0` resolved · `3` unresolved (candidates emitted, `ask_user`
true) · `2` error · `4` unsupported runtime. Stdout is always one JSON object
with `session_id`, `resolution`, `chain`, and `evidence`.

Plugin install (enables signal 1 globally):

```bash
python3 ~/.agents/skills/brain/scripts/resolve_session_id.py --install-plugin
```

Copies `plugins/brain-session-env.js` from the skill tree into
`$OPENCODE_CONFIG_DIR/plugins/` (default `~/.config/opencode/plugins/`).
Refuses to overwrite an existing copy unless `--force` is passed. OpenCode
loads the plugin on next start; `--pure` sessions skip it (signals 2–4 still
apply). The tool is read-only apart from `--install-plugin` and uses only
Python's standard library.

Codex first reads `CODEX_SESSION_ID`. If it is unavailable, the resolver
queries the daemon socket reported by `codex app-server daemon version`. If
that socket is unavailable, or zero/multiple loaded threads match the cwd, the
tool exits 3 with evidence. It never guesses by most-recent history entry.
`--socket-path` is available for diagnostics and tests; `--install-plugin` is
OpenCode-only.
