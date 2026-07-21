# runtime_health.py

## Purpose

Read-only post-apply verification for runtime wiring. It imports `RUNTIME_CONFIGS` from
`runtime_manager.py`, so the installer and health check use the same runtime mappings.

## What it checks

For each selected active runtime:

- every brain-managed mapping resolves from the expected local runtime path;
- local mapped state is not left without its canonical brain source;
- the bundled `brain` skill resolves from the runtime's user-skill location;
- private mapped files retain their required permissions;
- Codex's shared curated-memory link resolves when the brain provides that memory.

Supported runtimes are Claude, OpenCode, Agents, and Codex. Inactive runtimes are reported as
`SKIP`, not failures.

## Usage

```bash
python3 runtime_health.py --brain <path>
python3 runtime_health.py --brain <path> --runtime claude
python3 runtime_health.py --brain <path> --runtime claude --runtime codex
```

The script exits non-zero when any selected runtime fails validation. `bootstrap-zero.sh` runs it
automatically after a successful apply and converts any failure into the bootstrap health-check
failure exit.
