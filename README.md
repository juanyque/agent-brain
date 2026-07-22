# agent-brain

**Notes-agnostic second-brain operating model + multi-runtime agent config/memory versioning.**

agent-brain is a personal operating model for AI coding agents (Claude Code, OpenCode, Codex). It gives you:

- A **second-brain** knowledge structure (journal, WIP, memory, tasks) that the model builds on top of any folder of notes — Obsidian is one option, not a requirement.
- **Version-controlled runtime config & memory**: your `CLAUDE.md` / `AGENTS.md`, memory, and runtime settings live in a git-tracked *brain* and are symlinked into each runtime (`~/.claude`, `~/.config/opencode`, …), so your agent configuration and memory travel with you across machines.
- A **session lifecycle** (daily notes, session notes, consolidation) driven by the `brain` skill.
- An optional **boyscout** skill: spot improvement opportunities while you work, then route them to an explicit remediation workflow or backlog.

## Prerequisites

- **Python 3.x** (stdlib only — no pip dependencies)
- **git** on PATH
- At least one supported agent runtime installed:
  - [Claude Code](https://docs.anthropic.com/en/docs/claude-code) → `~/.claude/`
  - [OpenCode](https://opencode.ai/) → `~/.config/opencode/`
  - Shared agents dir → `~/.agents/`
  - Codex CLI → `~/.codex/` (`AGENTS.md` and `config.toml` are persisted under the private brain's `_AGENTS/CODEX/`; the brain skill is installed at `~/.agents/skills/brain`)

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/juanyque/agent-brain/main/bootstrap-zero.sh | bash
```

This clones agent-brain to `~/.local/share/agent-brain` and runs the orchestrator, which
will ask for your brain path (an Obsidian vault, a notes folder, or a new empty dir). It
dry-runs by default — review the plan, then apply:

```bash
curl -fsSL https://raw.githubusercontent.com/juanyque/agent-brain/main/bootstrap-zero.sh \
  | bash -s -- --brain /path/to/brain --apply
```

### If `_COMMON` already exists

If your brain already has a `_COMMON` symlink pointing to a different model (e.g. a previous setup), the dry-run reports the change. On `--apply`, the installer preserves the existing entry as `_COMMON.backup-<ts>` and repoints `_COMMON` to agent-brain automatically. The Git snapshot created before installation provides an additional rollback anchor.

### Flags

| Flag | Purpose |
|---|---|
| `--brain <path>` | Brain root path (skips interactive prompt) |
| `--apply` | Execute (default: dry-run) |
| `--update` | `git pull --ff-only` the repo before wiring |
| `--runtime claude,opencode,agents,codex` | Restrict to a comma-separated runtime subset (default: all detected) |

## How it works

The installer is a thin orchestrator that delegates to two layers:

1. **`brain_state`** — state machine (`virgin` → `attached` → `initial` → `maintenance`). Determines what flow to run based on the brain's current state.
2. **`home_setup`** — structure: pre-cleanup, staging (for virgin brains), `_COMMON` symlink, wrapper files, templates.
3. **`runtime_manager`** — all runtime config: detects each runtime, ingests local config into the brain (Direction A), implants brain config into local (Direction B), handles conflicts, links skills.
4. **`runtime_health`** — read-only post-apply validation for every selected runtime, using the same mapping matrix as `runtime_manager`.

Runtime policy and private configuration belong to the private brain, not this public repository.
When a brain contains `_AGENTS/SHARED/memory/`, Codex receives a stable pointer at
`~/.agents/brain-memory`; the bundled query tool ranks a small number of indexed notes on
demand. Codex's own generated `~/.codex/memories/` directory remains local and separate.

### Environment profiles

Environment profiles provide a runtime-neutral contract for selecting issue trackers,
repositories, project conventions, and optional private resources without embedding those
values in the public core. Profiles live in the private brain under
`_AGENTS/SHARED/profiles/`; global runtime symlinks remain stable when profiles change.

See [`docs/runtime-profiles.md`](docs/runtime-profiles.md) for the versioned schema, selection
algorithm, precedence, safety rules, and sanitized examples. `model/SCRIPTS/runtime_health.py`
loads and validates these files when they exist in a brain. Use `--profile <id>` for explicit
selection or `--cwd <path>` to exercise project-rule selection. MCP/API availability is
delegated to the active runtime adapter; the read-only check never treats a configured
provider name as proof of live access.

Skills can call `skills/brain/scripts/profile_context.py` to resolve generic capabilities into
sanitized provider context. `--live` checks the Codex MCP registry/auth boundary, while the caller
can pass exact `--available-tool` names plus `--tool-catalog-complete` to enforce active exposure.
An omitted or incomplete catalog remains unverified. Claude live discovery is refused because its
official registry command may rewrite runtime settings.

Runtime adapters can project standalone private profile resources with
`model/SCRIPTS/profile_overlays.py`. The adapter supplies explicit roots for each selected resource
kind; the dry-run-first projector links brain-owned sources, quarantines conflicts, and is safe to
apply repeatedly without rewriting runtime configuration.

`model/SCRIPTS/profile_secrets.py` checks referenced secret names without returning their values.
Environment presence, metadata-only macOS keychain lookup, and sanitized runtime-native catalogs
share the same fail-closed status contract.

Git is used as rollback anchor: a local snapshot commit or annotated tag is created before any
mutation. Snapshot messages are deterministic and snapshot signing is disabled so unattended
bootstrap runs never open an editor or a GPG prompt. Nothing is pushed automatically.

## Skills

Two skills ship with agent-brain, but only the operating skill is installed automatically:

| Skill | Command | Installation | Purpose |
|---|---|---|---|
| **brain** | `/brain` (Codex: `$brain`) | Automatic | Connect to the brain, manage session lifecycle, daily notes, and standardization |
| **boyscout** | `/boyscout` (Codex: `$boyscout`) | Opt-in | Spot improvement opportunities and route them to an explicit remediation workflow or backlog |

Skills live outside the brain and are symlinked to the repo. Codex discovers global user skills
under `~/.agents/skills/`; other runtimes use their own user-skill directory. Skill files use
normal names without the `.common.md` suffix.

The brain skill's session-open apply is idempotent: it creates or updates one session note,
upserts exactly one daily recovery entry keyed by the full session ID, preserves a manually
edited summary, and checks the resulting session/daily state. Active WIP notes can be checked
against the `WIP/WIP.md` dashboard with the bundled read-only `brain_check.py` tool.

Install `boyscout` for Codex only when wanted. Review the dry-run first:

```bash
bash ~/.local/share/agent-brain/model/SCRIPTS/skill_link.sh boyscout ~/.agents
bash ~/.local/share/agent-brain/model/SCRIPTS/skill_link.sh boyscout ~/.agents --apply
```

## Repository layout

```
agent-brain/
├── bootstrap-zero.sh     # curl entry point (clones repo, dispatches to orchestrator)
├── docs/                 # public architecture and versioned profile schemas
├── examples/profiles/    # sanitized environment-profile examples
├── model/                # the operating model — what _COMMON symlinks to inside a brain
│   ├── AGENTS.common.md  # shared agent instructions
│   ├── BRAIN.common.md   # brain structure & conventions
│   ├── RULES-*.common.md # daily notes, file naming, links, sessions, evidence
│   ├── JOBS.common.md    # recurring maintenance routines
│   ├── TASK_TYPES/       # how-to guides for recurring task types
│   ├── TEMPLATES/        # daily note, WIP, issue, report templates
│   └── SCRIPTS/
│       ├── brain_state.py       # state machine (shared)
│       ├── home_setup.py        # structure (cleanup, staging, _COMMON, wrappers)
│       ├── runtime_manager.py   # runtime config (Direction A/B, conflict, skill link)
│       ├── runtime_health.py    # post-apply checks for all supported runtimes
│       ├── profile_overlays.py  # optional private-resource projection
│       ├── profile_secrets.py   # value-free secret-reference preflight
│       ├── runtime_install.sh   # low-level symlink helper (called by runtime_manager)
│       └── skill_link.sh        # manual skill installer for non-default skills
└── skills/
    ├── brain/            # session lifecycle, daily notes, maintenance
    │   ├── SKILL.md
    │   ├── scripts/      # session_open.py, brain_check.py, find_home.py, ...
    │   └── references/   # project-aware-loading, setup-and-attach, brain-maintenance, runtime-merge
    └── boyscout/         # improvement-spotting + backlog management
        ├── SKILL.md
        ├── scripts/      # backlog.py, doctor.py, fix-ceremony.sh
        └── references/   # finding-schema, detection guides, ticket backends, deep-mode, ...
```

Files under `model/` keep the `.common.md` naming convention because they live inside a brain (via `_COMMON`) and must stay link-safe for notes apps. `skills/` and the repo root use normal names.

## Tests

The stdlib-only test suite runs entirely against temporary brains, homes, and Git
repositories:

```bash
python3 -m unittest discover -s tests -v
```

CI executes the same suite on macOS and Linux. The profile integration test uses an isolated
temporary `HOME` and verifies dry-run safety, conflict quarantine, and double-apply idempotence.

See [`tests/README.md`](tests/README.md) for the covered contracts, individual-test
commands, and fixture rules.

## Origin

Evolved from `obsidian-vault-common` (private). This is the clean, notes-agnostic, multi-runtime rewrite.

## License

TBD.
