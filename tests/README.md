# Tests

The test suite protects agent-brain's deterministic installation and brain-lifecycle
contracts. Tests use Python's standard library only and create isolated temporary
directories; they do not modify a real brain, runtime home, Git history, or remote state.

## Run the suite

From the repository root:

```bash
python3 -m unittest discover -s tests -v
```

Run one module or one test directly when iterating:

```bash
python3 -m unittest tests.test_session_open -v
python3 -m unittest \
  tests.test_session_open.SessionRecoveryTests.test_full_apply_can_be_repeated_without_duplicate_artifacts \
  -v
```

Some negative-path tests intentionally print `FAIL` or `SKIP` diagnostics produced by
the code under test. The authoritative result is unittest's final `OK` / `FAILED`
summary and process exit code.

## Coverage by module

| Module | Contract protected |
|---|---|
| `test_runtime_health.py` | Runtime detection and symlink/config health checks for Claude, OpenCode, shared agents, and Codex. Includes deliberately broken fixtures to prove failures are detected. |
| `test_runtime_manager.py` | Dry-run safety plus Direction A ingestion, Direction B implantation, conflict quarantine, Codex private-file permissions, runtime isolation, and double-apply idempotence. |
| `test_home_setup.py` | Brain-state detection, preservation of existing wrappers/templates, `_COMMON` conflict backup/switch, virgin staging, and repeated apply without drift. |
| `test_bootstrap.py` | Non-interactive explicit-brain execution, deterministic initial snapshot commits, unsigned annotated tags even with signing enabled, and dirty-repository refusal without Git mutation. |
| `test_session_open.py` | Runtime-specific recovery commands, original cwd persistence, clean daily preparation, local/common template conflict refusal, idempotent session-note and daily registration, duplicate removal, and postcondition failures. |
| `test_session_close.py` | Dry-run safety, idempotent handoff/consolidation, safe refusal to archive untracked notes, and repeatable tracked archival. |
| `test_brain_check.py` | Read-only verification that active WIP notes are registered in `WIP/WIP.md`, for both Obsidian wikilinks and standard Markdown links. |

## Test design rules

- Prefer behavior-level tests over assertions on implementation details.
- Every mutating script must be dry-run by default and have an apply-path test.
- Every operation advertised as idempotent must be executed at least twice in one test;
  the second run must produce no duplicate artifacts or content drift.
- Include the unsafe or invalid counterpart for health checks and validators, so a test
  cannot pass merely because the checker always returns success.
- Use `tempfile.TemporaryDirectory`; never point tests at a user's actual brain or home.
- Keep fixtures minimal and include only the files required by the contract under test.

Before handing changes back for review, also run:

```bash
python3 -m py_compile skills/brain/scripts/*.py
git diff HEAD --check
```
