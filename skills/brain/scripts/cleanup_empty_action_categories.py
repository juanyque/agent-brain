#!/usr/bin/env python3
"""Remove empty placeholder action categories from daily notes.

Daily notes created from `TEMPLATE.daily-note.common.md` ship with placeholder
action categories (`* [[LEARN]]:`, `* [[READ]]:`, etc.). At end-of-day cleanup
the unused ones should be removed while preserving categories with real
content. Some categories (`OBJECTIVES`, `WORK`) ship with placeholder children
that are themselves scaffolding (`[[Objective from WIP/OBJECTIVES.md]] — ...`,
`[[Project or context]] <!-- ... -->`, `Detailed work performed ...`); those
count as empty for removal purposes (placeholder-only mode).

Dry-run by default. Pass `--apply` to write changes. Files without a
`# Actions` section (legacy daily shape, non-daily notes) are skipped.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

STATUS_OPEN_RE = re.compile(r"^-\s+Status:\s*open\s*$", re.IGNORECASE)

# Top-level action bullet: `* [[NAME]]:` followed by optional trailing whitespace.
CATEGORY_RE = re.compile(r"^\*\s+\[\[([\w-]+)\]\]:\s*$")

# Indented child bullet under a category (`-` or `*`).
CHILD_BULLET_RE = re.compile(r"^\s+[-*]\s+\S")

# Known placeholder substrings per category. Substring match (not exact line)
# to tolerate trailing whitespace and minor edits. Extend in place when the
# template grows new scaffolding lines.
PLACEHOLDER_SUBSTRINGS = {
    "OBJECTIVES": [
        "[[Objective from WIP/OBJECTIVES.md]]",
    ],
    "WORK": [
        "[[Project or context]]",
        "Detailed work performed for that project/context today",
    ],
}


def is_placeholder_child(category: str, line: str) -> bool:
    for needle in PLACEHOLDER_SUBSTRINGS.get(category, []):
        if needle in line:
            return True
    return False


def clean_actions_section(
    lines: list[str],
) -> tuple[list[str], list[tuple[str, str]]]:
    """Return (cleaned_lines, removed_categories).

    Walks the file; while inside `# Actions`, drops each top-level category
    whose child block is empty or contains only known placeholders. Preserves
    everything else byte-for-byte (frontmatter, # Sessions, other sections,
    nav links, trailing newline).
    """
    out: list[str] = []
    removed: list[tuple[str, str]] = []
    in_actions = False
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]
        stripped = line.rstrip("\n")

        if not in_actions:
            out.append(line)
            if stripped.startswith("# Actions"):
                in_actions = True
            i += 1
            continue

        # End of Actions: next top-level (`# `) header that is not `# Actions`.
        if stripped.startswith("# ") and not stripped.startswith("# Actions"):
            in_actions = False
            out.append(line)
            i += 1
            continue

        m = CATEGORY_RE.match(stripped)
        if not m:
            out.append(line)
            i += 1
            continue

        category = m.group(1)
        # Gather contiguous indented child lines (stop at blank, non-child, or EOF).
        j = i + 1
        children: list[str] = []
        while j < n:
            cs = lines[j].rstrip("\n")
            if cs.strip() == "":
                break
            if CHILD_BULLET_RE.match(cs):
                children.append(cs)
                j += 1
                continue
            break

        real = [c for c in children if not is_placeholder_child(category, c)]
        if not children:
            removed.append((category, "no children"))
            i += 1
            continue
        if not real:
            removed.append((category, f"placeholder-only ({len(children)} child line(s))"))
            i = j
            continue

        # Keep category + all its original child lines verbatim.
        out.append(line)
        for k in range(i + 1, j):
            out.append(lines[k])
        i = j

    return out, removed


def process_file(path: Path, apply: bool) -> tuple[bool, list[tuple[str, str]]]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"  WARNING: read failed for {path}: {exc}", file=sys.stderr)
        return (False, [])
    if "# Actions" not in text:
        return (False, [])
    lines = text.splitlines(keepends=True)
    cleaned, removed = clean_actions_section(lines)
    if not removed:
        return (False, [])
    if apply:
        try:
            path.write_text("".join(cleaned), encoding="utf-8")
        except OSError as exc:
            print(f"  WARNING: write failed for {path}: {exc}", file=sys.stderr)
            return (False, removed)
    return (True, removed)


def has_open_session_for_date(vault_root: Path, date_str: str) -> list[str]:
    """Return list of open session note paths (relative) whose filename date matches date_str."""
    session_dir = vault_root / "WIP" / "SESSIONS"
    if not session_dir.exists():
        return []
    open_notes: list[str] = []
    for note in session_dir.glob(f"{date_str}-session-*.md"):
        try:
            text = note.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            if STATUS_OPEN_RE.match(line.strip()):
                open_notes.append(str(note.relative_to(vault_root)))
                break
    return open_notes


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Remove empty placeholder action categories from daily notes."
    )
    parser.add_argument("--vault-root", required=True, help="Path to the vault root.")
    parser.add_argument(
        "--journal-subdir",
        default="JOURNAL",
        help="Journal subdir under --vault-root (default: JOURNAL).",
    )
    parser.add_argument(
        "--glob",
        default="**/*.md",
        help="Glob (under journal-subdir) matching daily notes (default: **/*.md).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write changes. Default is dry-run.",
    )
    parser.add_argument(
        "--skip-if-open-sessions",
        action="store_true",
        help=(
            "Refuse to clean a daily note if it has open session notes pending consolidation. "
            "Checks WIP/SESSIONS/<date>-session-*.md for Status: open. "
            "When open sessions are found, exits with code 2 and prints which notes block the cleanup."
        ),
    )
    args = parser.parse_args()

    vault = Path(args.vault_root).expanduser().resolve()
    if not vault.is_dir():
        print(f"ERROR: vault root not found: {vault}", file=sys.stderr)
        return 1
    journal = vault / args.journal_subdir
    if not journal.is_dir():
        print(f"ERROR: journal dir not found: {journal}", file=sys.stderr)
        return 1

    files = sorted(p for p in journal.glob(args.glob) if p.is_file() and p.suffix == ".md")

    if args.skip_if_open_sessions:
        import re as _re
        date_pat = _re.compile(r"^(\d{4}-\d{2}-\d{2})")
        blocked: list[tuple[str, list[str]]] = []
        for f in files:
            m = date_pat.match(f.name)
            if not m:
                continue
            date_str = m.group(1)
            open_notes = has_open_session_for_date(vault, date_str)
            if open_notes:
                blocked.append((str(f.relative_to(vault)), open_notes))
        if blocked:
            print("ERROR: --skip-if-open-sessions: refusing to clean the following daily notes", file=sys.stderr)
            print("because they have open session notes pending consolidation:", file=sys.stderr)
            for daily_rel, notes in blocked:
                print(f"  {daily_rel}", file=sys.stderr)
                for note in notes:
                    print(f"    open session: {note}", file=sys.stderr)
            print(file=sys.stderr)
            print("Consolidate or close those sessions first, then re-run.", file=sys.stderr)
            return 2

    print("# Cleanup empty action categories")
    print(f"mode: {'apply' if args.apply else 'dry-run'}")
    print(f"vault: {vault}")
    print(f"scanning: {journal}  (glob: {args.glob})")
    print()

    changed_count = 0
    total_removed = 0
    for f in files:
        changed, removed = process_file(f, args.apply)
        if not changed:
            continue
        changed_count += 1
        total_removed += len(removed)
        try:
            rel = f.relative_to(vault)
        except ValueError:
            rel = f
        label = "updated" if args.apply else "would update"
        print(f"  {label}: {rel}")
        for cat, reason in removed:
            print(f"    - {cat}: {reason}")

    print()
    if not changed_count:
        print("  no daily notes needed cleanup")
    elif args.apply:
        print(f"  cleaned {changed_count} file(s); removed {total_removed} empty categor(ies)")
    else:
        print(f"  (dry-run: would clean {changed_count} file(s); {total_removed} empty categor(ies))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
