# Runtime merge — interactive conflict resolution

When `runtime_manager.py` detects **conflict** (both local `~/.<runtime>/` and brain `_AGENTS/<runtime>/` have config), it quarantines the local copy to `INBOX/_RUNTIME/<runtime>/` and implants the brain version. This reference describes the agent-driven merge procedure to reconcile the quarantined local config with the brain's canonical version.

## When to run this

After `runtime_manager.py` reports quarantined config at `INBOX/_RUNTIME/<RT>/`. The user should be offered this merge — it is never automatic.

## Scope

The merge covers three types of artifacts, each with its own strategy:

| Artifact | Strategy |
|---|---|
| `CLAUDE.md` / `AGENTS.md` (operational model) | Brain wins as canonical; personal overrides are slots. Diff section by section. |
| Memory (`.md` + frontmatter) | Per-file: present unique-from-local, let user select which to import. |
| Settings (`settings.json`, `opencode.json`, etc.) | Manual diff only. Never auto-merge structured JSON. |

## Procedure

### 1. Inventory both sides

Read the brain canonical config and the quarantined local config:

- Brain: `_AGENTS/<RT>/` (e.g. `CLAUDE.runtime.claude.md`, `settings.json`, `memory/`)
- Quarantined: `INBOX/_RUNTIME/<RT>/` (same filenames)

Present a summary table to the user showing what exists on each side.

### 2. CLAUDE.md / AGENTS.md merge

The brain version is the canonical operational model. The local version may contain personal overrides that should be preserved as slots.

1. Diff the two files section by section (split on `##` headings).
2. For each section that differs:
   - If the local has user-specific content not in the brain (e.g. project paths, personal preferences): propose extracting it as a slot.
   - If the brain has newer canonical content: the brain wins.
   - If both have changes: present both versions and ask the user which to keep.
3. Write the merged result to the brain canonical file.
4. Commit with message like `merge: ingest local <RT> config into brain`.

### 3. Memory merge

Memory files are standalone `.md` notes. The merge is per-file:

1. List all files in `INBOX/_RUNTIME/<RT>/memory/` that do NOT exist in `_AGENTS/<RT>/memory/`.
2. Present them to the user with a one-line preview (first content line).
3. For each file the user selects to import: `git mv` from quarantine to brain memory.
4. Files the user does not select remain in quarantine for later review or deletion.

### 4. Settings JSON merge

Never attempt automatic JSON deep-merge. Instead:

1. If the files are identical: nothing to do.
2. If they differ: present a unified diff and let the user manually edit the brain version.
3. Secrets (tokens, API keys) must never be versioned — if detected in the quarantined local, warn the user and do NOT import.

### 5. Atomic-write detection

Some runtimes (notably OpenCode via oh-my-openagent) perform atomic writes that replace symlinks with flat files. After merge, verify that runtime symlinks still point into the brain:

```bash
ls -la ~/.claude/CLAUDE.md ~/.config/opencode/AGENTS.md
```

If a symlink has been replaced by a flat file, diff it against the brain version and re-establish the symlink after reconciling any new content.

### 6. Cleanup

After the merge is complete and the user confirms:

1. Remove the quarantine directory: `rm -rf INBOX/_RUNTIME/<RT>/`
2. Commit with message `merge: <RT> conflict resolved, quarantine cleared`.
3. If any files were left in quarantine (user declined to import), record them in the daily note for future reference.
