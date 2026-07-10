#!/usr/bin/env python3
"""Find notes in an Obsidian vault related to given keywords.

Usage:
    python3 find_related_notes.py --vault /path/to/vault --keywords "lerp example-co"
    python3 find_related_notes.py --vault /path/to/vault --keywords "lerp" --mode content

Modes:
    filename (default) — match note filenames (stem) against keywords (case-insensitive).
    content            — also match note contents via grep (slower, more thorough).

Output: JSON with keys:
    - vault: vault root path
    - keywords: list of keywords used
    - mode: search mode used
    - notes: list of note objects (see below)
    - count: number of notes found

Note object keys:
    - path: absolute path to the note file
    - relative_path: path relative to vault root
    - title: note filename without extension
    - match_source: "filename" or "content"
    - matched_keywords: list of keywords that matched this note
    - first_line: first non-empty, non-frontmatter line of the note (preview)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SKIP_DIRS = {
    ".git", ".obsidian", "node_modules", ".Trash", ".cache",
    "__pycache__", ".venv", "venv", "ATTACHMENTS", "QUARANTINE",
    "TEMPLATES",
}

FRONTMATTER_RE = re.compile(r"^---\s*$", re.MULTILINE)


def _in_skip_dir(path: Path, vault: Path) -> bool:
    """Check if any parent directory (between file and vault root) is in skip list."""
    try:
        rel = path.relative_to(vault)
    except ValueError:
        return True
    for part in rel.parts[:-1]:
        if part in SKIP_DIRS:
            return True
    return False


def filename_search(vault: Path, keywords: list[str]) -> list[dict]:
    """Search notes by filename matching."""
    results = []
    kw_lower = [k.lower() for k in keywords]

    for md_file in vault.rglob("*.md"):
        if _in_skip_dir(md_file, vault):
            continue

        stem = md_file.stem.lower()

        matched = []
        for kw in kw_lower:
            if kw in stem:
                matched.append(kw)

        if matched:
            results.append({
                "path": str(md_file),
                "relative_path": str(md_file.relative_to(vault)),
                "title": md_file.stem,
                "match_source": "filename",
                "matched_keywords": matched,
                "first_line": _first_content_line(md_file),
            })

    return results


def content_search(vault: Path, keywords: list[str]) -> list[dict]:
    """Search notes by content via grep."""
    results = []
    kw_lower = [k.lower() for k in keywords]
    seen_paths: dict[str, dict] = {}

    for md_file in vault.rglob("*.md"):
        if _in_skip_dir(md_file, vault):
            continue

        try:
            raw_text = md_file.read_text(encoding="utf-8", errors="ignore")
        except (OSError, UnicodeDecodeError):
            continue
        text_lower = raw_text.lower()

        matched = []
        for kw in kw_lower:
            if kw in text_lower:
                matched.append(kw)

        if matched:
            rel_path = str(md_file.relative_to(vault))
            seen_paths[rel_path] = {
                "path": str(md_file),
                "relative_path": rel_path,
                "title": md_file.stem,
                "match_source": "content",
                "matched_keywords": matched,
                "first_line": _first_content_line(md_file, raw_text),
            }

    results = list(seen_paths.values())
    return results


def _strip_frontmatter(text: str) -> str:
    """Strip a YAML frontmatter block only if it appears at the start of the file."""
    if not (text.startswith("---\n") or text.startswith("---\r\n")):
        return text
    end = FRONTMATTER_RE.search(text, 4)
    if end is None:
        return text
    return text[end.end():]


def _first_content_line(path: Path, text: str | None = None) -> str:
    """Return the first non-empty, non-frontmatter, non-HR line of a note as preview.

    Pass `text` to reuse an already-read file body and avoid a second read.
    """
    if text is None:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except (OSError, UnicodeDecodeError):
            return ""

    body = _strip_frontmatter(text)
    for line in body.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and stripped != "---":
            return stripped[:120]
    return ""


def merge_results(filename_notes: list[dict], content_notes: list[dict]) -> list[dict]:
    """Merge filename and content results, deduplicating by path."""
    by_path: dict[str, dict] = {}

    for note in filename_notes:
        by_path[note["relative_path"]] = note

    for note in content_notes:
        rel = note["relative_path"]
        if rel in by_path:
            existing = by_path[rel]
            existing_kws = set(existing["matched_keywords"])
            existing_kws.update(note["matched_keywords"])
            existing["matched_keywords"] = sorted(existing_kws)
            existing["match_source"] = "filename+content"
        else:
            by_path[rel] = note

    return sorted(by_path.values(), key=lambda n: n["relative_path"])


def main() -> int:
    parser = argparse.ArgumentParser(description="Find related notes in an Obsidian vault")
    parser.add_argument("--vault", required=True, help="Absolute path to the vault root")
    parser.add_argument("--keywords", required=True, help="Space-separated keywords to search for")
    parser.add_argument(
        "--mode",
        choices=["filename", "content", "both"],
        default="filename",
        help="Search mode: filename (default), content, or both",
    )
    args = parser.parse_args()

    vault = Path(args.vault).expanduser().resolve()
    if not vault.is_dir():
        print(json.dumps({
            "vault": str(vault),
            "keywords": args.keywords.split(),
            "mode": args.mode,
            "notes": [],
            "count": 0,
            "error": f"Vault path does not exist: {vault}",
        }))
        return 1

    keywords = args.keywords.split()

    filename_notes = []
    content_notes = []

    if args.mode in ("filename", "both"):
        filename_notes = filename_search(vault, keywords)

    if args.mode in ("content", "both"):
        content_notes = content_search(vault, keywords)

    if args.mode == "both":
        notes = merge_results(filename_notes, content_notes)
    elif args.mode == "content":
        notes = content_notes
    else:
        notes = filename_notes

    print(json.dumps({
        "vault": str(vault),
        "keywords": keywords,
        "mode": args.mode,
        "notes": notes,
        "count": len(notes),
    }, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
