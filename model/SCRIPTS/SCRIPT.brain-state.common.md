# brain_state.py

## Purpose

Authoritative brain state machine (D21/D24). Shared by `home_setup`, `runtime_manager`, and `bootstrap`. Consulted before any mutation to decide the correct flow.

## States

| State | `_COMMON` | Markers | `_STAGING` | Flow |
|---|---|---|---|---|
| `virgin` | missing | absent | — | Full: stage → attach |
| `attached-link-missing` | missing | present | — | Re-create `_COMMON` + wrappers, no staging |
| `initial` | ok | — | has content | No re-stage; standardize drains `_STAGING` |
| `maintenance` | ok | — | absent | No re-order; idempotent refresh |
| `conflict` | wrong target | — | — | D25: ask switch / `--switch-model` |

## Interface

```python
from brain_state import detect_state, link_status, staging_status, has_markers

state = detect_state(brain_root, common_target)  # → str
status, desired = link_status(brain_root, common_target)  # → tuple[str, str]
status, count = staging_status(brain_root)  # → tuple[str, int]
has_markers(brain_root)  # → bool
```

## Constants

`COMMON_LINK_NAME`, `STAGING_DIR_NAME`, `AGENTS_DIR_NAME`, `OPERATIONAL_TOP_LEVEL_DIRS` — imported by `home_setup` and `runtime_manager` as the single source of truth.
