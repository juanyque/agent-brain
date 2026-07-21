# Memory query

`memory_query.py` ranks entries from a user's curated memory indexes without reading note bodies.
It is a context-saving router, not a semantic search engine.

```bash
python3 ~/.agents/skills/brain/scripts/memory_query.py \
  --cwd "$PWD" \
  --keywords "git worktree validation"
```

The default output is limited to five candidates and 4096 bytes. Open only the returned notes
that are relevant to the current task. Do not pre-load the full index or every candidate.

Options:

- `--memory-root PATH`: override `~/.agents/brain-memory`.
- `--limit N`: return 1 to 10 candidates.
- `--max-bytes N`: cap output between 512 and 16384 bytes.
- `--json`: emit machine-readable output.

The tool is read-only and uses Python's standard library.
