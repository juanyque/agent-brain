# Session id resolver

`resolve_session_id.py` resolves the current OpenCode session id through a
deterministic signal chain — never by list order. It is the executable form of
the "Identify the current session id" rule in `RULES-SESSION-LIFECYCLE.common.md`.

```bash
python3 ~/.agents/skills/brain/scripts/resolve_session_id.py \
  --runtime opencode \
  --cwd "$(pwd)"
```

Resolution chain (first hit wins):

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
