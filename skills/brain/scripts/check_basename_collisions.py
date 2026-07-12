#!/usr/bin/env python3
"""Detect `*.md` basename collisions across the brain_root.

Same basename in different folders makes Obsidian's `[[wikilink]]` resolution
non-deterministic. This tool surfaces all collisions, counts incoming
`[[<stem>]]` references across `.md` and `.canvas` files, and proposes:

- If 0 incoming references → rename ALL instances (no canonical to preserve).
- If 1+ incoming references → canonical = oldest, rename the rest.

It does NOT execute renames. The user reviews, renames in Obsidian's UI
(which auto-updates wikilinks by path), and asks the agent for per-link
rewrite proposals where needed.

Always read-only. No `--apply` flag.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# Wikilink: `[[anything]]` with optional `!` embed prefix. Captures full
# inside content; post-processing extracts the path (strip alias `|`, anchor
# `#`, optional `.md`). Covers: `[[X]]`, `[[X|alias]]`, `[[X#h]]`, `[[X#^id]]`,
# `[[a/b/X]]`, `[[X.md]]`, `![[X]]`.
WIKILINK_RE = re.compile(r"!?\[\[([^\]\n]+?)\]\]")

# Markdown link: `[text](url)`. URL has no raw whitespace (Obsidian URL-encodes
# spaces as %20). Covers: `](X)`, `](X.md)`, `](a/b/X.md)`, `](X.md#h)`.
MDLINK_RE = re.compile(r"\]\(([^)\s\n]+)\)")

# Code spans: Obsidian does NOT resolve wikilinks or markdown links inside
# `inline` code or ```fenced``` code blocks. We strip them (replace with
# same-length spaces) before regex matching so line numbers stay aligned
# but documentary mentions of `[[name]]` syntax inside docs aren't counted
# as real refs.
# Matches a balanced inline-code span: N opening backticks (1+), content
# (any non-newline chars, non-greedy), exactly N closing backticks. This
# handles both `single` and ``double-backtick spans containing `single`
# backticks`` correctly.
INLINE_CODE_RE = re.compile(r"(`+)[^\n]*?\1")
FENCED_CODE_RE = re.compile(r"```.*?```", re.DOTALL)


def strip_code_spans(text: str) -> str:
    """Replace inline-code and fenced-code spans with same-length spaces.

    Preserves total length and line breaks so any post-match line-number
    arithmetic remains correct. Note: this is a heuristic — pathological
    nesting (e.g. unmatched backticks across many lines) may not be handled
    perfectly, but the common cases (single backticks inline, triple
    backticks fenced) are.
    """
    def to_spaces(m: re.Match) -> str:
        s = m.group(0)
        return "".join("\n" if c == "\n" else " " for c in s)
    text = FENCED_CODE_RE.sub(to_spaces, text)
    text = INLINE_CODE_RE.sub(to_spaces, text)
    return text

# File extensions that may contain `[[wikilinks]]` or `]( )` markdown links.
# Canvas files are JSON but their text nodes use raw markdown/wikilink syntax.
LINK_BEARING_EXTS = (".md", ".canvas")


def walk_files(brain_root: Path, exclude_paths: list[Path]) -> list[Path]:
    """Yield files under visible non-symlinked top-level dirs.

    Mirrors `cleanup_ds_store.py`'s containment model: dotfile dirs and
    top-level symlinks (e.g. `_COMMON` → vault-common checkout) are skipped.
    Caller filters by suffix.

    `exclude_paths` are absolute paths (already resolved); anything under
    one of them is skipped.
    """
    found: list[Path] = []

    def is_excluded(p: Path) -> bool:
        for ex in exclude_paths:
            try:
                if p.is_relative_to(ex):
                    return True
            except (ValueError, AttributeError):
                # Path.is_relative_to is 3.9+; AttributeError fallback below
                if str(p).startswith(str(ex) + "/") or str(p) == str(ex):
                    return True
        return False

    try:
        top_entries = list(brain_root.iterdir())
    except OSError:
        return found
    for top in top_entries:
        try:
            if top.is_symlink():
                continue
            if top.is_dir():
                if top.name.startswith("."):
                    continue
                for path in top.rglob("*"):
                    try:
                        if not (path.is_file() and not path.is_symlink()):
                            continue
                        if is_excluded(path):
                            continue
                        found.append(path)
                    except OSError:
                        continue
            elif top.is_file():
                if not is_excluded(top):
                    found.append(top)
        except OSError:
            continue
    return found


REF_KINDS = ("wl_bare", "wl_path", "md_bare", "md_path")

# Human-readable labels for the four reference kinds — used in user-visible
# output (report headers, per-file breakdowns, legend). Internal code keeps
# the short identifiers as dict keys / variable names; only the printed
# output uses these labels.
REF_KIND_LABELS = {
    "wl_bare": "wikilink-simple",
    "wl_path": "wikilink-path",
    "md_bare": "markdown-simple",
    "md_path": "markdown-path",
}


def _normalize_ref(raw: str, kind: str) -> str | None:
    """Strip alias/anchor/`.md` extension and URL-decode (markdown links).
    Returns the cleaned path-or-stem; None if the ref points to no file
    (e.g. `[[#anchor]]`, `[[##]]`, `[[^^block]]`).
    """
    s = raw.strip()
    if kind == "wikilink":
        # Drop alias
        s = s.split("|", 1)[0]
        # Drop anchor (handles both `#h` and `#^block-id` and `##search`)
        s = s.split("#", 1)[0]
    else:  # mdlink
        s = s.split("#", 1)[0]
        try:
            from urllib.parse import unquote
            s = unquote(s)
        except Exception:
            pass
    s = s.strip()
    if not s:
        return None
    if s.startswith("^"):  # `[[^^block]]` style — no file basename
        return None
    if s.endswith(".md"):
        s = s[:-3]
    return s if s else None


def extract_refs(text: str) -> list[tuple[str, str]]:
    """Return all references as (kind, normalized_path) where kind is
    'wikilink' or 'mdlink' and normalized_path has no `.md`, no alias,
    no anchor.
    """
    refs: list[tuple[str, str]] = []
    for m in WIKILINK_RE.finditer(text):
        norm = _normalize_ref(m.group(1), "wikilink")
        if norm is not None:
            refs.append(("wikilink", norm))
    for m in MDLINK_RE.finditer(text):
        norm = _normalize_ref(m.group(1), "mdlink")
        if norm is not None:
            refs.append(("mdlink", norm))
    return refs


def count_incoming_refs(
    files: list[Path], target_stems: set[str]
) -> dict[str, dict[str, int]]:
    """Single-pass scan of `.md` + `.canvas`. For each reference whose
    basename is in `target_stems`, increment the matching counter:

    - `wl_bare`  : `[[stem]]` (no path)
    - `wl_path`  : `[[a/b/stem]]` (path-qualified wikilink)
    - `md_bare`  : `](stem)` or `](stem.md)` (markdown link, bare basename)
    - `md_path`  : `](a/b/stem.md)` (markdown link with path)

    Self-references are included; Obsidian counts them as backlinks too.
    """
    counts: dict[str, dict[str, int]] = {
        stem: {k: 0 for k in REF_KINDS} for stem in target_stems
    }
    for path in files:
        if path.suffix not in LINK_BEARING_EXTS:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        text = strip_code_spans(text)
        for kind, norm in extract_refs(text):
            if "/" in norm:
                stem = norm.rsplit("/", 1)[-1]
                qualifier = "path"
            else:
                stem = norm
                qualifier = "bare"
            if stem in counts:
                key = ("wl_" if kind == "wikilink" else "md_") + qualifier
                counts[stem][key] += 1
    return counts


def git_creation_iso(brain_root: Path, path: Path) -> str | None:
    """ISO timestamp of the first commit adding this path; None if untracked."""
    try:
        rel = path.relative_to(brain_root)
    except ValueError:
        return None
    try:
        result = subprocess.run(
            [
                "git", "-C", str(brain_root), "log",
                "--diff-filter=A", "--reverse", "--format=%cI",
                "--", str(rel),
            ],
            capture_output=True, text=True, check=False, timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    output = result.stdout.strip()
    if not output:
        return None
    return output.splitlines()[0]


def fs_birth_iso(path: Path) -> str:
    """Filesystem birth-time (macOS) or ctime as ISO."""
    st = path.stat()
    epoch = getattr(st, "st_birthtime", st.st_ctime)
    return datetime.fromtimestamp(epoch).isoformat()


def depth(brain_root: Path, path: Path) -> int:
    """Folder depth from vault root. File at root = 0; under `WIP/` = 1; etc."""
    try:
        return len(path.relative_to(brain_root).parts) - 1
    except ValueError:
        return -1


def parent_slug(path: Path) -> str:
    """Slug from the parent folder name. Lowercase, non-alnum → `-`, collapsed."""
    name = path.parent.name
    slug = "".join(c if c.isalnum() or c in "-_" else "-" for c in name).lower()
    slug = "-".join(filter(None, slug.split("-")))
    return slug or "root"


def suggested_new_basename(path: Path) -> str:
    """`<parent-slug>.<stem>.md`"""
    return f"{parent_slug(path)}.{path.stem}{path.suffix}"


def resolve_exclude_paths(brain_root: Path, raw_paths: list[str]) -> list[Path]:
    """Convert user-supplied `--exclude-path` values (relative to vault or
    absolute) into absolute Paths. Non-existent paths are kept (allows
    pre-emptive exclusion of paths that don't exist in every vault)."""
    resolved: list[Path] = []
    for raw in raw_paths:
        p = Path(raw)
        if not p.is_absolute():
            p = brain_root / p
        resolved.append(p.resolve(strict=False))
    return resolved


def attribute_ref_to_group_file(
    ref_file: Path,
    normalized_ref: str,
    group_files: list[Path],
    brain_root: Path,
) -> Path | None:
    """Try to identify which file in group_files the reference targets.

    Resolution strategy:
    - Path-qualified ref starting with `./` or `../`: resolve relative to
      ref_file's parent; match group_files by resolved path.
    - Other path-qualified refs: try vault-root + ref + .md; otherwise
      suffix-match (`endswith("/<ref>.md")`) within group_files.
    - Bare ref: assume same-folder resolution (Obsidian default) — match a
      group file in `ref_file.parent`.

    Returns the matching `Path` (one of `group_files`) or `None` when
    unresolved or ambiguous. Ambiguous matches deliberately return None to
    avoid silently attributing a ref to the wrong target.
    """
    target_filename = normalized_ref + ".md"

    if "/" in normalized_ref:
        if normalized_ref.startswith(".") or normalized_ref.startswith(".."):
            try:
                resolved = (ref_file.parent / target_filename).resolve()
            except (OSError, RuntimeError):
                return None
            for gf in group_files:
                try:
                    if gf.resolve() == resolved:
                        return gf
                except OSError:
                    continue
            return None
        # Vault-relative or path-suffix
        vault_candidate = (brain_root / target_filename).resolve()
        for gf in group_files:
            try:
                if gf.resolve() == vault_candidate:
                    return gf
            except OSError:
                continue
        # Path-suffix match
        suffix = "/" + target_filename
        matches = [gf for gf in group_files if str(gf).endswith(suffix)]
        if len(matches) == 1:
            return matches[0]
        return None
    # Bare ref — same-folder heuristic
    candidate = ref_file.parent / target_filename
    for gf in group_files:
        if gf == candidate:
            return gf
    return None


def count_refs_per_file(
    files: list[Path],
    duplicates: dict[str, list[Path]],
    brain_root: Path,
) -> dict[Path, dict[str, int]]:
    """Per-file attribution counter. For each duplicate-group file, returns
    counters of refs (by kind) that resolve to THIS specific file.

    Refs that cannot be unambiguously resolved are NOT attributed to any
    file — they remain "ambiguous" and only show up in the group-level
    counters via `count_incoming_refs`.
    """
    # Build a quick lookup: stem → group_files
    stem_to_group: dict[str, list[Path]] = {
        Path(bn).stem: paths for bn, paths in duplicates.items()
    }
    counts: dict[Path, dict[str, int]] = {}
    for group_files in duplicates.values():
        for f in group_files:
            counts[f] = {k: 0 for k in REF_KINDS}

    for ref_file in files:
        if ref_file.suffix not in LINK_BEARING_EXTS:
            continue
        try:
            text = ref_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        text = strip_code_spans(text)
        for m in WIKILINK_RE.finditer(text):
            norm = _normalize_ref(m.group(1), "wikilink")
            if norm is None:
                continue
            stem = norm.rsplit("/", 1)[-1] if "/" in norm else norm
            if stem not in stem_to_group:
                continue
            target = attribute_ref_to_group_file(
                ref_file, norm, stem_to_group[stem], brain_root
            )
            if target is None:
                continue
            qualifier = "path" if "/" in norm else "bare"
            counts[target]["wl_" + qualifier] += 1
        for m in MDLINK_RE.finditer(text):
            norm = _normalize_ref(m.group(1), "mdlink")
            if norm is None:
                continue
            stem = norm.rsplit("/", 1)[-1] if "/" in norm else norm
            if stem not in stem_to_group:
                continue
            target = attribute_ref_to_group_file(
                ref_file, norm, stem_to_group[stem], brain_root
            )
            if target is None:
                continue
            qualifier = "path" if "/" in norm else "bare"
            counts[target]["md_" + qualifier] += 1
    return counts


def find_refs_to_stem(
    files: list[Path], target_stem: str
) -> dict[str, list[tuple[Path, int, str]]]:
    """Return references to `target_stem` categorized by kind. Reuses the
    same WIKILINK_RE / MDLINK_RE / normalization as the counter — single
    source of truth for what counts as a reference.

    Returns `{kind: [(path, line_no, line_content), ...]}` keyed by REF_KINDS.
    """
    by_kind: dict[str, list[tuple[Path, int, str]]] = {k: [] for k in REF_KINDS}
    for path in files:
        if path.suffix not in LINK_BEARING_EXTS:
            continue
        try:
            raw_text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        # `text` is the code-stripped version (used for regex scanning),
        # `raw_lines` keeps the original line content for human-readable
        # display.
        text = strip_code_spans(raw_text)
        lines = raw_text.split("\n")

        def line_no_at(offset: int) -> int:
            return text.count("\n", 0, offset) + 1

        for m in WIKILINK_RE.finditer(text):
            norm = _normalize_ref(m.group(1), "wikilink")
            if norm is None:
                continue
            stem = norm.rsplit("/", 1)[-1] if "/" in norm else norm
            qualifier = "path" if "/" in norm else "bare"
            if stem != target_stem:
                continue
            ln = line_no_at(m.start())
            by_kind["wl_" + qualifier].append((path, ln, lines[ln - 1].rstrip()))
        for m in MDLINK_RE.finditer(text):
            norm = _normalize_ref(m.group(1), "mdlink")
            if norm is None:
                continue
            stem = norm.rsplit("/", 1)[-1] if "/" in norm else norm
            qualifier = "path" if "/" in norm else "bare"
            if stem != target_stem:
                continue
            ln = line_no_at(m.start())
            by_kind["md_" + qualifier].append((path, ln, lines[ln - 1].rstrip()))
    return by_kind


def is_inside_git_repo(path: Path) -> bool:
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True, check=False, timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and result.stdout.strip() == "true"


def git_mv(brain_root: Path, src: Path, dst: Path) -> tuple[bool, str]:
    """Run `git -C vault mv src dst`. Returns (ok, message)."""
    try:
        result = subprocess.run(
            ["git", "-C", str(brain_root), "mv", str(src), str(dst)],
            capture_output=True, text=True, check=False, timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return (False, f"subprocess error: {exc}")
    if result.returncode != 0:
        return (False, result.stderr.strip() or result.stdout.strip())
    return (True, "")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Detect *.md basename collisions across the brain_root."
    )
    parser.add_argument("--brain-root", required=True, help="Path to the vault root.")
    parser.add_argument(
        "--exclude-path",
        action="append",
        default=[],
        metavar="PATH",
        help=(
            "Path (relative to --brain-root, or absolute) to exclude from the scan. "
            "Repeatable. Use to skip subtrees owned by external runtimes (e.g. "
            "`_AGENTS/CLAUDE/memory` — files there are governed by CLAUDE.md, "
            "renaming breaks the runtime). Excluded files are also ignored when "
            "counting incoming references."
        ),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Auto-rename groups whose ALL FOUR ref counters (wl_bare, wl_path, "
            "md_bare, md_path) are zero. Groups with any reference are skipped "
            "and require interactive review. Renames use `git mv` when the vault "
            "is a git repo, plain `mv` otherwise."
        ),
    )
    parser.add_argument(
        "--show-refs",
        metavar="BASENAME",
        help=(
            "Instead of the collision report, list all references to BASENAME "
            "(with or without .md). Output is `file:line` + line content, "
            "categorized by the 4 ref kinds. Uses the same patterns as the "
            "internal counter — single source of truth for the interactive "
            "review workflow."
        ),
    )
    args = parser.parse_args()

    brain_root = Path(args.brain_root).expanduser().resolve()
    if not brain_root.is_dir():
        print(f"ERROR: brain root not found: {brain_root}", file=sys.stderr)
        return 1

    exclude_paths = resolve_exclude_paths(brain_root, args.exclude_path)
    use_git = is_inside_git_repo(brain_root)

    all_files = walk_files(brain_root, exclude_paths)
    md_files = [f for f in all_files if f.suffix == ".md"]

    # --show-refs short-circuits before the collision report.
    if args.show_refs:
        target = args.show_refs
        if target.endswith(".md"):
            target = target[:-3]
        by_kind = find_refs_to_stem(all_files, target)
        total = sum(len(refs) for refs in by_kind.values())
        print(f"# References to `{target}` (basename `{target}.md`)")
        print(f"brain_root: {brain_root}")
        if exclude_paths:
            print("excluded:")
            for ex in exclude_paths:
                try:
                    print(f"  - {ex.relative_to(brain_root)}")
                except ValueError:
                    print(f"  - {ex}")
        print(f"link-bearing files scanned (md + canvas): {len(all_files)}")
        print(f"total references: {total}")
        print()
        if total == 0:
            print("No references found.")
            return 0
        for kind in REF_KINDS:
            refs = by_kind[kind]
            if not refs:
                continue
            label = {
                "wl_bare": f"`[[{target}]]` (and variants)",
                "wl_path": f"`[[*/{target}]]` (path-qualified wikilink)",
                "md_bare": f"`]({target}.md)` (markdown link, no path)",
                "md_path": f"`](*/{target}.md)` (markdown link with path)",
            }[kind]
            print(f"## {REF_KIND_LABELS[kind]} — {label} · {len(refs)} occurrence(s)")
            for path, line_no, content in sorted(refs, key=lambda t: (str(t[0]), t[1])):
                try:
                    rel = path.relative_to(brain_root)
                except ValueError:
                    rel = path
                print(f"  - {rel}:{line_no}")
                print(f"      {content.strip()}")
            print()
        return 0

    by_basename: dict[str, list[Path]] = defaultdict(list)
    for f in md_files:
        by_basename[f.name].append(f)
    duplicates = {bn: paths for bn, paths in by_basename.items() if len(paths) > 1}

    target_stems = {Path(bn).stem for bn in duplicates.keys()}
    incoming = count_incoming_refs(all_files, target_stems)
    per_file = count_refs_per_file(all_files, duplicates, brain_root)

    print("# Basename collisions report")
    print(f"brain_root: {brain_root}")
    if exclude_paths:
        print("excluded:")
        for ex in exclude_paths:
            try:
                rel = ex.relative_to(brain_root)
                print(f"  - {rel}")
            except ValueError:
                print(f"  - {ex}")
    print(f"mode: {'apply' if args.apply else 'dry-run'}")
    print(f"git: {'available' if use_git else 'not detected — would use plain mv on --apply'}")
    print(f"total *.md scanned: {len(md_files)}")
    print(f"link-bearing files scanned (md + canvas): {len(all_files)}")
    print(f"distinct basenames: {len(by_basename)}")
    print(f"basenames with duplicates: {len(duplicates)}")
    total_dupes = sum(len(p) for p in duplicates.values())
    print(f"total files in duplicate groups: {total_dupes}")
    print()

    if not duplicates:
        print("No collisions found.")
        return 0

    # Track apply results
    applied = 0
    apply_failures: list[tuple[Path, Path, str]] = []
    safe_groups = 0
    interactive_groups = 0

    for basename, paths in sorted(
        duplicates.items(), key=lambda kv: (-len(kv[1]), kv[0])
    ):
        stem = Path(basename).stem
        c = incoming.get(stem, {k: 0 for k in REF_KINDS})
        total = sum(c.values())
        kinds_str = " ".join(f"{REF_KIND_LABELS[k]}={c[k]}" for k in REF_KINDS)
        print(f"## `{basename}` — {len(paths)} instances · references: {kinds_str} (total={total})")

        annotated: list[tuple[Path, Path, str, int]] = []
        for p in paths:
            iso = git_creation_iso(brain_root, p) or fs_birth_iso(p)
            d = depth(brain_root, p)
            try:
                rel = p.relative_to(brain_root)
            except ValueError:
                rel = p
            annotated.append((p, rel, iso, d))
        annotated.sort(key=lambda t: (t[2], t[3], str(t[1])))

        if total == 0:
            safe_groups += 1
            print("  No incoming references found — safe to rename ALL.")
            for p, rel, iso, d in annotated:
                print(f"   - {rel}   (created={iso[:10]}, depth={d})")
            for p, rel, iso, d in annotated:
                new_name = suggested_new_basename(p)
                dst = p.parent / new_name
                try:
                    new_rel = dst.relative_to(brain_root)
                except ValueError:
                    new_rel = dst
                if args.apply:
                    if dst.exists():
                        print(f"    SKIP rename (target exists): {rel} → {new_rel}")
                        apply_failures.append((p, dst, "target exists"))
                        continue
                    if use_git:
                        ok, err = git_mv(brain_root, p, dst)
                    else:
                        try:
                            p.rename(dst)
                            ok, err = True, ""
                        except OSError as exc:
                            ok, err = False, str(exc)
                    if ok:
                        applied += 1
                        print(f"    RENAMED: {rel} → {new_rel}")
                    else:
                        apply_failures.append((p, dst, err))
                        print(f"    FAILED:  {rel} → {new_rel}  ({err})")
                else:
                    print(f"    → would rename: {rel} → {new_rel}")
        else:
            interactive_groups += 1
            canonical = annotated[0]
            attributed_total = sum(
                sum(per_file[p].values()) for p, _, _, _ in annotated
            )
            unresolved = total - attributed_total
            print(
                f"  Per-file attribution: {attributed_total}/{total} refs resolved"
                + (
                    f" ({unresolved} ambiguous — bare refs whose same-folder resolution does not land on a file in this group)"
                    if unresolved
                    else ""
                )
            )

            # Partition. Files with per-file count > 0 need edits before rename.
            # Files with 0 → "auto-safe". If unresolved bare refs exist, one
            # auto-safe file must remain unrenamed to preserve their resolution.
            auto_safe = [a for a in annotated if sum(per_file[a[0]].values()) == 0]
            needs_edits = [a for a in annotated if sum(per_file[a[0]].values()) > 0]
            preservation_target: tuple[Path, Path, str, int] | None = None
            if unresolved > 0 and auto_safe:
                preservation_target = auto_safe[0]  # oldest auto-safe

            preservation_msg = ""
            if preservation_target is not None:
                preservation_msg = (
                    f"  Preserving `{preservation_target[1]}` (oldest auto-safe) "
                    f"to anchor {unresolved} unresolved bare ref(s)."
                )
                print(preservation_msg)
            elif unresolved > 0 and not auto_safe:
                print(
                    f"  WARNING: {unresolved} unresolved bare ref(s) and no auto-safe file to anchor them."
                )

            for p, rel, iso, d in annotated:
                tag = "  Canonical" if (p, rel) == (canonical[0], canonical[1]) else "  "
                pf = per_file[p]
                pf_total = sum(pf.values())
                pf_str = " ".join(f"{REF_KIND_LABELS[k]}={pf[k]}" for k in REF_KINDS if pf[k])
                is_preserved = (
                    preservation_target is not None
                    and (p, rel) == (preservation_target[0], preservation_target[1])
                )
                if is_preserved:
                    marker = "  ← preserved (anchors ambiguous bare refs)"
                elif pf_total == 0:
                    marker = "  ← per-file safe"
                else:
                    marker = ""
                pf_label = (
                    f"refs→here: {pf_total} ({pf_str})"
                    if pf_total
                    else f"refs→here: 0{marker}"
                )
                print(f"{tag} - {rel}   (created={iso[:10]}, depth={d})  · {pf_label}")

            # Renames: auto_safe minus preservation_target; needs_edits printed as manual.
            renamable = [a for a in auto_safe if a is not preservation_target]
            for p, rel, iso, d in renamable:
                new_name = suggested_new_basename(p)
                dst = p.parent / new_name
                try:
                    new_rel = dst.relative_to(brain_root)
                except ValueError:
                    new_rel = dst
                if args.apply:
                    if dst.exists():
                        print(f"    SKIP rename (target exists): {rel} → {new_rel}")
                        apply_failures.append((p, dst, "target exists"))
                        continue
                    if use_git:
                        ok, err = git_mv(brain_root, p, dst)
                    else:
                        try:
                            p.rename(dst)
                            ok, err = True, ""
                        except OSError as exc:
                            ok, err = False, str(exc)
                    if ok:
                        applied += 1
                        print(f"    RENAMED (auto-safe): {rel} → {new_rel}")
                    else:
                        apply_failures.append((p, dst, err))
                        print(f"    FAILED:  {rel} → {new_rel}  ({err})")
                else:
                    print(f"    → would rename (auto-safe): {rel} → {new_rel}")
            for p, rel, iso, d in needs_edits:
                new_name = suggested_new_basename(p)
                try:
                    new_rel = p.parent.relative_to(brain_root) / new_name
                except ValueError:
                    new_rel = Path(p.parent) / new_name
                print(f"    → suggest rename (needs edits): {rel} → {new_rel}")
        print()

    print("---")
    print("Summary")
    print(f"  safe groups (all 4 counters = 0): {safe_groups}")
    print(f"  interactive groups (>= 1 ref): {interactive_groups}")
    if args.apply:
        print(f"  files renamed: {applied}")
        if apply_failures:
            print(f"  failures: {len(apply_failures)}")
            for src, dst, err in apply_failures:
                print(f"    - {src.name}: {err}")
    print()
    print("Reference kinds (labels used in the report):")
    print("  wikilink-simple  : `[[stem]]`, `[[stem|alias]]`, `[[stem#heading]]`, `![[stem]]`")
    print("  wikilink-path    : `[[a/b/stem]]` and variants — wikilink with path qualifier")
    print("  markdown-simple  : `[text](stem)` or `[text](stem.md)` — markdown link, no path")
    print("  markdown-path    : `[text](a/b/stem.md)` and variants — markdown link with path")
    print()
    print("Interactive review (for groups with total > 0):")
    print("  Ask the agent: \"For group `<basename>`, grep references with context")
    print("   and propose per-link rewrites — which version each ref should point to.\"")
    print("  The agent reads each match in context, suggests rewrites, you confirm,")
    print("  it applies (Edit on each referencing file + git mv for the file itself).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
