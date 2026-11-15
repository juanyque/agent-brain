#!/usr/bin/env bash
# Resolve the comparison base (MODEL_BASE) for the CI committed-range gates.
#
# Inputs (environment variables; the git repository is the current directory):
#   EVENT_NAME        GitHub event name (github.event_name): pull_request or push.
#   PR_BASE_SHA       github.event.pull_request.base.sha (pull_request only).
#   PUSH_BEFORE_SHA   github.event.before (push only); 40 zeros when the push
#                     creates a ref (a branch or a tag).
#   DEFAULT_BRANCH    github.event.repository.default_branch (e.g. main); used
#                     only when a push creates a branch.
#
# Contract:
#   pull_request              base = PR_BASE_SHA
#   push, existing branch     base = PUSH_BEFORE_SHA
#   push, new branch or tag   base = merge-base of origin/$DEFAULT_BRANCH and HEAD
#   anything else             fail ("unsupported event; provide an explicit base")
# A SHA base must be a commit object (one `git fetch --no-tags origin <sha>` is
# attempted when missing) that shares history with HEAD (`git merge-base`).
# There is deliberately NO fallback to HEAD, HEAD~1 or the root commit: when the
# base cannot be determined the script fails.
#
# Output: the base SHA alone on stdout, exit 0. Diagnostics go to stderr; any
# failure exits non-zero with a message on stderr.
#
# Note: consumers diff with `base...HEAD`, which audits from the merge-base of
# base and HEAD up to HEAD.

set -euo pipefail

fail() {
  printf 'resolve_model_base: %s\n' "$*" >&2
  exit 1
}

# verify_commit LABEL SHA: prove SHA is a commit related to HEAD, print it.
verify_commit() {
  local label="$1" sha="$2" resolved
  [ -n "$sha" ] || fail "$label is empty; provide an explicit base"
  if ! git cat-file -e "${sha}^{commit}" 2>/dev/null; then
    printf 'resolve_model_base: %s %s not present locally; fetching once\n' "$label" "$sha" >&2
    git fetch --no-tags origin "$sha" >&2 2>&1 || true
    git cat-file -e "${sha}^{commit}" 2>/dev/null \
      || fail "$label $sha is not a commit in this checkout and could not be fetched; provide an explicit base"
  fi
  git merge-base "$sha" HEAD >/dev/null 2>&1 \
    || fail "$label $sha shares no history with HEAD (no merge-base); provide an explicit base"
  resolved="$(git rev-parse "${sha}^{commit}")"
  printf '%s\n' "$resolved"
}

event="${EVENT_NAME:-}"

case "$event" in
  pull_request)
    verify_commit "PR base" "${PR_BASE_SHA:-}"
    ;;
  push)
    before="${PUSH_BEFORE_SHA:-}"
    [ -n "$before" ] || fail "push event without PUSH_BEFORE_SHA; provide an explicit base"
    case "$before" in
      *[!0]*)
        verify_commit "push before" "$before"
        ;;
      *)
        branch="${DEFAULT_BRANCH:-}"
        [ -n "$branch" ] || fail "new-branch push without DEFAULT_BRANCH; provide an explicit base"
        ref="refs/remotes/origin/$branch"
        git rev-parse --verify --quiet "${ref}^{commit}" >/dev/null \
          || fail "new-branch push: $ref is not available; provide an explicit base"
        base="$(git merge-base "$ref" HEAD 2>/dev/null)" \
          || fail "new-branch push: no merge-base between $ref and HEAD; provide an explicit base"
        [ -n "$base" ] || fail "new-branch push: empty merge-base; provide an explicit base"
        printf '%s\n' "$base"
        ;;
    esac
    ;;
  *)
    fail "unsupported event; provide an explicit base (EVENT_NAME='${event}')"
    ;;
esac
