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
import subprocess
import shutil
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path


@dataclass
class AttachmentReport:
    attachment: Path
    status: str
    references: list[Path]
    proposed_destination: Path | None
    note: str


from _common import Reporter, build_command_string  # noqa: E402  (lives next to this script)


def is_git_repo(brain_root: Path) -> bool:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=brain_root,
            capture_output=True,
            text=True,
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
    if not any(p.is_file() for p in attachment_dir.iterdir()):
        return []
    reports: list[AttachmentReport] = []
    for attachment in sorted(p for p in attachment_dir.iterdir() if p.is_file()):
        refs = sorted(set(markdown_index.get(attachment.name, [])))
        status, destination, note = infer_destination(
            brain_root=brain_root,
            refs=refs,
            quarantine_dir=quarantine_dir,
            current_attachment_dir=attachment_dir,
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
    if scope_root.is_dir() and scope_root.name == "ATTACHMENTS":
        dirs.add(scope_root)
    for p in scope_root.rglob("ATTACHMENTS"):
        if p.is_dir():
            dirs.add(p)
    return sorted(dirs)


def move_file(src: Path, dst: Path, brain_root: Path, use_git_mv: bool) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        raise FileExistsError(f"Destination already exists for {src.name}: {dst}")
    if use_git_mv:
        subprocess.run(["git", "mv", str(src), str(dst)], cwd=brain_root, check=True)
    else:
        shutil.move(str(src), str(dst))


def cleanup_empty_attachment_dirs(dirs: set[Path]) -> None:
    for attachment_dir in sorted(dirs, key=lambda p: len(p.parts), reverse=True):
        if attachment_dir.exists() and attachment_dir.is_dir() and not any(attachment_dir.iterdir()):
            attachment_dir.rmdir()


def apply_reports(reports: list[AttachmentReport], brain_root: Path, use_git_mv: bool) -> None:
    touched_attachment_dirs: set[Path] = set()
    for report in reports:
        if report.status not in {"RELOCATE_CANDIDATE", "ORPHAN_CANDIDATE"}:
            continue
        if report.proposed_destination is None:
            continue
        touched_attachment_dirs.add(report.attachment.parent)
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
            reporter.write("")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit and optionally relocate attachments under a scope root.")
    parser.add_argument("--brain-root", default=".", help="Vault root path")
    parser.add_argument(
        "--scope-root",
        default="JOURNAL",
        help="Root path under which all ATTACHMENTS folders should be audited. If the path itself is an ATTACHMENTS folder, it is included too.",
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

    print_report(brain_root, scoped_reports, reporter, args.apply, command_string)
    if args.apply:
        apply_reports(all_reports, brain_root, use_git_mv)
        reporter.write("Applied relocate/orphan moves for safe candidates.")
    reporter.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
