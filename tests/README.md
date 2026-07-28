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

The complete governed local gate is declared in
`tests/fixtures/operating-model-qa-commands.json` as alias `complete-local-gate`. Run it through
the run-todo wrapper so the invocation, manifest command, plan SHA, implementation SHA, stdout,
stderr, and status are captured as receipt-verifiable evidence:

```bash
python3 tests/support/evidence_cli.py run-todo \
  --todo 19 \
  --step 1 \
  --cwd . \
  --evidence-root /path/to/evidence-root \
  --shell '<canonical command from the QA manifest>'
```

Some negative-path tests intentionally print `FAIL` or `SKIP` diagnostics produced by
the code under test. The authoritative result is unittest's final `OK` / `FAILED`
summary and process exit code.

## Coverage by module

| Module | Contract protected |
|---|---|
| `test_runtime_health.py` | Runtime detection and symlink/config health checks for Claude, OpenCode, shared agents, and Codex. Includes deliberately broken fixtures to prove failures are detected. |
| `test_skill_link.py` | Dry-run safety, external repo skill paths, all-runtime linking, idempotence, latest-run audit logging, and invalid-source rejection for `skill_link.sh`. |
| `test_runtime_manager.py` | Dry-run safety plus Direction A ingestion, Direction B implantation, conflict quarantine, Codex private-file permissions, runtime isolation, and double-apply idempotence. |
| `test_home_setup.py` | Brain-state detection, preservation of existing wrappers/templates, unambiguous current-vs-desired `_COMMON` conflict reporting, conflict backup/switch, virgin staging, and repeated apply without drift. |
| `test_home_setup_symlinks.py` | Repair of every bootstrap-managed template symlink when it still points to a previous model. |
| `test_bootstrap.py` | Bootstrap-candidate discovery, non-interactive explicit-brain execution, deterministic initial snapshot commits, unsigned annotated tags even with signing enabled, and dirty-repository refusal without Git mutation. |
| `test_find_home.py` | Strict current-model brain identity, separation from bootstrap candidates, wrong/broken `_COMMON` rejection, ancestor resolution, nested-brain metadata, and symlink traversal safety. |
| `test_session_open.py` | Current-model identity guard, runtime-specific recovery commands, original cwd persistence, project-filtered WIP discovery including optional-capability links, chronological daily discovery across archive folders, reciprocal nearest-neighbor navigation across date gaps and backfills, dry-run and rollback safety, local/common template conflict refusal, idempotent session-note and daily registration with canonical link refresh, duplicate removal, and postcondition failures. |
| `test_session_close.py` | Current-model brain identity enforcement, dry-run safety, idempotent handoff/consolidation, `--apply` placement before or after subcommands, safe refusal to archive untracked notes, final staged-content integrity, rollback on move/staging failures, and repeatable tracked archival. |
| `test_brain_check.py` | Read-only session verification across active and archived notes with active-note precedence, plus active-WIP registration through Obsidian wikilinks and standard Markdown links. |
| `test_boyscout_doctor.py` | Boyscout portable reference graph, detector parity, backlog round-trip, and rejection of private-layout migration artifacts. |
| `test_find_related_notes.py` | CLI behavior across filename/content/both note discovery modes and structured missing-brain errors. |
| `test_runtime_profiles.py` | Sanitized profile selection, capability-route integrity, and the public/private content boundary. |
| `test_environment_profiles.py` | Stdlib profile loading, strict validation, deterministic selection, and provider preflight states. |
| `test_profile_overlays.py` | Runtime-neutral overlay planning, dry-run safety, conflict quarantine, path validation, and double-apply idempotence. |
| `test_profile_secrets.py` | Value-free environment, metadata-only macOS keychain, and sanitized runtime-catalog secret preflight. |
| `test_profile_integration.py` | End-to-end profile selection, value-free preflight, conflict quarantine, projection, and double-apply behavior under an isolated temporary `HOME`. |
| `test_runtime_provider_discovery.py` | Sanitized Codex/Claude MCP registry discovery and readiness normalization. |
| `test_profile_context.py` | Skill-facing capability resolution, runtime invocation hints, and fail-closed exact matching against complete caller-supplied active tool catalogs. |
| `test_model_check.py::StrictGateTests` | Negative probes for orphan model artifacts, startup budget overflow, untracked out-of-scope files, and untracked whitespace. |
| `test_model_check.py::WorkflowContractTests` | Static workflow contract for full-history checkout, `MODEL_BASE` object verification, PR/push/root fallback selection, and macOS/Linux committed/worktree gates. |

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
python3 tests/support/compile_sources.py model/SCRIPTS skills tests
git diff HEAD --check
```

GitHub Actions runs the complete stdlib suite and strict operating-model gates on both
`ubuntu-latest` and `macos-latest`. The workflow uses full checkout history, proves the selected
comparison base object, runs committed-range whitespace/scope checks, then runs worktree
scope/whitespace checks after compile and shell syntax validation.
