# Deep mode sources

Closed list of sources the `/boyscout deep` mode reads. **Any source outside this list is not read** — the closed-list rule keeps the scan bounded, deterministic, and cheap.

## Window

Default window: **2 days** (covers ~3-5 sessions of a normal working day).

Override via second positional arg: `/boyscout deep 7` widens to 7 days. The override is supported but not promoted as recommended flow — wider windows multiply token cost without proportionally improving finding quality.

`N` below refers to the window value in days (default 2).

## Sources (in order)

### 1. Claude Code transcripts

- **Path glob:** `transcript files (see runtimes.md for paths)*/*.jsonl`
- **Filter:** `mtime` within the last `N` days.
- **Selection:** newest first; cap at ~10 transcripts to bound cost even if the user's window is wide.
- **What to extract:** user messages (for `repeated-instruction`), tool-use sequences (for `automation-opportunity`), conversation arcs / phases (for `promotable-flow`).
- **Never extract:** raw command output, secrets, tokens, full file contents pasted into the chat.

### 2. Active memories

- **Path:** `~/.claude/memory/`
- **Selection rule:** only files referenced from `~/.claude/memory/MEMORY.md` and any project-specific `~/.claude/memory/projects/<project>/MEMORY.md` indexes. Orphan files in the directory are **not read**.
- **Why this matters:** memories of `type: feedback` are the dedup + escalation key for `repeated-instruction` findings (see `detection-repeated-instruction.md`). A finding that matches an existing `feedback` memory is evidence the memory was not enough.

### 3. CLAUDE.md files

- **Current repo:** the `CLAUDE.md` at the root of the repo where `/boyscout deep` was invoked (if any).
- **Active plugins:** every `CLAUDE.md` discovered under `~/.claude/plugins/*/CLAUDE.md`.
- **Purpose:** baseline of rules already documented for the agent. Used to assess whether a `repeated-instruction` finding is "the rule exists but the agent isn't following it" vs "the rule isn't written anywhere".

### 4. Recent git activity

- **Commands:** `git reflog --since=N.days` and `git log --since=N.days --all --oneline` from the current repo.
- **Purpose:** correlate findings with actual commits — e.g. a `repeated-instruction` about "don't push directly to main" can cite the commits that triggered the rule.
- **Never include:** commit content (diffs, code) in the finding output. Only commit hashes + subject lines as evidence.

## Discovery commands (reference)

```bash
# Window in days (default 2)
N=${1:-2}

# 1. Transcripts modified within the window
find ~/.claude/projects -name "*.jsonl" -mtime -${N} 2>/dev/null | head -10

# 2. Indexed memories
cat ~/.claude/memory/MEMORY.md 2>/dev/null
find ~/.claude/memory/projects -name "MEMORY.md" 2>/dev/null

# 3. CLAUDE.md files
[ -f CLAUDE.md ] && echo "$(pwd)/CLAUDE.md"
ls ~/.claude/plugins/*/CLAUDE.md 2>/dev/null

# 4. Recent git activity
git reflog --since="${N}.days" 2>/dev/null
git log --since="${N}.days" --all --oneline 2>/dev/null
```

These commands are reference only — the deep-mode subagents invoke them as part of their scan.

## What this list does NOT include

The following are intentionally excluded and must not be added without revising this file:

- Bash command history (`~/.zsh_history`, `~/.bash_history`) — too noisy, often contains secrets.
- Slack / Notion / Jira content beyond what's already referenced from the current session.
- File contents outside the repo (other repos, vault, downloads).
- Browser history, screenshots, or any non-textual context.
- Anything in `/tmp`.

If a future enhancement needs new sources, update this file first (closed-list rule), then update the relevant `detection-*.md` to consume them.
