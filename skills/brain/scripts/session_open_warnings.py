"""Advisory diagnostics for the session-open request.

Pure and read-only: they never fail session-open, never rewrite the caller's
flags and never enter the postcondition errors (those trigger rollback).
Matching runtime and cwd do not prove a correct session id, and absent markers
leave the runtime unverifiable.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

RUNTIME_ENV_MARKERS: dict[str, tuple[str, ...]] = {
    "codex": ("CODEX_SESSION_ID", "CODEX_THREAD_ID"),
    "claude": ("CLAUDE_CODE_SESSION_ID",),
    "opencode": ("OPENCODE_SESSION_ID",),
}


def _resolved(path: str | Path, base: Path) -> Path | None:
    try:
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = base / candidate
        return candidate.resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        return None


def _cwd_warning(cwd: str, process_cwd: str | Path | None) -> str | None:
    if not cwd.strip() or process_cwd is None:
        return None
    process = _resolved(process_cwd, Path("/"))
    supplied = _resolved(cwd.strip(), process) if process is not None else None
    if process is None or supplied is None or supplied == process:
        return None
    return (
        f"cwd-mismatch: --cwd ({supplied}) differs from the process working directory "
        f"({process}); may be intentional, but the recovery command will use --cwd."
    )


def _runtime_warning(
    runtime: str, runtime_explicit: bool, environ: Mapping[str, str]
) -> str | None:
    present = {
        family: [name for name in names if environ.get(name, "").strip()]
        for family, names in RUNTIME_ENV_MARKERS.items()
    }
    observed = {family: names for family, names in present.items() if names}
    if len(observed) > 1:
        families = ", ".join(sorted(observed))
        return (
            f"runtime-env-ambiguous: environment markers of several runtimes are set "
            f"({families}); cannot confirm which runtime this session runs in."
        )
    if len(observed) == 1 and runtime_explicit:
        (family, names), = observed.items()
        requested = (runtime or "").strip().lower()
        if requested not in ("", "generic", family):
            return (
                f"runtime-env-mismatch: --runtime {requested} but the environment indicates "
                f"{family} ({', '.join(names)}); the resume command follows --runtime."
            )
    return None


def session_request_warnings(
    runtime: str,
    cwd: str,
    *,
    runtime_explicit: bool = True,
    process_cwd: str | Path | None,
    environ: Mapping[str, str],
) -> tuple[str, ...]:
    warnings = (
        _cwd_warning(cwd, process_cwd),
        _runtime_warning(runtime, runtime_explicit, environ),
    )
    return tuple(warning for warning in warnings if warning)
