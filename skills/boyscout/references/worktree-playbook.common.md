# Worktree playbook (Step 4A)

Never touch the current working tree. All fixes happen in a separate worktree on
a fresh branch from the up-to-date base branch.

## Standard finding (same repo as primary task)

Spawn a subagent with `isolation: "worktree"` — this creates an isolated copy at
the current HEAD. The subagent must then:

1. Identify the base branch (local, no network needed):
   ```bash
   git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's@^refs/remotes/origin/@@'
   # if empty, try: git branch -r | grep -E 'origin/(main|master)$' | head -1 | sed 's@.*origin/@@'
   ```
2. Fetch latest: `git fetch origin`
3. Create a new branch from the base:
   `git checkout -b boyscout/fix/<slug> origin/<base-branch>`.
   **Verify with `git branch --show-current` — if the branch name is not
   `boyscout/fix/<slug>`, delete the wrongly-created branch
   (`git branch -D <actual-name>`), abort, and report the error to the user.**
4. Apply the fix
5. Commit with a descriptive message
6. Push: `git push origin boyscout/fix/<slug>`
7. Create a PR:
   ```bash
   gh pr create \
     --title "<commit message one-liner>" \
     --body "$(cat <<'EOF'
   Boyscout fix: <one-line summary>

   Found while: <ticket code or brief description — no raw error output, code snippets, or stack traces>

   🤖 Generated with [Claude Code](https://claude.com/claude-code)
   EOF
   )"
   ```

**On failure:** If `git push` or `gh pr create` fails, report the error to the
user with the branch name left behind (`boyscout/fix/<slug>`). Ask whether to
retry or skip. Do not delete the branch automatically — commits are intact.

## `skill-gap` finding (different repo)

Do NOT use `isolation: "worktree"` — it would create a worktree of the wrong
repo. Instead, brief a regular subagent to operate directly in the skill's repo:

> **Important:** `git checkout -b boyscout/fix/<slug> origin/$BASE` always starts
> from the remote tip, so there is no stale-state risk when creating a new
> branch. If you ever work in an *existing* checked-out worktree instead (e.g.,
> a skill-gap branch already in progress), run
> `git fetch origin && git checkout origin/<branch> -- <files>` first to sync to
> the remote state before modifying.

```bash
cd ~/workspace/your-project   # adjust to your project path
git fetch origin
BASE=$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's@^refs/remotes/origin/@@')
[ -z "$BASE" ] && BASE=$(git branch -r | grep -E 'origin/(main|master)$' | head -1 | sed 's@.*origin/@@')
# Branch from the remote tip — always starts at the latest upstream state
git checkout -b boyscout/fix/<slug> origin/$BASE
# [apply the fix described in the subagent brief]
git commit -m "..."
git push origin boyscout/fix/<slug>
gh pr create \
  --title "<commit message one-liner>" \
  --body "$(cat <<'EOF'
Boyscout fix: <one-line summary>

Found while: <ticket code or brief description — no raw error output, code snippets, or stack traces>

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

## Subagent brief (every variant)

Brief the subagent with:
- Self-contained description of the fix
- Exact file paths, line numbers, and what to change
- Success criterion (what done looks like)
- List of files touched by the primary task — do not modify any of them
- For `skill-gap`: the target skill's repo path and SKILL.md location

Report when done:
> "Fixed [summary] — PR: \<URL\>"

If the sub-agent reports it lacks Bash/Read/Glob permissions, handle the fix
directly in the parent session using the same git workflow described in the
sections above.

## Fixing into the PR currently under review

When the finding targets a file in the PR just reviewed and the user wants the
fix applied directly to that PR (not a new branch):

1. Get the PR branch and state:
   ```bash
   gh pr view <PR_NUMBER> --json headRefName,state --jq '{branch: .headRefName, state: .state}'
   ```
2. **Guard:** if `state` is not `OPEN` (it is `MERGED` or `CLOSED`), stop immediately and tell the user:
   > "PR #N is <STATE> — cannot push to a merged/closed branch. Create a new branch from the base branch instead (standard worktree path above)."
   Do NOT proceed with steps 3–6 if the PR is not open.
3. Brief a regular subagent (no `isolation: "worktree"`) to work in the repo:
   ```bash
   cd <repo>
   git fetch origin
   git switch --detach origin/<pr-branch>   # HEAD now at the remote tip of the PR branch
   ```
4. Apply the fix
5. Commit and push: `git push origin HEAD:<pr-branch>`
6. Report: `"Fixed [summary] in existing PR branch <pr-branch>"`
