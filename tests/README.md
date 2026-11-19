# Tests

The test suite protects agent-brain's deterministic installation and brain-lifecycle
contracts. Tests create isolated temporary directories; they do not modify a real
brain, runtime home, Git history, or remote state. Focused lifecycle subsets use only
the standard library, while the complete governed gate supplies `jsonschema`,
`pydantic`, and `pyyaml` through `uv`.

## Run the suite

From the repository root:

```bash
uv run --python 3.12 \
  --with 'jsonschema>=4.25,<5' \
  --with 'pydantic>=2.10,<3' \
  --with 'pyyaml>=6.0.2,<7' \
  python3 -m unittest discover -s tests -v
```

Run one module or one test directly when iterating:

```bash
python3 -m unittest tests.test_session_open -v
python3 -m unittest \
  tests.test_session_open.SessionRecoveryTests.test_full_apply_can_be_repeated_without_duplicate_artifacts \
  -v
```

For a fast check of the model and public-boundary gates (about 1.5 minutes
instead of the full suite's ~14), run:

```bash
python3 -m unittest tests.test_model_check tests.test_model_gates tests.test_public_boundary -v
python3 model/SCRIPTS/model_check.py --strict --format json
```

`test_public_boundary` skips its private-marker check unless `git config pushgate.valuesFile`
points to a forbidden-values file.

The complete local gate (suite, compile, shell syntax, whitespace and strict checker) is the command list under "Local and CI gates" in the top-level
`README.md`.

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
| `test_find_home.py` | Strict current-model brain identity, separation from bootstrap candidates, wrong/broken `_COMMON` rejection, ancestor resolution, nested-brain metadata, symlink traversal safety, and the outside-a-brain fallback (machine default, single-brain HOME scan, ambiguity, conflict never bypassed, `--no-scan`, `--all`). |
| `test_brain_default.py` | The per-machine default brain: dry-run unless `--apply`, validation, atomic private write, unusable defaults reported but never deleted, and `XDG_CONFIG_HOME`. |
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
| `test_model_gates.py` | `StrictGateTests`: negative probes for orphan model artifacts, startup budget overflow, untracked out-of-scope files, and untracked whitespace. `WorkflowContractTests`: static workflow contract for full-history checkout, per-event `MODEL_BASE` resolution through `tests/support/resolve_model_base.sh` (no pinned commit), `MODEL_BASE` object verification, and macOS/Linux committed/worktree gates and test steps. `OperatingModelContractTests`: canonical `OPERATING-MODEL.json`, governed inventory matching on-disk Markdown, and 13 unique route triples linked from the router. `RetiredManifestKeyGuardTests`: the manifest and the routed text carry none of the retired baseline/materialization keys or markers. `BudgetContractTests`: `context-budget-exceeded` is a required default selector (a manifest that drops or disables it is rejected) and plain `--strict` fails on a startup or scenario cap overflow. `LoadingUsageErrorOrderingTests`: default `--strict` reports structural route findings (exit 1) when the loading data is uncomputable, exits 2 when no other error explains it, and `--only` never swallows the usage error. `TrackedTextWhitespaceTests`: tracked `*.md`/`*.j2` files carry no trailing whitespace. |
| `test_resolve_model_base.py` | Hermetic throwaway-repo tests for `tests/support/resolve_model_base.sh`: pull request base, push to an existing branch (single/multi-commit, force-push diverged or missing `before`), push creating a branch (merge-base with `origin/<default>`, missing ref), unrelated histories, root and merge commits, unsupported events, stdout contains only the SHA, and no fallback to `HEAD`, `HEAD~1`, or the root commit. |

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

GitHub Actions runs the complete dependency-bearing suite and strict operating-model gates on both
`ubuntu-latest` and `macos-latest`. The workflow uses full checkout history, proves the selected
comparison base object, runs committed-range whitespace/scope checks, then runs worktree
scope/whitespace checks after compile and shell syntax validation.
