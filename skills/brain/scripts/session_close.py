#!/usr/bin/env python3
"""Session-close ceremony script.

Replaces the 5-8 manual edits of the current close ceremony with one invocation.

Subcommands:
  handoff <session-id>              Mark session as handoff-only (same session continues another day).
  consolidate <session-id>          Mark session as consolidated (work preserved, session done).
    [--archive]                     Additionally move the note to QUARANTINE/TRASH/ via git mv.

Dry-run by default; pass --apply to write changes. State transitions and archives
are idempotent. Archival preflights Git tracking and destination safety before
editing the note, stages the final consolidated destination, and restores the
original path and content if the move or staging step fails.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import date
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
MODEL_SCRIPTS = REPO_ROOT / "model" / "SCRIPTS"
if str(MODEL_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(MODEL_SCRIPTS))

from brain_state import current_brain_status, current_model_root  # noqa: E402
from session_open_discovery import (  # noqa: E402
    JournalConfigError,
    list_daily_notes,
    load_journal_folder,
)
from source_scheduler import registry_activated, summarize_due_sources  # noqa: E402


VALID_TRANSITIONS: dict[str, list[str]] = {
    "handoff": ["open"],
    "consolidate": ["open", "handoff-only"],
}

STATUS_LINE_RE = re.compile(r"^(-\s+Status:)\s*(.+)$")
WIP_TAG_RE = re.compile(r"\bwip\b")


def normalize_apply_flag(argv: list[str]) -> list[str]:
    """Accept --apply before or after the subcommand.

    argparse only recognizes options owned by the main parser before a subcommand.
    Keep one canonical global option while accepting the natural trailing form used
    by callers and documentation.
    """
    if "--apply" not in argv:
        return argv
    return ["--apply", *(argument for argument in argv if argument != "--apply")]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Session-close ceremony: mark session state and optionally archive."
    )
    parser.add_argument(
        "--brain-root",
        required=True,
        help="Vault root path.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write changes. Default is dry-run.",
    )
    parser.add_argument(
        "--cwd",
        default="",
        help="Session cwd used only to select an environment profile for the "
        "still-due-sources check (default: brain root). Never affects which "
        "sources are evaluated -- source ingestion is brain-scoped.",
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

    return parser.parse_args(normalize_apply_flag(sys.argv[1:]))


def find_session_note(brain_root: Path, session_id: str) -> Path | None:
    """Find a session note in WIP/SESSIONS/ whose filename contains session_id.

    When multiple notes match (e.g. same session spanning two days), prefer the
    most recent note whose status is active (open or handoff-only). Falls back to
    the most recent note overall if all are in terminal states.
    """
    session_dir = brain_root / "WIP" / "SESSIONS"
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


def find_archived_session_note(brain_root: Path, session_id: str) -> Path | None:
    trash_dir = brain_root / "QUARANTINE" / "TRASH"
    if not trash_dir.is_dir():
        return None
    matches = sorted(
        (path for path in trash_dir.glob("*.md") if session_id in path.name),
        reverse=True,
    )
    return matches[0] if matches else None


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


def _heading_section(text: str, heading: str) -> str | None:
    """Return the body of the block under `heading` (an exact stripped line match,
    e.g. '# Sessions' or '## Resume command'), or None if the note has none.

    Mirrors model_check_session_ownership.py's _ownership_block() heading-scope
    parsing: the block ends at the next heading of the same or higher level.
    """
    lines = text.splitlines()
    level = len(heading) - len(heading.lstrip("#"))
    for index, line in enumerate(lines):
        if line.strip() != heading:
            continue
        end = next(
            (
                cursor
                for cursor in range(index + 1, len(lines))
                if lines[cursor].startswith("#")
                and len(lines[cursor]) - len(lines[cursor].lstrip("#")) <= level
            ),
            len(lines),
        )
        return "\n".join(lines[index + 1 : end])
    return None


RESUME_ID_RE = re.compile(r"(?:--resume|--conversation|\bresume|(?<!\S)-s)\s+(\S+)")


def _split_unquoted(line: str, sep: str) -> str | None:
    """Return the text after the first `sep` that appears outside any quoted
    span, or None if `sep` never appears unquoted.

    session_digest.py's resume_command() always builds the recovery command as
    'cd {shlex.quote(cwd)} && <command>' -- shlex.quote() quotes the cwd whenever
    it contains a shell metacharacter, so a real '&&' separator is never itself
    inside quotes. But a plain, quote-unaware split on the first '&&' would still
    stop early if the quoted cwd's own text happens to contain that literal
    two-character sequence (e.g. a directory named '.../a&&resume project').
    """
    quote: str | None = None
    seplen = len(sep)
    for index, char in enumerate(line):
        if quote:
            if char == quote:
                quote = None
            continue
        if char in "'\"":
            quote = char
            continue
        if line[index : index + seplen] == sep:
            return line[index + seplen :]
    return None


def _command_after_cwd(text: str) -> str:
    """Drop a leading 'cd <dir> && ' prefix from each line before scanning for a
    resume verb. Every canonical recovery command has this shape (see
    RULES-SESSION-LIFECYCLE.common.md's "Session notes"); without stripping it, an
    arbitrary absolute cwd that happens to contain the literal word "resume"
    followed by whitespace (e.g. '/tmp/resume project') would match before the
    regex ever reaches the real '--resume <id>' flag later in the same line.
    """
    lines = []
    for line in text.splitlines():
        remainder = _split_unquoted(line, "&&")
        lines.append(remainder if remainder is not None else line)
    return "\n".join(lines)


def _bare_resume_id(section: str) -> str | None:
    """Fallback for a runtime with no known resume-command template.

    session_digest.py's resume_command() returns the bare session id itself
    (no verb, no 'cd ... &&' prefix at all) when the runtime isn't one of the
    ones with a known template (e.g. '--runtime generic'), matching this
    model's own documented "leave a clearly-marked placeholder... for other
    runtimes" fallback. If the whole '## Resume command' section is just one
    bulleted, backtick-quoted bare token, that token is the id.
    """
    lines = [line.strip() for line in section.splitlines() if line.strip()]
    if len(lines) != 1:
        return None
    candidate = lines[0].lstrip("-").strip().strip("`").strip()
    if candidate and " " not in candidate:
        return candidate
    return None


def resolve_full_session_id(note_path: Path, fallback: str) -> str:
    """Best-effort: extract the real full session id from the note's own
    '## Resume command' section (present in every real session note per
    RULES-SESSION-LIFECYCLE.common.md's "Session notes"), so a CLI-supplied
    unambiguous *prefix* still matches its own full-id registration in the
    journal exactly, instead of failing a whole-token match against a longer
    string. Falls back to the CLI-supplied value when no resume command is
    present (e.g. a minimal or hand-written note) rather than guessing.

    `fallback` is either the real id or a documented unambiguous prefix of it
    (find_session_note()'s own contract) -- the one thing already known for
    certain to identify this session. A candidate extracted from the note's
    prose that doesn't even start with it can't be this session's own
    registration (a stale or mismatched Resume command section, e.g.
    copy-pasted from a different note) and must not be trusted over the
    fallback.
    """
    try:
        text = note_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return fallback
    section = _heading_section(text, "## Resume command")
    if section is None:
        return fallback
    match = RESUME_ID_RE.search(_command_after_cwd(section))
    if match is not None:
        candidate = match.group(1).strip("`")
        return candidate if candidate.startswith(fallback) else fallback
    bare = _bare_resume_id(section)
    if bare is not None and bare.startswith(fallback):
        return bare
    return fallback


def find_journal_registration(brain_root: Path, session_id: str) -> Path | None:
    """Return the first daily note whose '# Sessions' block registers session_id
    as a whole token, or None.

    Verifies the consolidation checklist's "Session ID written in daily note" item
    against the actual daily notes on disk instead of trusting the session note's
    own self-reported checkbox. Scoped to the '# Sessions' block specifically (not
    the whole note) and matched on word boundaries -- a plain substring search
    would let "session-123" false-match inside an unrelated "session-1234", or
    inside a bare textual mention elsewhere in the day's prose. Discovers daily
    notes the same way session_open.py does (load_journal_folder() for a
    configured folder name, list_daily_notes()'s recursive rglob for notes
    archived under JOURNAL/<year>/ by yearly maintenance) instead of a hardcoded,
    non-recursive "JOURNAL/*.md" glob that would miss both.
    """
    try:
        journal_root = brain_root / load_journal_folder(brain_root)
    except JournalConfigError:
        return None
    if not journal_root.is_dir():
        return None
    pattern = re.compile(rf"(?<![\w-]){re.escape(session_id)}(?![\w-])")
    for path in list_daily_notes(journal_root):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        section = _heading_section(text, "# Sessions")
        if section is not None and pattern.search(section):
            return path
    return None


def archive_preflight(brain_root: Path, src: Path, dst: Path) -> tuple[bool, str]:
    """Refuse an archive that git cannot perform before mutating the note."""
    if dst.exists() or dst.is_symlink():
        return False, f"archive destination already exists: {dst.relative_to(brain_root)}"
    try:
        src_rel = src.relative_to(brain_root)
    except ValueError:
        return False, "session note is outside the brain repository"
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", str(src_rel)],
        cwd=brain_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return False, f"session note is not tracked by Git: {src_rel}"
    return True, ""


def git_mv(src: Path, dst: Path, brain_root: Path, apply: bool) -> bool:
    """Run git mv src dst. Return True on success."""
    src_rel = src.relative_to(brain_root)
    dst_rel = dst.relative_to(brain_root)
    cmd = ["git", "mv", str(src_rel), str(dst_rel)]
    if not apply:
        print(f"  would run: {' '.join(cmd)}")
        return True
    dst.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(cmd, cwd=brain_root, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        print(f"ERROR: git mv failed: {result.stderr.strip()}", file=sys.stderr)
        return False
    return True


def git_stage(path: Path, brain_root: Path, apply: bool) -> bool:
    """Stage path so the index contains its final working-tree content."""
    path_rel = path.relative_to(brain_root)
    cmd = ["git", "add", "--", str(path_rel)]
    if not apply:
        print(f"  would run: {' '.join(cmd)}")
        return True
    result = subprocess.run(cmd, cwd=brain_root, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        print(f"ERROR: git add failed: {result.stderr.strip()}", file=sys.stderr)
        return False
    return True


def main() -> int:
    args = parse_args()
    brain_root = Path(args.brain_root).expanduser().resolve()
    if not brain_root.is_dir():
        print(f"ERROR: vault root not found: {brain_root}", file=sys.stderr)
        return 1
    model_status = current_brain_status(brain_root)
    if model_status != "ok":
        print(
            "ERROR: brain root is not attached to the current agent-brain model "
            f"(status: {model_status}; expected: {current_model_root()}): {brain_root}",
            file=sys.stderr,
        )
        return 2

    cwd_arg: Path | None = None
    if args.cwd:
        try:
            cwd_arg = Path(args.cwd).expanduser().resolve()
        except (RuntimeError, OSError) as error:
            print(f"ERROR: invalid --cwd value: {args.cwd!r} ({error})", file=sys.stderr)
            return 1
        if not cwd_arg.is_dir():
            # Belt-and-suspenders past the try/except above: Python 3.14 changed
            # Path.resolve() to no longer raise on a symlink loop (verified
            # directly against a real loop on this machine), so a looping --cwd
            # would otherwise sail through as a "resolved" path that is not
            # actually a usable directory. is_dir() still correctly reports
            # False for it on every Python version, since the underlying stat()
            # call still fails with ELOOP regardless of resolve()'s own
            # raise-or-not behavior.
            print(f"ERROR: invalid --cwd value: {args.cwd!r} (not a directory)", file=sys.stderr)
            return 1

    mode = "apply" if args.apply else "dry-run"
    subcommand: str = args.subcommand
    session_id: str = args.session_id

    note_path = find_session_note(brain_root, session_id)
    if note_path is None:
        if subcommand == "consolidate" and args.archive:
            archived = find_archived_session_note(brain_root, session_id)
            if archived is not None and read_session_status(archived) == "consolidated":
                print("# Session close — consolidate")
                print(f"mode: {mode}")
                print(f"session_note: {archived.relative_to(brain_root)}")
                print("status: already consolidated and archived")
                return 0
        print(f"ERROR: session note not found for id '{session_id}'", file=sys.stderr)
        print(f"  searched in: {brain_root / 'WIP' / 'SESSIONS'}", file=sys.stderr)
        return 1

    current_status = read_session_status(note_path)
    if current_status is None:
        print(f"WARNING: could not read Status line from {note_path.name}")

    new_status = "handoff-only" if subcommand == "handoff" else "consolidated"
    already_target = current_status == new_status
    allowed_from = VALID_TRANSITIONS[subcommand]
    if current_status and not already_target and current_status not in allowed_from:
        print(f"ERROR: invalid state transition.", file=sys.stderr)
        print(f"  current status: {current_status}", file=sys.stderr)
        print(f"  '{subcommand}' requires status to be one of: {', '.join(allowed_from)}", file=sys.stderr)
        return 1

    note_rel = note_path.relative_to(brain_root)

    trash_dir = brain_root / "QUARANTINE" / "TRASH"
    archive_dst = trash_dir / note_path.name
    if subcommand == "consolidate" and args.archive:
        preflight_ok, preflight_error = archive_preflight(brain_root, note_path, archive_dst)
        if not preflight_ok:
            print(f"ERROR: {preflight_error}", file=sys.stderr)
            return 1

    # Compute both disk-verification checks before any mutation below. Reading
    # JOURNAL/*.md and WIP/SOURCES/ is fallible (a malformed daily, an unreadable
    # descriptor) -- if either raised here, previously, it did so *after*
    # patch_status() had already written "consolidated" to disk, crashing the
    # script with the note left half-closed and no rollback. Doing this first
    # means a failure here never leaves the note mutated.
    if subcommand == "consolidate":
        full_session_id = resolve_full_session_id(note_path, session_id)
        registration = find_journal_registration(brain_root, full_session_id)
        pending_sources = (
            summarize_due_sources(brain_root, date.today(), cwd_arg)
            if registry_activated(brain_root)
            else []
        )

    print(f"# Session close — {subcommand}")
    print(f"mode: {mode}")
    print(f"session_note: {note_rel}")
    print(f"status: {current_status} → {new_status}")
    print()

    original_text = note_path.read_text(encoding="utf-8")
    if already_target:
        print(f"  unchanged: Status already {new_status}")
    else:
        ok, old = patch_status(note_path, new_status, apply=args.apply)
        if ok:
            action = "updated" if args.apply else "would update"
            print(f"  {action}: Status: {old} → {new_status}")
        else:
            print(f"  ERROR patching status: {old}", file=sys.stderr)
            return 1

    if subcommand == "consolidate":
        if registration is not None:
            print(
                f"  verified: session id found in {registration.relative_to(brain_root)} "
                "(JOURNAL registration confirmed on disk)"
            )
        else:
            print(
                "  WARNING: session id not found in any JOURNAL/*.md daily note -- "
                "the 'Session ID written in daily note' consolidation-checklist item "
                "cannot be confirmed from disk; verify manually before archiving"
            )
        if pending_sources:
            print("  WARNING: source(s) need attention before consolidating (WIP/SOURCES/):")
            for line in pending_sources:
                print(f"  {line}")
        else:
            print("  verified: no sources are still due (checked against WIP/SOURCES/ on disk)")

        wip_changed = remove_wip_tag(note_path, apply=args.apply)
        if wip_changed:
            action = "removed" if args.apply else "would remove"
            print(f"  {action}: 'wip' tag from frontmatter")

        if args.archive:
            ok = git_mv(note_path, archive_dst, brain_root, apply=args.apply)
            if not ok:
                if args.apply and note_path.exists():
                    note_path.write_text(original_text, encoding="utf-8")
                    print("  rolled back session-note content after archive failure", file=sys.stderr)
                return 1
            staged = git_stage(archive_dst, brain_root, apply=args.apply)
            if not staged:
                if args.apply:
                    moved_back = git_mv(archive_dst, note_path, brain_root, apply=True)
                    rollback_path = note_path if moved_back else archive_dst
                    if rollback_path.exists():
                        rollback_path.write_text(original_text, encoding="utf-8")
                    if moved_back:
                        print(
                            "  rolled back session-note path and content after staging failure",
                            file=sys.stderr,
                        )
                    else:
                        print(
                            "  rollback incomplete after staging failure; original content was "
                            f"restored at {rollback_path.relative_to(brain_root)}",
                            file=sys.stderr,
                        )
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
