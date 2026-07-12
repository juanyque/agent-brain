#!/usr/bin/env python3

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from _common import build_command_string


DATE_RE = re.compile(r"^(\d{4})-\d{2}-\d{2}\.md$")

EXPECTED_ROOT_DIRS = {
    "_COMMON",
    "BACKLOG",
    "INBOX",
    "JOURNAL",
    "MEMORY",
    "QUARANTINE",
    "REPORTS",
    "TEMPLATES",
    "WIP",
}

EXPECTED_ROOT_FILES = {
    "AGENTS.md",
    "BRAIN.md",
    "JOBS.md",
    "JOBS_LOGS.md",
    "RULES-DAILY-NOTES.md",
    "RULES-FILE-NAMING.md",
    "RULES-LINKS.md",
    "RULES-SESSION-LIFECYCLE.md",
}

DEFAULT_SENSITIVE_TERMS = [
    "credential", "credentials", "password", "secret", "token", "access",
]


def build_sensitive_re(extra_terms: list[str]) -> re.Pattern[str]:
    """Build a case-insensitive regex matching any of the default + extra terms."""
    terms = DEFAULT_SENSITIVE_TERMS + [t for t in extra_terms if t]
    pattern = "(" + "|".join(re.escape(t) for t in terms) + ")"
    return re.compile(pattern, re.IGNORECASE)


@dataclass
class Finding:
    severity: str
    area: str
    message: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Assess a vault against the obsidian-vault-common structure.")
    parser.add_argument("--brain-root", default=".", help="Vault root path")
    parser.add_argument("--output", default="WIP/STANDARDIZE_PROCESS.md", help="Report path relative to vault root")
    parser.add_argument("--apply", action="store_true", help="Write the assessment report instead of printing only")
    parser.add_argument(
        "--sensitive-extra",
        nargs="*",
        default=[],
        help="Extra case-insensitive terms to flag for manual sensitivity review (e.g. tool names specific to your stack)",
    )
    return parser.parse_args()


def rel(brain_root: Path, path: Path) -> str:
    return str(path.relative_to(brain_root))


def list_children(path: Path) -> list[Path]:
    if not path.exists() or not path.is_dir():
        return []
    return sorted(path.iterdir(), key=lambda p: p.name.casefold())


def count_md(path: Path) -> int:
    if not path.exists() or not path.is_dir():
        return 0
    return sum(1 for _ in path.rglob("*.md"))


def assess_root(brain_root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for required in sorted(EXPECTED_ROOT_DIRS):
        if not (brain_root / required).exists():
            findings.append(Finding("warning", "root", f"Missing expected directory `{required}/`."))
    for required in sorted(EXPECTED_ROOT_FILES):
        if not (brain_root / required).exists():
            findings.append(Finding("warning", "root", f"Missing expected file `{required}`."))
    for child in list_children(brain_root):
        if child.name.startswith("."):
            continue
        if child.is_dir() and child.name not in EXPECTED_ROOT_DIRS:
            findings.append(Finding("review", "root", f"Unexpected top-level directory `{child.name}/`."))
        if child.is_file() and child.name not in EXPECTED_ROOT_FILES:
            findings.append(Finding("review", "root", f"Unexpected top-level file `{child.name}`."))
    return findings


def assess_staging(brain_root: Path) -> list[Finding]:
    staging = brain_root / "_STAGING"
    if not staging.exists():
        return [Finding("ok", "mode", "`_STAGING/` is absent: maintenance mode.")]
    if not staging.is_dir():
        return [Finding("error", "mode", "`_STAGING` exists but is not a directory.")]
    count = len(list_children(staging))
    if count == 0:
        return [Finding("ok", "mode", "`_STAGING/` exists but is empty: maintenance mode.")]
    return [Finding("warning", "mode", f"`_STAGING/` contains {count} top-level item(s): initial mode should continue draining it.")]


def assess_journal(brain_root: Path) -> list[Finding]:
    findings: list[Finding] = []
    root_entry_names = {child.name for child in list_children(brain_root)}
    journal = brain_root / "JOURNAL"
    if "Journal" in root_entry_names:
        findings.append(Finding("warning", "JOURNAL", "Legacy `Journal/` path still exists."))
    if not journal.exists():
        return findings
    current_year = str(datetime.now().year)
    non_daily: list[Path] = []
    old_year_daily: list[Path] = []
    nested_current_year_daily: list[Path] = []
    for md in journal.rglob("*.md"):
        match = DATE_RE.match(md.name)
        if not match:
            non_daily.append(md)
            continue
        year = match.group(1)
        parent = md.parent.relative_to(journal)
        if year == current_year and str(parent) != ".":
            nested_current_year_daily.append(md)
        if year != current_year and parent.parts[:1] != (year,):
            old_year_daily.append(md)
    for md in non_daily[:20]:
        findings.append(Finding("review", "JOURNAL", f"Non-daily note under JOURNAL: `{rel(brain_root, md)}`."))
    if len(non_daily) > 20:
        findings.append(Finding("review", "JOURNAL", f"{len(non_daily) - 20} additional non-daily JOURNAL notes not listed."))
    for md in old_year_daily[:20]:
        findings.append(Finding("review", "JOURNAL", f"Closed-year daily note not under `JOURNAL/<year>/`: `{rel(brain_root, md)}`."))
    for md in nested_current_year_daily[:20]:
        findings.append(Finding("review", "JOURNAL", f"Current-year daily note should live directly under `JOURNAL/`: `{rel(brain_root, md)}`."))
    return findings


def assess_wip(brain_root: Path) -> list[Finding]:
    findings: list[Finding] = []
    wip = brain_root / "WIP"
    if not (wip / "WIP.md").exists():
        findings.append(Finding("warning", "WIP", "Missing `WIP/WIP.md` dashboard."))
    if not (wip / "SESSIONS").exists():
        findings.append(Finding("review", "WIP", "Missing `WIP/SESSIONS/` for session notes."))
    return findings


def assess_counts(brain_root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for area in ["INBOX", "INBOX/LEGACY", "BACKLOG", "WIP", "MEMORY", "REPORTS", "QUARANTINE"]:
        findings.append(Finding("info", area, f"`{area}/` contains {count_md(brain_root / area)} markdown note(s)."))
    return findings


def assess_support_files(brain_root: Path) -> list[Finding]:
    findings: list[Finding] = []
    attachments = [p for p in brain_root.rglob("ATTACHMENTS") if p.is_dir()]
    canvases = [p for p in brain_root.rglob("*.canvas")]
    findings.append(Finding("info", "attachments", f"Found {len(attachments)} `ATTACHMENTS/` folder(s). Run `attachments_audit.py` by scope before/after reorganizing notes."))
    findings.append(Finding("info", "canvas", f"Found {len(canvases)} canvas file(s). Run `canvas_path_repair.py` after note/canvas moves."))
    return findings


def assess_sensitive_names(brain_root: Path, sensitive_re: re.Pattern[str]) -> list[Finding]:
    findings: list[Finding] = []
    matches = [p for p in brain_root.rglob("*.md") if sensitive_re.search(p.name)]
    for md in matches[:20]:
        findings.append(Finding("review", "sensitive-review", f"Filename suggests manual sensitivity review: `{rel(brain_root, md)}`."))
    if len(matches) > 20:
        findings.append(Finding("review", "sensitive-review", f"{len(matches) - 20} additional filename-based sensitivity candidates not listed."))
    return findings


def build_report(brain_root: Path, findings: list[Finding]) -> str:
    lines = [
        "# STANDARDIZE_PROCESS",
        "",
        "## Purpose",
        "- Track vault standardization state across sessions and runtimes.",
        "- This report is generated by `standardize_assessment.py` and should be reviewed before any move.",
        "",
        "## Last assessment",
        f"- Generated: {datetime.now().isoformat(timespec='seconds')}",
        f"- Command: `{build_command_string()}`",
        f"- Vault: `{brain_root}`",
        "- Mode: maintenance assessment (no files moved)",
        "",
        "## Summary",
    ]
    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding.severity] = counts.get(finding.severity, 0) + 1
    for severity in ["error", "warning", "review", "info", "ok"]:
        lines.append(f"- {severity}: {counts.get(severity, 0)}")
    lines.extend(["", "## Findings"])
    for finding in findings:
        lines.append(f"- [{finding.severity}] **{finding.area}** — {finding.message}")
    lines.extend([
        "",
        "## Proposed next actions",
        "- Review `error` and `warning` findings first.",
        "- Review `review` findings by area and decide whether each item belongs in WIP, BACKLOG, MEMORY, INBOX/LEGACY, or QUARANTINE.",
        "- Run attachment/canvas tools only for scopes touched by actual moves.",
        "- Do not move or delete anything from this assessment without an explicit follow-up plan.",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    brain_root = Path(args.brain_root).expanduser().resolve()
    if not brain_root.is_dir():
        print(f"Vault root not found: {brain_root}")
        return 1
    findings: list[Finding] = []
    findings.extend(assess_staging(brain_root))
    findings.extend(assess_root(brain_root))
    findings.extend(assess_journal(brain_root))
    findings.extend(assess_wip(brain_root))
    findings.extend(assess_counts(brain_root))
    findings.extend(assess_support_files(brain_root))
    sensitive_re = build_sensitive_re(args.sensitive_extra)
    findings.extend(assess_sensitive_names(brain_root, sensitive_re))
    report = build_report(brain_root, findings)
    print(report)
    if args.apply:
        output = brain_root / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(report, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
