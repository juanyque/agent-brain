// agent-brain · brain-session-env
//
// Exposes the running session's id to every shell execution through the
// documented `shell.env` plugin hook (https://opencode.ai/docs/plugins).
// The hook input carries { cwd, sessionID?, callID? } and its output.env is
// injected into each shell command run by the agent and by user terminals.
//
// Install:  python3 ~/.agents/skills/brain/scripts/resolve_session_id.py \
//               --install-plugin
// Consumed by: RULES-SESSION-LIFECYCLE.common.md ("Identify the current
// session id") — read $OPENCODE_SESSION_ID as the authoritative id.
//
// `sessionID` is optional by API contract: a user terminal without session
// context does not carry one. Only inject when present so the variable never
// carries a stale or foreign value.

export const BrainSessionEnvPlugin = async () => ({
  "shell.env": async (input, output) => {
    if (input && typeof input.sessionID === "string" && input.sessionID) {
      output.env.OPENCODE_SESSION_ID = input.sessionID
    }
  },
})
