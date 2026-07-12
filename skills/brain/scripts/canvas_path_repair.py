#!/usr/bin/env python3

"""
Audit and optionally repair Obsidian canvas file-node paths after note moves.

Safe by default:
- dry-run unless --apply
- only rewrites broken file paths when the destination is uniquely resolvable by basename
- logs to console and always overwrites the latest .log file
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class NodeReport:
    canvas: Path
    node_id: str
    old_path: str
    status: str
    new_path: str | None
    note: str


from _common import Reporter, build_command_string  # noqa: E402  (lives next to this script)


def build_file_index(brain_root: Path) -> dict[str, list[Path]]:
    index: dict[str, list[Path]] = {}
    for p in brain_root.rglob("*.md"):
        index.setdefault(p.name, []).append(p)
    return index


def normalize_basename(name: str) -> str:
    return "".join(ch for ch in name.casefold() if ch.isalnum())


def build_normalized_file_index(brain_root: Path) -> dict[str, list[Path]]:
    index: dict[str, list[Path]] = {}
    for p in brain_root.rglob("*.md"):
        key = normalize_basename(p.name)
        index.setdefault(key, []).append(p)
    return index


def audit_canvas(brain_root: Path, canvas_path: Path, file_index: dict[str, list[Path]], normalized_file_index: dict[str, list[Path]]) -> tuple[list[NodeReport], dict]:
    try:
        data = json.loads(canvas_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [NodeReport(canvas_path, "", "", "PARSE_ERROR", None, f"Failed to read/parse canvas: {exc}")], {}
    reports: list[NodeReport] = []
    for node in data.get("nodes", []):
        if node.get("type") != "file":
            continue
        rel = node.get("file")
        if not rel:
            continue
        target = (brain_root / rel).resolve()
        if target.exists():
            reports.append(NodeReport(canvas_path, node.get("id", ""), rel, "OK", rel, "Target exists."))
            continue
        basename = Path(rel).name
        matches = file_index.get(basename, [])
        if not matches:
            matches = normalized_file_index.get(normalize_basename(basename), [])
        if not matches:
            reports.append(NodeReport(canvas_path, node.get("id", ""), rel, "MISSING", None, "No matching note basename found in vault."))
            continue
        if len(matches) > 1:
            reports.append(NodeReport(canvas_path, node.get("id", ""), rel, "AMBIGUOUS", None, f"Multiple matching note basenames found: {[str(m.relative_to(brain_root)) for m in matches]}"))
            continue
        new_rel = str(matches[0].relative_to(brain_root))
        reports.append(NodeReport(canvas_path, node.get("id", ""), rel, "REWRITE_CANDIDATE", new_rel, "Unique basename match found."))
    return reports, data


def atomic_write(path: Path, content: str) -> None:
    """Write `content` to `path` via a temp file + rename to avoid partial writes."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def apply_reports(brain_root: Path, canvas_data: dict[Path, tuple[list[NodeReport], dict]]) -> None:
    for canvas_path, (reports, data) in canvas_data.items():
        changed = False
        node_map = {node.get("id", ""): node for node in data.get("nodes", [])}
        for report in reports:
            if report.status != "REWRITE_CANDIDATE" or not report.new_path:
                continue
            node = node_map.get(report.node_id)
            if node is None:
                continue
            node["file"] = report.new_path
            changed = True
        if changed:
            atomic_write(canvas_path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def print_report(brain_root: Path, scoped: dict[Path, tuple[list[NodeReport], dict]], reporter: Reporter, applied: bool, command_string: str) -> None:
    reporter.write("# Canvas path audit")
    reporter.write("")
    reporter.write(f"brain_root: {brain_root}")
    reporter.write(f"mode: {'apply' if applied else 'dry-run'}")
    reporter.write(f"command: {command_string}")
    reporter.write("")
    for canvas_path, (reports, _) in scoped.items():
        reporter.write(f"## Canvas: {canvas_path.relative_to(brain_root)}")
        reporter.write("")
        for report in reports:
            reporter.write(f"- node: {report.node_id}")
            reporter.write(f"  old_path: {report.old_path}")
            reporter.write(f"  status: {report.status}")
            if report.new_path:
                reporter.write(f"  new_path: {report.new_path}")
            reporter.write(f"  note: {report.note}")
            reporter.write("")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit and optionally repair Obsidian canvas file-node paths.")
    parser.add_argument("--brain-root", default=".", help="Vault root path")
    parser.add_argument("--scope-root", default=".", help="Root path under which canvas files should be audited")
    parser.add_argument("--apply", action="store_true", help="Rewrite uniquely resolvable broken file paths")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    brain_root = Path(args.brain_root).resolve()
    scope_root = (brain_root / args.scope_root).resolve()
    log_path = Path(__file__).with_suffix(".log")
    reporter = Reporter(log_path)
    command_string = build_command_string()

    if not scope_root.exists():
        reporter.write(f"Scope root not found: {scope_root}")
        reporter.flush()
        return 1

    canvases = sorted(scope_root.rglob("*.canvas")) if scope_root.is_dir() else []
    if not canvases:
        reporter.write(f"No canvas files found under: {scope_root}")
        reporter.flush()
        return 0

    index = build_file_index(brain_root)
    normalized_index = build_normalized_file_index(brain_root)
    scoped: dict[Path, tuple[list[NodeReport], dict]] = {}
    for canvas_path in canvases:
        scoped[canvas_path] = audit_canvas(brain_root, canvas_path, index, normalized_index)

    print_report(brain_root, scoped, reporter, args.apply, command_string)
    if args.apply:
        apply_reports(brain_root, scoped)
        reporter.write("Applied unique canvas path rewrites.")
    reporter.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
