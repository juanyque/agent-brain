# Brain postcondition check

`brain_check.py` is a read-only verifier for the invariants that should hold after
session and active-WIP writes. It never edits the brain.

## Session registration

```bash
python3 ~/.agents/skills/brain/scripts/brain_check.py \
  --brain-root /path/to/brain \
  --session-id <real-runtime-id> \
  --runtime codex \
  --cwd /original/working/directory
```

The check fails unless:

- one session note exists for the full session id;
- its recovery command contains the expected runtime command and original cwd;
- today's daily has exactly one matching entry under `# Sessions`;
- that entry contains the same recovery command;
- the section contains no known template scaffold.

Use `--date YYYY-MM-DD` when verifying a registration from another day.

## Active WIP registration

```bash
python3 ~/.agents/skills/brain/scripts/brain_check.py \
  --brain-root /path/to/brain \
  --wip-note WIP/project-name.md
```

The check fails when the note does not exist or `WIP/WIP.md` does not link it.
Repeat `--wip-note` to verify multiple active notes. Session notes are not active
project WIP and do not need to be passed here.

Both forms can be combined in one invocation. Exit code `0` means all requested
postconditions hold; `1` means at least one invariant failed; `2` means the
invocation itself is invalid.
