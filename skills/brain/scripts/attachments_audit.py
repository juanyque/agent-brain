#!/usr/bin/env python3

"""
Audit and optionally relocate attachments from all ATTACHMENTS folders under a root path.

Design goals:
- safe by default (dry-run unless --apply)
- never delete anything
- classify conflicts explicitly instead of guessing
- print to console and always write the latest run to a sibling .log file
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from pathlib import Path
from re import Pattern, compile as re_compile

from _common import Reporter, build_command_string
from attachment_destinations import (
    AttachmentDestinationError,
    collision_key,
    flat_attachment_shape,
    require_flat_attachment_destination,
)

WIKILINK_SPAN_RE: Pattern[str] = re_compile(r"\[\[.*?\]\]")
MOVE_CANDIDATE_STATUSES = frozenset({"ORPHAN_CANDIDATE", "RELOCATE_CANDIDATE"})


@dataclass(frozen=True, slots=True)
class AttachmentReport:
    attachment: Path
    status: str
    references: list[Path]
    proposed_destination: Path | None
    note: str
    plain_mentions: tuple[Path, ...] = ()

def is_git_repo(brain_root: Path) -> bool:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=brain_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return False
    return result.returncode == 0 and result.stdout.strip() == "true"


def build_markdown_index(brain_root: Path) -> dict[str, list[Path]]:
    index: dict[str, list[Path]] = defaultdict(list)
    for md_file in brain_root.rglob("*.md"):
        try:
            content = md_file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = md_file.read_text(encoding="utf-8", errors="ignore")
        for line in content.splitlines():
            if "[[" not in line:
                continue
            start = 0
            while True:
                i = line.find("[[", start)
                if i == -1:
                    break
                j = line.find("]]", i + 2)
                if j == -1:
                    break
                target = line[i + 2 : j].split("|", 1)[0].strip()
                base = Path(target).name
                if base:
                    index[base].append(md_file)
                start = j + 2
    return index


def note_attachment_dir(note_path: Path) -> Path:
    return note_path.parent / "ATTACHMENTS"


def _is_name_boundary(char: str) -> bool:
    return char.isalnum() or char in "._-"


def has_bounded_occurrence(text: str, name: str) -> bool:
    start = 0
    while True:
        i = text.find(name, start)
        if i == -1:
            return False
        end = i + len(name)
        bounded_before = i == 0 or not _is_name_boundary(text[i - 1])
        bounded_after = end >= len(text) or not _is_name_boundary(text[end])
        if bounded_before and bounded_after:
            return True
        start = i + 1


def build_plain_mention_index(
    brain_root: Path,
    names: set[str],
) -> dict[str, tuple[Path, ...]]:
    """Single vault pass mapping each candidate filename to the notes that
    mention it as plain text.

    Wikilink spans are stripped before matching so only plain-text mentions
    count, and matches must sit on name boundaries so a longer filename that
    merely contains this name is not reported. The index is built once per
    run from the notes on disk at that moment; it is never cached.
    """
    index: dict[str, tuple[Path, ...]] = {name: () for name in names}
    if not names:
        return index
    hits: dict[str, list[Path]] = defaultdict(list)
    for md_file in brain_root.rglob("*.md"):
        try:
            content = md_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for name in names:
            if name not in content:
                continue
            for line in content.splitlines():
                if name not in line:
                    continue
                plain_line = WIKILINK_SPAN_RE.sub(" ", line)
                if has_bounded_occurrence(plain_line, name):
                    hits[name].append(md_file)
                    break
    for name, notes in hits.items():
        index[name] = tuple(notes)
    return index


def with_plain_mentions(
    reports: list[AttachmentReport],
    mention_index: dict[str, tuple[Path, ...]],
) -> list[AttachmentReport]:
    enriched: list[AttachmentReport] = []
    for report in reports:
        if report.status not in MOVE_CANDIDATE_STATUSES:
            enriched.append(report)
            continue
        refs = {ref.resolve() for ref in report.references}
        mentions = tuple(
            note
            for note in mention_index.get(report.attachment.name, ())
            if note.resolve() not in refs
        )
        enriched.append(replace(report, plain_mentions=mentions))
    return enriched


def infer_destination(
    brain_root: Path,
    refs: list[Path],
    quarantine_dir: Path,
    current_attachment_dir: Path,
    attachment_name: str,
) -> tuple[str, Path | None, str]:
    if not refs:
        return "ORPHAN_CANDIDATE", quarantine_dir / attachment_name, "No markdown references found in the vault."

    target_dirs = {note_attachment_dir(ref) for ref in refs}

    if len(target_dirs) > 1:
        return (
            "CONFLICT_MULTI_NOTE",
            None,
            "Referenced from notes that live in different folders, so no safe automatic destination exists.",
        )

    target_dir = next(iter(target_dirs))
    if target_dir.resolve() == current_attachment_dir.resolve():
        return "KEEP_LOCAL", current_attachment_dir / attachment_name, "All references already point to notes in this folder."

    return (
        "RELOCATE_CANDIDATE",
        target_dir / attachment_name,
        f"Referenced from notes in {target_dir.relative_to(brain_root)}.",
    )


def audit_folder(brain_root: Path, attachment_dir: Path, quarantine_dir: Path, markdown_index: dict[str, list[Path]]) -> list[AttachmentReport]:
    attachments = sorted(path for path in attachment_dir.rglob("*") if path.is_file())
    if not attachments:
        return []
    basename_counts = Counter(attachment.name for attachment in attachments)
    reports: list[AttachmentReport] = []
    for attachment in attachments:
        refs = sorted(set(markdown_index.get(attachment.name, [])))
        if basename_counts[attachment.name] > 1:
            reports.append(
                AttachmentReport(
                    attachment=attachment,
                    status="CONFLICT_DUPLICATE_BASENAME",
                    references=refs,
                    proposed_destination=None,
                    note="Multiple files under this ATTACHMENTS root share the same basename.",
                )
            )
            continue
        status, destination, note = infer_destination(
            brain_root=brain_root,
            refs=refs,
            quarantine_dir=quarantine_dir,
            current_attachment_dir=attachment.parent,
            attachment_name=attachment.name,
        )
        reports.append(
            AttachmentReport(
                attachment=attachment,
                status=status,
                references=refs,
                proposed_destination=destination,
                note=note,
            )
        )
    return reports


def find_attachment_dirs(scope_root: Path) -> list[Path]:
    dirs: set[Path] = set()
    inside_attachment_root = any(parent.name == "ATTACHMENTS" for parent in scope_root.parents)
    if scope_root.is_dir() and (scope_root.name == "ATTACHMENTS" or inside_attachment_root):
        dirs.add(scope_root)
    for p in scope_root.rglob("ATTACHMENTS"):
        if p.is_dir():
            dirs.add(p)
    return sorted(
        attachment_dir
        for attachment_dir in dirs
        if not any(parent in dirs for parent in attachment_dir.parents)
    )


def move_file(src: Path, dst: Path, brain_root: Path, use_git_mv: bool) -> None:
    dst = require_flat_attachment_destination(dst, brain_root=brain_root)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() or dst.is_symlink():
        raise FileExistsError(f"Destination already exists for {src.name}: {dst}")
    if use_git_mv:
        subprocess.run(["git", "mv", str(src), str(dst)], cwd=brain_root, check=True)
    else:
        shutil.move(str(src), str(dst))


def validate_destinations(
    reports: list[AttachmentReport],
    brain_root: Path,
) -> list[str]:
    errors: list[str] = []
    claimed: dict[Path, str] = {}
    for report in reports:
        if report.proposed_destination is None:
            continue
        destination = report.proposed_destination
        if report.status not in MOVE_CANDIDATE_STATUSES:
            if not flat_attachment_shape(destination):
                errors.append(
                    f"{report.attachment.name}: destination is not a direct "
                    f"child of an ATTACHMENTS/ directory: {destination}"
                )
            continue
        try:
            resolved = require_flat_attachment_destination(
                destination, brain_root=brain_root
            )
        except AttachmentDestinationError as error:
            errors.append(f"{report.attachment.name}: {error}")
            continue
        previous = claimed.get(collision_key(resolved))
        if previous is not None:
            errors.append(
                f"{report.attachment.name}: destination {destination} collides "
                f"with the one proposed for {previous}"
            )
        else:
            claimed[collision_key(resolved)] = report.attachment.name
        source = report.attachment.resolve(strict=False)
        if source == resolved:
            errors.append(
                f"{report.attachment.name}: already at its proposed destination "
                f"({destination}); re-auditing it proposes a no-op move"
            )
            continue
        if destination.exists() or destination.is_symlink():
            errors.append(
                f"{report.attachment.name}: destination already exists ({destination})"
            )
    return errors


def cleanup_empty_attachment_dirs(dirs: set[Path]) -> None:
    for attachment_dir in sorted(dirs, key=lambda p: len(p.parts), reverse=True):
        if attachment_dir.exists() and attachment_dir.is_dir() and not any(attachment_dir.iterdir()):
            attachment_dir.rmdir()


def apply_reports(reports: list[AttachmentReport], brain_root: Path, use_git_mv: bool) -> None:
    errors = validate_destinations(reports, brain_root)
    if errors:
        raise AttachmentDestinationError(
            "destination preflight failed:\n" + "\n".join(f"- {e}" for e in errors)
        )
    touched_attachment_dirs: set[Path] = set()
    for report in reports:
        if report.status not in {"RELOCATE_CANDIDATE", "ORPHAN_CANDIDATE"}:
            continue
        if report.proposed_destination is None:
            continue
        for parent in report.attachment.parents:
            touched_attachment_dirs.add(parent)
            if parent.name == "ATTACHMENTS":
                break
        move_file(report.attachment, report.proposed_destination, brain_root, use_git_mv)
    cleanup_empty_attachment_dirs(touched_attachment_dirs)


def print_report(brain_root: Path, scoped_reports: list[tuple[Path, list[AttachmentReport]]], reporter: Reporter, applied: bool, command_string: str) -> None:
    reporter.write("# Attachment audit")
    reporter.write("")
    reporter.write(f"brain_root: {brain_root}")
    reporter.write(f"mode: {'apply' if applied else 'dry-run'}")
    reporter.write(f"command: {command_string}")
    reporter.write(f"move_strategy: {'git mv' if is_git_repo(brain_root) else 'filesystem move'}")
    reporter.write("")
    for attachment_dir, reports in scoped_reports:
        reporter.write(f"## Folder: {attachment_dir.relative_to(brain_root)}")
        reporter.write("")
        for report in reports:
            rel_attachment = report.attachment.relative_to(brain_root)
            reporter.write(f"- {rel_attachment}")
            reporter.write(f"  status: {report.status}")
            reporter.write(f"  note: {report.note}")
            if report.proposed_destination is not None:
                reporter.write(f"  proposed_destination: {report.proposed_destination.relative_to(brain_root)}")
            if report.references:
                reporter.write("  references:")
                for ref in report.references:
                    reporter.write(f"    - {ref.relative_to(brain_root)}")
            else:
                reporter.write("  references: []")
            if report.plain_mentions:
                reporter.write(
                    "  plain_text_mentions (review before moving):"
                )
                for mention in report.plain_mentions:
                    reporter.write(f"    - {mention.relative_to(brain_root)}")
            reporter.write("")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit and optionally relocate attachments under a scope root.")
    parser.add_argument("--brain-root", default=".", help="Vault root path")
    parser.add_argument(
        "--scope-root",
        default="JOURNAL",
        help="Root path under which ATTACHMENTS folders are audited. A path inside an ATTACHMENTS folder is accepted as an exact narrow audit boundary.",
    )
    parser.add_argument(
        "--quarantine-dir",
        default="QUARANTINE/ATTACHMENTS",
        help="Quarantine directory for orphan candidates",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually move safe relocate/orphan candidates instead of reporting only",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    brain_root = Path(args.brain_root).resolve()
    scope_root = (brain_root / args.scope_root).resolve()
    quarantine_dir = (brain_root / args.quarantine_dir).resolve()
    log_path = Path(__file__).with_suffix(".log")
    reporter = Reporter(log_path)
    use_git_mv = is_git_repo(brain_root)
    command_string = build_command_string()

    if not scope_root.exists():
        reporter.write(f"command: {command_string}")
        reporter.write(f"Scope root not found: {scope_root}")
        reporter.flush()
        return 1

    attachment_dirs = find_attachment_dirs(scope_root)
    if not attachment_dirs:
        reporter.write(f"command: {command_string}")
        reporter.write(f"No ATTACHMENTS directories found under: {scope_root}")
        reporter.flush()
        return 0

    markdown_index = build_markdown_index(brain_root)
    scoped_reports: list[tuple[Path, list[AttachmentReport]]] = []
    all_reports: list[AttachmentReport] = []
    for attachment_dir in attachment_dirs:
        reports = audit_folder(brain_root, attachment_dir, quarantine_dir, markdown_index)
        if reports:
            scoped_reports.append((attachment_dir, reports))
            all_reports.extend(reports)

    candidate_names = {
        report.attachment.name
        for report in all_reports
        if report.status in MOVE_CANDIDATE_STATUSES
    }
    if candidate_names:
        mention_index = build_plain_mention_index(brain_root, candidate_names)
        scoped_reports = [
            (attachment_dir, with_plain_mentions(reports, mention_index))
            for attachment_dir, reports in scoped_reports
        ]
        all_reports = with_plain_mentions(all_reports, mention_index)

    destination_errors = validate_destinations(all_reports, brain_root)

    print_report(brain_root, scoped_reports, reporter, args.apply, command_string)
    if destination_errors:
        reporter.write("")
        reporter.write("destination preflight FAILED (no moves were applied):")
        for error in destination_errors:
            reporter.write(f"- {error}")
        reporter.flush()
        return 1
    if args.apply:
        apply_reports(all_reports, brain_root, use_git_mv)
        reporter.write("Applied relocate/orphan moves for safe candidates.")
    reporter.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
