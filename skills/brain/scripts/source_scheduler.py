#!/usr/bin/env python3
"""Deterministic due-ness decisions for source ingestion.

See RULES-OPTIONAL-CAPABILITIES.common.md -> "Source ingestion". The agent never guesses
whether a source is due for a check, blocked, or how it is reached; this script decides
from the registry, each descriptor's fields, and the brain's environment profile, and the
agent only interprets the result (which sources are due, which are blocked and why, then
whether what a subagent found is worth surfacing).

Source ingestion is brain-scoped, not project-scoped (RULES-OPTIONAL-CAPABILITIES.common.md
-> "Scopes"): a mailbox or a calendar belongs to the person, not to whichever project a
session happens to open in. `registry_activated()` below is the whole activation check --
a direct link to `sources.registry` anywhere in WIP/WIP.md, with no per-directory filter.
Once activated, every enabled registry entry is evaluated every session; there is no
`Repository root matcher` concept.

A decision is one of three states, never a silent fourth:
- due: the cadence window has elapsed (or the source is `always` due); safe to investigate.
- not due: checked recently enough; nothing to do, stays quiet.
- blocked: something about the source could not be determined safely (missing/malformed
  descriptor, unknown or unwritten source type, an access capability the active
  environment profile can't route, or a corrupt schedule field). A blocked source is
  reported, never investigated -- fail closed, matching
  RULES-OPTIONAL-CAPABILITIES.common.md's general activation doctrine.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
MODEL_SCRIPTS = REPO_ROOT / "model" / "SCRIPTS"
SCRIPT_DIR = Path(__file__).resolve().parent
if str(MODEL_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(MODEL_SCRIPTS))
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from environment_profiles import ProfileError, resolve_profile  # noqa: E402
from model_check_no_follow import lstat_entry, symlinked_parent  # noqa: E402
from _common import Reporter, build_command_string  # noqa: E402


SOURCE_HEADING_RE = re.compile(r"^###\s+(.+?)\s*$")
FIELD_RE = re.compile(r"^-\s+([A-Za-z][A-Za-z0-9 ()]*):\s*(.*?)\s*$")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
CAPABILITY_RE = re.compile(r"^[a-z][a-z0-9_.-]*$")
REGISTRY_LINK_RE = re.compile(
    r"\[\[[^\]]*sources\.registry(?:\.md)?[^\]]*\]\]"
    r"|\]\([^)]*sources\.registry\.md\)"
)

VALID_STATUS = ("ok", "no_activity", "degraded")
WATERMARK_STATUSES = ("ok", "no_activity")
NEVER_CHECKED_SENTINELS = {"", "not checked", "none"}


@dataclass
class SourceEntry:
    slug: str
    status: str
    source_type: str
    descriptor: str
    purpose: str


@dataclass
class SourceDecision:
    slug: str
    source_type: str
    due: bool
    blocked: bool
    reason: str
    last_checked: str
    cadence_days: int


def parse_fields(lines: list[str]) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in lines:
        match = FIELD_RE.match(line)
        if match:
            value = match.group(2).strip()
            # A field value is often written as inline code (`issues.search`,
            # `always`) -- natural Markdown style for a technical token. Strip one
            # surrounding pair so parsing doesn't depend on the author's styling.
            if len(value) >= 2 and value.startswith("`") and value.endswith("`"):
                value = value[1:-1].strip()
            fields[match.group(1).strip().casefold()] = value
    return fields


def parse_registry_entries(text: str) -> list[SourceEntry]:
    entries: list[SourceEntry] = []
    current_slug: str | None = None
    current_lines: list[str] = []

    def flush() -> None:
        if current_slug is None:
            return
        fields = parse_fields(current_lines)
        entries.append(
            SourceEntry(
                slug=current_slug,
                status=fields.get("status", "disabled").casefold(),
                source_type=fields.get("type", ""),
                descriptor=fields.get("descriptor", ""),
                purpose=fields.get("purpose", ""),
            )
        )

    for line in text.splitlines():
        heading = SOURCE_HEADING_RE.match(line)
        if heading:
            flush()
            current_slug = heading.group(1).strip()
            current_lines = []
            continue
        if current_slug is not None:
            current_lines.append(line)
    flush()
    return entries


def enabled_sources(registry_path: Path) -> list[SourceEntry]:
    if not registry_path.exists():
        return []
    text = registry_path.read_text(encoding="utf-8")
    return [entry for entry in parse_registry_entries(text) if entry.status == "enabled"]


def registry_activated(brain_root: Path) -> bool:
    """Whether source ingestion is switched on for this brain.

    Brain-scoped: a direct link to `sources.registry` anywhere in WIP/WIP.md activates
    the capability for the whole brain, with no per-project heading match and no
    presentational preview-length limit. A bare textual mention of the filename (e.g.
    prose that happens to say "sources.registry") is not enough -- an actual wikilink or
    markdown link is required.
    """
    wip_path = brain_root / "WIP" / "WIP.md"
    if not wip_path.exists():
        return False
    text = wip_path.read_text(encoding="utf-8")
    return bool(REGISTRY_LINK_RE.search(text))


def descriptor_path_for(sources_dir: Path, slug: str) -> Path:
    if not SLUG_RE.match(slug):
        raise ValueError(f"invalid source slug: {slug!r}")
    return sources_dir / f"sources.{slug}.md"


def capability_routes(brain_root: Path) -> tuple[set[str] | None, str | None]:
    """Statically resolve the brain's environment profile and return the set of
    capabilities it routes, or (None, <error>) if no usable profile is configured.
    This never performs a live provider call -- that is the investigating subagent's
    job, via profile_context.py, the same as any other skill."""
    try:
        resolved = resolve_profile(brain_root, cwd=brain_root)
    except ProfileError as error:
        return None, str(error)
    return set(resolved.document.get("capability_routes", {})), None


def decide_source(
    brain_root: Path,
    entry: SourceEntry,
    today: date,
    routed_capabilities: set[str] | None,
    profile_error: str | None,
) -> SourceDecision:
    sources_dir = brain_root / "WIP" / "SOURCES"
    source_types_dir = brain_root / "SOURCE_TYPES"

    def blocked(reason: str) -> SourceDecision:
        return SourceDecision(entry.slug, entry.source_type, False, True, reason, "none", 0)

    try:
        descriptor_path = descriptor_path_for(sources_dir, entry.slug)
    except ValueError as error:
        return blocked(str(error))

    unsafe_parent = symlinked_parent(brain_root, descriptor_path)
    if unsafe_parent is not None:
        return blocked(f"descriptor parent is a symlink: {unsafe_parent}")
    file_entry = lstat_entry(descriptor_path)
    if not file_entry.exists:
        return blocked("descriptor not found")
    if file_entry.is_symlink:
        return blocked("descriptor is a symlink")
    if not file_entry.is_file:
        return blocked("descriptor is not a regular file")

    if not entry.source_type:
        return blocked("missing source type")
    if not (source_types_dir / f"{entry.source_type}.md").exists():
        return blocked(f"no guide for type {entry.source_type!r}")

    fields = parse_fields(descriptor_path.read_text(encoding="utf-8").splitlines())

    capability = fields.get("requires capability", "").strip()
    if not capability or not CAPABILITY_RE.match(capability):
        return blocked("missing or malformed 'Requires capability'")
    if profile_error is not None:
        return blocked(f"no usable environment profile: {profile_error}")
    if routed_capabilities is not None and capability not in routed_capabilities:
        return blocked(f"capability {capability!r} is not routed by the active profile")

    cadence_raw = fields.get("check cadence (days)", "").strip()
    if not cadence_raw:
        return blocked("missing 'Check cadence (days)'")
    if cadence_raw.casefold() == "always":
        cadence_days = 0
    else:
        try:
            cadence_days = int(cadence_raw)
        except ValueError:
            return blocked(f"invalid cadence: {cadence_raw!r}")
        if cadence_days <= 0:
            return blocked(f"invalid cadence: {cadence_raw!r}")

    if "last checked" not in fields:
        return blocked("missing 'Last checked'")
    last_checked_raw = fields["last checked"].strip()

    if cadence_days == 0:
        never_checked = last_checked_raw.casefold() in NEVER_CHECKED_SENTINELS
        last_label = "none" if never_checked else last_checked_raw
        return SourceDecision(
            entry.slug, entry.source_type, True, False,
            "always due (cadence: always)", last_label, cadence_days,
        )

    if last_checked_raw.casefold() in NEVER_CHECKED_SENTINELS:
        return SourceDecision(
            entry.slug, entry.source_type, True, False, "never checked", "none", cadence_days,
        )

    try:
        last_checked = date.fromisoformat(last_checked_raw)
    except ValueError:
        return blocked(f"invalid 'Last checked' date: {last_checked_raw!r}")

    next_due = last_checked + timedelta(days=cadence_days)
    if today >= next_due:
        reason = f"last checked {last_checked.isoformat()}, cadence {cadence_days}d"
        return SourceDecision(
            entry.slug, entry.source_type, True, False, reason, last_checked.isoformat(), cadence_days,
        )
    reason = f"checked {last_checked.isoformat()}, next due {next_due.isoformat()}"
    return SourceDecision(
        entry.slug, entry.source_type, False, False, reason, last_checked.isoformat(), cadence_days,
    )


def decide_sources(brain_root: Path, today: date) -> list[SourceDecision]:
    sources_dir = brain_root / "WIP" / "SOURCES"
    registry_path = sources_dir / "sources.registry.md"
    routed_capabilities, profile_error = capability_routes(brain_root)
    return [
        decide_source(brain_root, entry, today, routed_capabilities, profile_error)
        for entry in enabled_sources(registry_path)
    ]


def summarize_due_sources(brain_root: Path, today: date) -> list[str]:
    lines: list[str] = []
    for decision in decide_sources(brain_root, today):
        if decision.blocked:
            lines.append(f"- {decision.slug}: blocked — {decision.reason}")
        elif decision.due:
            type_label = decision.source_type or "unknown type"
            lines.append(f"- {decision.slug} ({type_label}): {decision.reason}")
    return lines


def _atomic_write(path: Path, content: str) -> None:
    """Write `content` to `path` via a temp file + rename to avoid partial writes."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def mark_checked(descriptor_path: Path, today: date, status: str) -> None:
    if status not in VALID_STATUS:
        raise ValueError(f"invalid status: {status!r} (expected one of {VALID_STATUS})")
    if not descriptor_path.exists():
        raise FileNotFoundError(f"descriptor not found: {descriptor_path}")
    if descriptor_path.is_symlink():
        raise ValueError(f"descriptor must not be a symlink: {descriptor_path}")
    text = descriptor_path.read_text(encoding="utf-8")
    text, status_count = re.subn(
        r"(?m)^- Last status:.*$", f"- Last status: {status}", text, count=1
    )
    if status in WATERMARK_STATUSES:
        text, checked_count = re.subn(
            r"(?m)^- Last checked:.*$", f"- Last checked: {today.isoformat()}", text, count=1
        )
    else:
        # degraded: leave the watermark untouched so the source stays due for retry
        # and no unread window is silently skipped.
        checked_count = 1 if re.search(r"(?m)^- Last checked:.*$", text) else 0
    if checked_count == 0 or status_count == 0:
        raise ValueError(
            f"descriptor missing 'Last checked:'/'Last status:' fields: {descriptor_path}"
        )
    _atomic_write(descriptor_path, text)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Decide which sources are due, not due, or blocked for ingestion."
    )
    parser.add_argument("--brain-root", default=".", help="Brain root path")
    subparsers = parser.add_subparsers(dest="command")

    list_due = subparsers.add_parser("list-due", help="List due/blocked sources (default)")
    list_due.add_argument("--date", help="Override today's date as YYYY-MM-DD")
    list_due.add_argument("--json", action="store_true", help="Print machine-readable JSON")

    mark = subparsers.add_parser("mark-checked", help="Record that a source was just checked")
    mark.add_argument("--source", required=True, help="Source slug, matching sources.<slug>.md")
    mark.add_argument("--status", required=True, choices=VALID_STATUS)
    mark.add_argument("--date", help="Override today's date as YYYY-MM-DD")
    mark.add_argument("--apply", action="store_true", help="Apply the update. Default is dry-run.")

    return parser


def normalize_brain_root(argv: list[str]) -> list[str]:
    """Accept --brain-root before or after the subcommand.

    argparse only recognizes an option owned by the main parser before the
    subcommand token; a subparser copy would work for "after" but a naive
    `_SubParsersAction` merge-back overwrites an already-parsed parent value with
    the subparser's own unset default, breaking "before". Move `--brain-root`
    (and its value) to the front instead, so it always binds to the one option
    defined on the main parser, regardless of where the caller placed it -- the
    documented SKILL.md form puts it after the subcommand.
    """
    front: list[str] = []
    rest: list[str] = []
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--brain-root" and index + 1 < len(argv):
            front.extend([token, argv[index + 1]])
            index += 2
            continue
        if token.startswith("--brain-root="):
            front.append(token)
            index += 1
            continue
        rest.append(token)
        index += 1
    return [*front, *rest]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    raw = sys.argv[1:] if argv is None else argv
    args = build_parser().parse_args(normalize_brain_root(raw))
    if args.command is None:
        args.command = "list-due"
        args.date = None
        args.json = False
    return args


def run_mark_checked(brain_root: Path, today: date, source: str, status: str, apply: bool) -> int:
    log_path = SCRIPT_DIR / "source_scheduler.log"
    reporter = Reporter(log_path)
    reporter.write("# Source scheduler: mark-checked")
    reporter.write(f"mode: {'apply' if apply else 'dry-run'}")
    reporter.write(f"brain_root: {brain_root}")
    reporter.write(f"command: {build_command_string()}")
    reporter.write("")

    sources_dir = brain_root / "WIP" / "SOURCES"
    try:
        descriptor_path = descriptor_path_for(sources_dir, source)
    except ValueError as error:
        reporter.write(f"mark-checked failed: {error}")
        reporter.flush()
        return 1

    unsafe_parent = symlinked_parent(brain_root, descriptor_path)
    if unsafe_parent is not None:
        reporter.write(f"mark-checked failed: descriptor parent is a symlink: {unsafe_parent}")
        reporter.flush()
        return 1
    file_entry = lstat_entry(descriptor_path)
    if file_entry.is_symlink:
        reporter.write(f"mark-checked failed: descriptor is a symlink: {descriptor_path}")
        reporter.flush()
        return 1
    if not file_entry.exists or not file_entry.is_file:
        reporter.write(f"mark-checked failed: descriptor not found: {descriptor_path}")
        reporter.flush()
        return 1

    watermark_note = (
        "advances Last checked" if status in WATERMARK_STATUSES
        else "leaves Last checked untouched (degraded)"
    )
    reporter.write(f"  {source}: set Last status: {status} ({watermark_note})")

    if not apply:
        reporter.write("")
        reporter.write("(dry-run: no file changed. Re-run with --apply.)")
        reporter.flush()
        return 0

    try:
        mark_checked(descriptor_path, today, status)
    except (FileNotFoundError, ValueError) as error:
        reporter.write(f"mark-checked failed: {error}")
        reporter.flush()
        return 1
    reporter.write("  applied.")
    reporter.flush()
    return 0


def main() -> int:
    args = parse_args()
    brain_root = Path(args.brain_root).expanduser().resolve()
    if not brain_root.is_dir():
        print(f"Brain root not found: {brain_root}")
        return 1
    today = date.fromisoformat(args.date) if args.date else datetime.now().date()

    if args.command == "mark-checked":
        return run_mark_checked(brain_root, today, args.source, args.status, args.apply)

    decisions = decide_sources(brain_root, today)
    if args.json:
        print(json.dumps([decision.__dict__ for decision in decisions], ensure_ascii=False, indent=2))
    else:
        print("# Source scheduler")
        print(f"brain_root: {brain_root}")
        print(f"today: {today.isoformat()}")
        print()
        print("## Decisions")
        for decision in decisions:
            print(f"- {decision.slug} ({decision.source_type or 'unknown type'})")
            print(f"  blocked: {decision.blocked}")
            print(f"  due: {decision.due}")
            print(f"  reason: {decision.reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
