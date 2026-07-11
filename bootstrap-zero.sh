#!/usr/bin/env bash
#
# bootstrap-zero.sh (root entry point)
#
# curl -fsSL https://raw.githubusercontent.com/juanyque/agent-brain/main/bootstrap-zero.sh | bash
#
# Ensures the agent-brain repo is cloned to a canonical location, then dispatches to the
# real orchestrator at model/SCRIPTS/bootstrap-zero.sh. All flags after '--' (or any flags)
# are forwarded to the orchestrator.

set -euo pipefail

CANONICAL="${AGENT_BRAIN_HOME:-$HOME/.local/share/agent-brain}"
REPO_URL="https://github.com/juanyque/agent-brain.git"

if [[ ! -d "$CANONICAL/.git" ]]; then
  echo "Cloning agent-brain into $CANONICAL ..."
  mkdir -p "$CANONICAL"
  git clone --depth 1 "$REPO_URL" "$CANONICAL"
else
  echo "agent-brain already present at $CANONICAL — updating (git pull --ff-only)..."
  git -C "$CANONICAL" pull --ff-only || echo "  (pull failed — continuing with local copy)"
fi

exec bash "$CANONICAL/model/SCRIPTS/bootstrap-zero.sh" "$@"
