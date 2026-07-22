# Deep mode sources

Closed list of sources the `/boyscout deep` mode reads. **Any source outside this list is not read** —
the closed-list rule keeps the scan bounded, deterministic, and cheap. Runtime-specific paths and
selection rules come from [runtimes.md](runtimes.md).

## Window

Default window: **2 days** (covers a small set of recent working sessions).

Override via second positional arg: `/boyscout deep 7` widens to 7 days. The override is supported
but not promoted as the recommended flow — wider windows multiply token cost without proportionally
improving finding quality.

`N` below refers to the window value in days (default 2).

## Sources (in order)

### 1. Supported runtime transcripts

- **Paths:** only transcript patterns for detected adapters in [runtimes.md](runtimes.md).
- **Filter:** modification time within the last `N` days; resolve and reject path escapes before
  reading.
- **Selection:** combine all detected runtimes, sort newest first, and cap at 10 transcripts total.
- **What to extract:** user messages (for `repeated-instruction`), tool-use sequences (for
  `automation-opportunity`), and conversation arcs (for `promotable-flow`).
- **Never extract:** raw command output, secrets, tokens, or full file contents pasted into a chat.

### 2. Indexed durable memory

- **Indexes:** only the runtime and shared-memory indexes listed in [runtimes.md](runtimes.md).
- **Selection rule:** query index metadata first, then open only entries that materially match the
  candidate finding. Orphan files and recursive directory scans are out of scope.
- **Why this matters:** a matching durable feedback rule is the deduplication and escalation signal
  for `repeated-instruction` findings. A correction that persists after a matching rule exists is
  evidence that memory alone is insufficient.

### 3. Agent instruction files

- **Paths:** only the project, global, and plugin instruction paths listed for detected adapters in
  [runtimes.md](runtimes.md).
- **Purpose:** establish which rules and skills are already documented. This distinguishes "the rule
  exists but was not followed" from "the rule is not documented" without searching arbitrary files.

### 4. Recent git activity

- **Commands:** `git reflog --since=N.days` and `git log --since=N.days --all --oneline` from the
  current repository.
- **Purpose:** correlate findings with actual commits when commit metadata is useful evidence.
- **Never include:** commit content, diffs, or code in the finding. Only commit hashes and sanitized
  subject summaries may be used.

## Discovery commands (reference)

The following commands enumerate adapter inputs. They do not decide which note bodies to open and
must not be widened to scan the home directory.

```bash
# Window in days (default 2)
N=${1:-2}
if ! [[ "$N" =~ ^[1-9][0-9]*$ ]] || (( N > 30 )); then
  echo "days must be an integer from 1 to 30" >&2
  exit 2
fi

# Supported transcript adapters; merge, sort by mtime, and cap at 10 after enumeration.
find ~/.claude/projects -type f -name "*.jsonl" -mtime "-${N}" 2>/dev/null
find ~/.codex/sessions -type f -name "rollout-*.jsonl" -mtime "-${N}" 2>/dev/null

# Exact memory indexes. Read matched entries only after querying an index.
[ -f ~/.agents/brain-memory/MEMORY.md ] && echo ~/.agents/brain-memory/MEMORY.md
[ -f ~/.claude/memory/MEMORY.md ] && echo ~/.claude/memory/MEMORY.md
find ~/.claude/memory/projects -type f -name "MEMORY.md" 2>/dev/null
[ -f ~/.codex/memories/MEMORY.md ] && echo ~/.codex/memories/MEMORY.md

# Exact project and global instruction files.
[ -f AGENTS.md ] && echo "$(pwd)/AGENTS.md"
[ -f CLAUDE.md ] && echo "$(pwd)/CLAUDE.md"
[ -f ~/.codex/AGENTS.md ] && echo ~/.codex/AGENTS.md
[ -f ~/.claude/CLAUDE.md ] && echo ~/.claude/CLAUDE.md
find ~/.claude/plugins -mindepth 2 -maxdepth 2 -type f -name "CLAUDE.md" 2>/dev/null

# Recent git metadata from the current repository.
git reflog --since="${N}.days" 2>/dev/null
git log --since="${N}.days" --all --oneline 2>/dev/null
```

These commands are reference only. Before reading a transcript, apply the root-containment and
global-cap rules in [runtimes.md](runtimes.md).

## What this list does NOT include

The following are intentionally excluded and must not be added without revising this file:

- Shell command history — too noisy and likely to contain secrets.
- External chat, document, or issue-tracker content beyond links already present in the current
  session.
- Arbitrary file contents outside the current repository.
- Browser history, screenshots, or any non-textual context.
- Temporary directories.

If a future enhancement needs a new source, update this closed list and the runtime adapter contract
first, then update the relevant `detection-*.md` consumer.
