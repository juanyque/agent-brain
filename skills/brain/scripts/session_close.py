#!/usr/bin/env python3
"""Session-close ceremony script.

Replaces the 5-8 manual edits of the current close ceremony with one invocation.

Subcommands:
  handoff <session-id>              Mark session as handoff-only (same session continues another day).
  consolidate <session-id>          Mark session as consolidated (work preserved, session done).
    [--archive]                     Additionally move the note to QUARANTINE/TRASH/ via git mv.

Dry-run by default; pass --apply to write changes.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

VALID_TRANSITIONS: dict[str, list[str]] = {
    "handoff": ["open"],
    "consolidate": ["open", "handoff-only"],
}

STATUS_LINE_RE = re.compile(r"^(-\s+Status:)\s*(.+)$")
WIP_TAG_RE = re.compile(r"\bwip\b")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Session-close ceremony: mark session state and optionally archive."
    )
    parser.add_argument(
        "--vault-root",
        required=True,
        help="Vault root path.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write changes. Default is dry-run.",
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    handoff_p = subparsers.add_parser("handoff", help="Mark session as handoff-only.")
    handoff_p.add_argument("session_id", help="Session ID (or unambiguous prefix).")

    consolidate_p = subparsers.add_parser("consolidate", help="Mark session as consolidated.")
    consolidate_p.add_argument("session_id", help="Session ID (or unambiguous prefix).")
    consolidate_p.add_argument(
        "--archive",
        action="store_true",
        help="Move the consolidated note to QUARANTINE/TRASH/ via git mv.",
    )

    return parser.parse_args()


def find_session_note(vault_root: Path, session_id: str) -> Path | None:
    """Find a session note in WIP/SESSIONS/ whose filename contains session_id.

    When multiple notes match (e.g. same session spanning two days), prefer the
    most recent note whose status is active (open or handoff-only). Falls back to
    the most recent note overall if all are in terminal states.
    """
    session_dir = vault_root / "WIP" / "SESSIONS"
    if not session_dir.exists():
        return None
    matches = [p for p in session_dir.glob("*.md") if session_id in p.name]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        active = sorted(
            [p for p in matches if read_session_status(p) in ("open", "handoff-only")],
            reverse=True,  # alphabetical desc = most-recent-first for date-prefixed names
        )
        if active:
            chosen = active[0]
            print(
                f"NOTE: ambiguous — {len(matches)} notes match '{session_id}'; "
                f"using most recent active: {chosen.name}",
                file=sys.stderr,
            )
            return chosen
        # All notes are in terminal states; fall back to most recent overall.
        chosen = sorted(matches, reverse=True)[0]
        print(
            f"NOTE: ambiguous — {len(matches)} notes match '{session_id}' (all terminal); "
            f"using most recent: {chosen.name}",
            file=sys.stderr,
        )
        return chosen
    return None


def read_session_status(note_path: Path) -> str | None:
    try:
        for line in note_path.read_text(encoding="utf-8").splitlines():
            m = STATUS_LINE_RE.match(line.strip())
            if m:
                return m.group(2).strip()
    except OSError:
        pass
    return None


def patch_status(note_path: Path, new_status: str, apply: bool) -> tuple[bool, str]:
    """Return (changed, old_status). Writes if apply=True."""
    try:
        text = note_path.read_text(encoding="utf-8")
    except OSError as exc:
        return (False, f"read error: {exc}")

    old_status = None
    lines = text.splitlines(keepends=True)
    new_lines: list[str] = []
    changed = False
    for line in lines:
        m = STATUS_LINE_RE.match(line.rstrip("\n"))
        if m and old_status is None:
            old_status = m.group(2).strip()
            new_lines.append(f"{m.group(1)} {new_status}\n")
            changed = True
        else:
            new_lines.append(line)

    if not changed:
        return (False, "Status line not found")

    if apply:
        try:
            note_path.write_text("".join(new_lines), encoding="utf-8")
        except OSError as exc:
            return (False, f"write error: {exc}")

    return (True, old_status or "")


def remove_wip_tag(note_path: Path, apply: bool) -> bool:
    """Remove 'wip' from the frontmatter tags list. Return True if changed."""
    try:
        text = note_path.read_text(encoding="utf-8")
    except OSError:
        return False

    # Match tags: [session, wip] or tags: [wip, session] or tags: [wip]
    new_text = re.sub(
        r"(tags:\s*\[)([^\]]*\bwip\b[^\]]*)\]",
        lambda m: m.group(1) + re.sub(r",?\s*\bwip\b\s*,?", lambda s: "," if s.group().strip().endswith(",") else "", m.group(2)).strip(", ") + "]",
        text,
    )
    if new_text == text:
        return False
    if apply:
        try:
            note_path.write_text(new_text, encoding="utf-8")
        except OSError:
            return False
    return True


def git_mv(src: Path, dst: Path, apply: bool) -> bool:
    """Run git mv src dst. Return True on success."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["git", "mv", str(src), str(dst)]
    if not apply:
        print(f"  would run: {' '.join(cmd)}")
        return True
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"ERROR: git mv failed: {result.stderr.strip()}", file=sys.stderr)
        return False
    return True


def main() -> int:
    args = parse_args()
    vault_root = Path(args.vault_root).expanduser().resolve()
    if not vault_root.is_dir():
        print(f"ERROR: vault root not found: {vault_root}", file=sys.stderr)
        return 1

    mode = "apply" if args.apply else "dry-run"
    subcommand: str = args.subcommand
    session_id: str = args.session_id

    note_path = find_session_note(vault_root, session_id)
    if note_path is None:
        print(f"ERROR: session note not found for id '{session_id}'", file=sys.stderr)
        print(f"  searched in: {vault_root / 'WIP' / 'SESSIONS'}", file=sys.stderr)
        return 1

    current_status = read_session_status(note_path)
    if current_status is None:
        print(f"WARNING: could not read Status line from {note_path.name}")

    allowed_from = VALID_TRANSITIONS[subcommand]
    if current_status and current_status not in allowed_from:
        print(f"ERROR: invalid state transition.", file=sys.stderr)
        print(f"  current status: {current_status}", file=sys.stderr)
        print(f"  '{subcommand}' requires status to be one of: {', '.join(allowed_from)}", file=sys.stderr)
        return 1

    note_rel = note_path.relative_to(vault_root)
    new_status = "handoff-only" if subcommand == "handoff" else "consolidated"

    print(f"# Session close — {subcommand}")
    print(f"mode: {mode}")
    print(f"session_note: {note_rel}")
    print(f"status: {current_status} → {new_status}")
    print()

    ok, old = patch_status(note_path, new_status, apply=args.apply)
    if ok:
        action = "updated" if args.apply else "would update"
        print(f"  {action}: Status: {old} → {new_status}")
    else:
        print(f"  ERROR patching status: {old}", file=sys.stderr)
        return 1

    if subcommand == "consolidate":
        wip_changed = remove_wip_tag(note_path, apply=args.apply)
        if wip_changed:
            action = "removed" if args.apply else "would remove"
            print(f"  {action}: 'wip' tag from frontmatter")

        if args.archive:
            trash_dir = vault_root / "QUARANTINE" / "TRASH"
            dst = trash_dir / note_path.name
            ok = git_mv(note_path, dst, apply=args.apply)
            if not ok:
                return 1
            action = "moved" if args.apply else "would move"
            print(f"  {action}: {note_rel} → QUARANTINE/TRASH/{note_path.name}")
            print()
            print("NOTE: QUARANTINE/TRASH/ is reversible — permanent deletion requires explicit user approval.")

    print()
    if args.apply:
        print("Done.")
    else:
        print("(dry-run — pass --apply to write changes)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
