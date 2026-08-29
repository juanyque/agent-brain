#!/usr/bin/env python3
"""Session-open ceremony compatibility facade."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


# session_digest.py (imported below, transitively) requires Python 3.10+
# (dataclass slots=True). Rather than rely on the caller's PATH already
# resolving `python3` to a new enough interpreter, re-exec under the newest
# 3.10+ interpreter found on PATH before that import runs.
if sys.version_info < (3, 10):
    for _candidate in ("python3.13", "python3.12", "python3.11", "python3.10"):
        _found = shutil.which(_candidate)
        if _found:
            os.execv(_found, [_found, *sys.argv])
    sys.exit(
        "session_open.py requires Python 3.10+ (dataclass slots=True); none of "
        "python3.10/python3.11/python3.12/python3.13 found on PATH."
    )


REPO_ROOT = Path(__file__).resolve().parents[3]
MODEL_SCRIPTS = REPO_ROOT / "model" / "SCRIPTS"
SCRIPT_DIR = Path(__file__).resolve().parent
if str(MODEL_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(MODEL_SCRIPTS))
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import session_open_daily  # noqa: E402
from session_digest import (  # noqa: E402
    SessionDigestFixtureData,
    SessionDigestRequest,
    SessionDigestState,
    fixed_session_digest_fixture_data,
    fixed_session_digest_request,
    normalize_cwd,
    render_session_digest,
    resume_command,
)
from session_open_cli import (  # noqa: E402
    detect_runtime,
    main as _cli_main,
    parse_args,
)
from session_open_context import (  # noqa: E402
    collect_session_digest_state,
    derive_topic,
    extract_task_types,
    extract_wip_context,
    slugify,
)
from session_open_discovery import (  # noqa: E402
    JournalConfigError,
    find_daily_neighbors,
    find_daily_template,
    find_existing_session_note,
    find_template,
    is_session_open,
    list_daily_notes,
    list_session_notes,
    load_journal_folder,
    read_lines_safe,
    read_text_safe,
)
from session_open_flow import SessionOpenHooks  # noqa: E402
from session_open_fs import UnsafeDailyPathError, _write_text  # noqa: E402
from session_open_navigation import (  # noqa: E402
    daily_navigation_targets,
    instantiate_daily_template,
    rewrite_daily_navigation,
)
from session_open_registration import (  # noqa: E402
    build_sessions_entry,
    instantiate_session_template,
    upsert_session_recovery,
    upsert_sessions_entry,
)
from session_open_validation import (  # noqa: E402
    validate_daily_navigation,
    validate_session_postconditions,
)


def prepare_daily_note(
    brain_root: Path,
    daily_path: Path,
    day: str,
    apply: bool,
) -> str:
    return session_open_daily.prepare_daily_note(
        brain_root,
        daily_path,
        day,
        apply,
        _write_text,
    )


def main() -> int:
    hooks = SessionOpenHooks(
        instantiate_session_template=instantiate_session_template,
        upsert_sessions_entry=upsert_sessions_entry,
        prepare_daily_note=prepare_daily_note,
    )
    return _cli_main(hooks)


if __name__ == "__main__":
    raise SystemExit(main())
