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
- blocked: something about the source, its descriptor, its type guide, or the registry
  itself could not be determined safely (missing/malformed/duplicated fields, an
  unwritten or unsafe source type, an access capability the active environment profile
  can't route, a corrupt schedule field, a missing or unreadable registry, or a
  duplicate registry entry). A blocked source is reported, never investigated -- fail
  closed, matching RULES-OPTIONAL-CAPABILITIES.common.md's general activation doctrine.

A `cwd` parameter appears on the capability-resolution path (`capability_routes()`,
`decide_sources()`, `summarize_due_sources()`, the `list-due` CLI). It selects which
environment profile applies in a brain with per-project profiles -- the same selector
`profile_context.py` uses -- and nothing else. It never scopes which sources are
evaluated; that would reintroduce the project-scoping this module deliberately doesn't
have. Passing the session's real cwd keeps this static check and the investigating
subagent's later live resolution pointed at the same profile.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
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
SOURCE_TYPE_RE = re.compile(r"^[a-z][a-z0-9-]*$")
WIKILINK_TARGET_RE = re.compile(r"\[\[([^\]|#]+)")
MARKDOWN_LINK_TARGET_RE = re.compile(r"\]\(([^)#]+)")
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
FENCED_CODE_RE = re.compile(r"```.*?```", re.DOTALL)
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
URL_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")
REGISTRY_LINK_BASENAMES = {"sources.registry", "sources.registry.md"}

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
    duplicate_fields: frozenset[str]


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
                duplicate_fields=frozenset(_duplicate_field_keys(current_lines)),
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


def _read_no_follow(path: Path) -> str:
    """Read `path` as UTF-8 text, refusing to follow it if it is (or has just become) a
    symlink. Using O_NOFOLLOW at open() time closes the gap between an earlier
    lstat-based symlink check and this read: a swap in between is rejected by the
    open() call itself, not missed by a stale prior check."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "r", encoding="utf-8") as handle:
        return handle.read()


def _read_source_file_or_issue(brain_root: Path, path: Path, label: str) -> tuple[str | None, str | None]:
    """Shared safety-and-read logic for the registry, a descriptor, or a source-type
    guide: validate the path shape, then read it through the same no-follow open --
    one combined operation instead of a separate shape check followed by a plain
    open() a race could swap out from under. Returns (text, None) or (None, issue)."""
    unsafe_parent = symlinked_parent(brain_root, path)
    if unsafe_parent is not None:
        return None, f"{label} parent is a symlink: {unsafe_parent}"
    entry = lstat_entry(path)
    if not entry.exists:
        return None, f"{label} not found"
    if entry.is_symlink:
        return None, f"{label} is a symlink"
    if not entry.is_file:
        return None, f"{label} is not a regular file"
    try:
        return _read_no_follow(path), None
    except UnicodeDecodeError:
        return None, f"{label} is not valid UTF-8"
    except OSError as error:
        return None, f"{label} is not readable: {error}"


def _link_target_basenames(text: str) -> list[str]:
    """Every link target's basename in `text` -- wikilink and local Markdown links,
    alias/heading/fragment stripped -- so activation can compare exact filenames
    instead of a raw substring match (which would also match `not-sources.registry.md`
    or `sources.registry.backup`, and miss a valid link with a `#fragment`).

    Excludes: HTML comments, fenced code blocks, and inline code spans (a link shown
    only as example text, e.g. `` `[[sources.registry]]` ``, is not a rendered link);
    and any Markdown link whose destination is an absolute URL (`scheme://...`) -- an
    external link that merely ends in a filename matching the registry's is not a
    local link to it.
    """
    stripped = HTML_COMMENT_RE.sub("", text)
    stripped = FENCED_CODE_RE.sub("", stripped)
    stripped = INLINE_CODE_RE.sub("", stripped)
    targets = [match.group(1).strip() for match in WIKILINK_TARGET_RE.finditer(stripped)]
    targets += [
        match.group(1).strip()
        for match in MARKDOWN_LINK_TARGET_RE.finditer(stripped)
        if not URL_SCHEME_RE.match(match.group(1).strip())
    ]
    return [Path(target).name for target in targets if target]


def registry_activated(brain_root: Path) -> bool:
    """Whether source ingestion is switched on for this brain.

    Brain-scoped: a direct link to `sources.registry` anywhere in WIP/WIP.md activates
    the capability for the whole brain, with no per-project heading match and no
    presentational preview-length limit. A bare textual mention of the filename (e.g.
    prose that happens to say "sources.registry") is not enough -- an actual, local,
    rendered wikilink or Markdown link, resolved to its exact target basename, is
    required. See `_link_target_basenames()` for exactly what is excluded.
    """
    wip_path = brain_root / "WIP" / "WIP.md"
    if not wip_path.exists():
        return False
    try:
        text = wip_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return False
    return any(name in REGISTRY_LINK_BASENAMES for name in _link_target_basenames(text))


def descriptor_path_for(sources_dir: Path, slug: str) -> Path:
    if not SLUG_RE.match(slug):
        raise ValueError(f"invalid source slug: {slug!r}")
    return sources_dir / f"sources.{slug}.md"


def capability_routes(brain_root: Path, cwd: Path | None = None) -> tuple[set[str] | None, str | None]:
    """Statically resolve the environment profile the given cwd would select and
    return the set of capabilities it routes, or (None, <error>) if no usable profile
    is configured. This never performs a live provider call -- that is the
    investigating subagent's job, via profile_context.py, the same as any other skill.

    `cwd` selects which profile applies (a brain can have per-project profiles via
    `project_rules`), never which sources are evaluated -- source ingestion itself
    stays brain-scoped regardless of `cwd`. Pass the session's real cwd so this static
    check resolves the SAME profile the subagent's later live resolution will use;
    defaulting to `brain_root` here caused the two to select different profiles in a
    brain with per-project rules.
    """
    try:
        resolved = resolve_profile(brain_root, cwd=cwd or brain_root)
    except ProfileError as error:
        return None, str(error)
    return set(resolved.document.get("capability_routes", {})), None


def _duplicate_field_keys(lines: list[str]) -> set[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for line in lines:
        match = FIELD_RE.match(line)
        if not match:
            continue
        key = match.group(1).strip().casefold()
        if key in seen:
            duplicates.add(key)
        seen.add(key)
    return duplicates


def _registry_descriptor_link_issue(entry: SourceEntry) -> str | None:
    """The registry's `Descriptor:` field is a validated cross-check, not a redirect:
    the descriptor path is always the deterministic `sources.<slug>.md`, never derived
    from this field. Keeping both a fixed path AND an authoritative field would let a
    registry entry silently point away from what it actually loads; keeping the field
    unvalidated (as before) let it silently disagree with what actually loads. Neither
    is acceptable, so the field must be present and name this exact slug."""
    targets = _link_target_basenames(entry.descriptor)
    expected = {f"sources.{entry.slug}", f"sources.{entry.slug}.md"}
    if not any(target in expected for target in targets):
        return "registry 'Descriptor' field is missing or does not name this slug"
    return None


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

    if entry.duplicate_fields:
        return blocked(
            f"duplicate field(s) in registry entry: {', '.join(sorted(entry.duplicate_fields))}"
        )

    descriptor_link_issue = _registry_descriptor_link_issue(entry)
    if descriptor_link_issue is not None:
        return blocked(descriptor_link_issue)

    descriptor_text, descriptor_issue = _read_source_file_or_issue(brain_root, descriptor_path, "descriptor")
    if descriptor_issue is not None:
        return blocked(descriptor_issue)

    if not entry.source_type:
        return blocked("missing source type")
    if not SOURCE_TYPE_RE.match(entry.source_type):
        return blocked(f"invalid source type: {entry.source_type!r}")
    guide_path = source_types_dir / f"{entry.source_type}.md"
    if not lstat_entry(guide_path).exists:
        return blocked(f"no guide for type {entry.source_type!r}")
    _, guide_issue = _read_source_file_or_issue(brain_root, guide_path, "source type guide")
    if guide_issue is not None:
        return blocked(guide_issue)

    descriptor_lines = descriptor_text.splitlines()
    duplicates = _duplicate_field_keys(descriptor_lines)
    if duplicates:
        return blocked(f"duplicate field(s) in descriptor: {', '.join(sorted(duplicates))}")
    fields = parse_fields(descriptor_lines)

    capability = fields.get("requires capability", "").strip()
    if not capability or not CAPABILITY_RE.match(capability):
        return blocked("missing or malformed 'Requires capability'")
    if profile_error is not None:
        return blocked(f"no usable environment profile: {profile_error}")
    if routed_capabilities is not None and capability not in routed_capabilities:
        return blocked(f"capability {capability!r} is not routed by the active profile")

    if not fields.get("locator", "").strip():
        return blocked("missing 'Locator'")

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

    if not fields.get("last status", "").strip():
        return blocked("missing 'Last status'")
    if "last checked" not in fields:
        return blocked("missing 'Last checked'")
    last_checked_raw = fields["last checked"].strip()
    never_checked = last_checked_raw.casefold() in NEVER_CHECKED_SENTINELS

    if cadence_days == 0:
        if never_checked:
            last_label = "none"
        else:
            try:
                last_label = date.fromisoformat(last_checked_raw).isoformat()
            except ValueError:
                return blocked(f"invalid 'Last checked' date: {last_checked_raw!r}")
        return SourceDecision(
            entry.slug, entry.source_type, True, False,
            "always due (cadence: always)", last_label, cadence_days,
        )

    if never_checked:
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


def decide_sources(brain_root: Path, today: date, cwd: Path | None = None) -> list[SourceDecision]:
    sources_dir = brain_root / "WIP" / "SOURCES"
    registry_path = sources_dir / "sources.registry.md"

    # Distinct from "no enabled entries" (a legitimate empty result): an activated
    # capability whose registry is missing, symlinked, or corrupt must be visible as
    # blocked, not indistinguishable from a brain that simply has nothing enabled yet.
    registry_text, registry_issue = _read_source_file_or_issue(brain_root, registry_path, "sources.registry.md")
    if registry_issue is not None:
        return [SourceDecision("(registry)", "", False, True, registry_issue, "none", 0)]

    # Duplicate slugs are computed across EVERY parsed entry, before filtering to
    # `enabled` -- an enabled section that shares a slug with a disabled one is just
    # as ambiguous as two enabled sections would be.
    all_entries = parse_registry_entries(registry_text)
    duplicate_slugs = {
        slug for slug in {entry.slug for entry in all_entries}
        if sum(1 for entry in all_entries if entry.slug == slug) > 1
    }
    entries = [entry for entry in all_entries if entry.status == "enabled"]
    routed_capabilities, profile_error = capability_routes(brain_root, cwd)

    decisions: list[SourceDecision] = []
    reported_duplicates: set[str] = set()
    for entry in entries:
        if entry.slug in duplicate_slugs:
            if entry.slug in reported_duplicates:
                continue
            reported_duplicates.add(entry.slug)
            decisions.append(
                SourceDecision(
                    entry.slug, entry.source_type, False, True,
                    "duplicate registry entry for this slug", "none", 0,
                )
            )
            continue
        decisions.append(decide_source(brain_root, entry, today, routed_capabilities, profile_error))
    return decisions


def summarize_due_sources(brain_root: Path, today: date, cwd: Path | None = None) -> list[str]:
    lines: list[str] = []
    for decision in decide_sources(brain_root, today, cwd):
        if decision.blocked:
            lines.append(f"- {decision.slug}: blocked — {decision.reason}")
        elif decision.due:
            type_label = decision.source_type or "unknown type"
            lines.append(f"- {decision.slug} ({type_label}): {decision.reason}")
    return lines


def _atomic_write(path: Path, content: str) -> None:
    """Write `content` to `path` via a uniquely named temp file created with
    O_EXCL|O_CREAT in the same directory, then an atomic rename.

    `tempfile.mkstemp()` fails outright if the generated name already exists in any
    form -- including a pre-planted symlink -- so it can never be tricked into opening
    through one and writing to an unrelated target the way a predictable `.tmp`
    sibling plus a plain `write_text()` could. The original file's mode is preserved
    explicitly: a freshly created file gets the process default mode, which would
    otherwise silently relax a private (e.g. 0600) descriptor to that default on every
    write.
    """
    original_mode = path.stat().st_mode & 0o777
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f"{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.chmod(tmp_name, original_mode)
        os.replace(tmp_name, path)
    except Exception:
        Path(tmp_name).unlink(missing_ok=True)
        raise


LAST_CHECKED_LINE_RE = re.compile(r"(?mi)^- Last checked:.*$")
LAST_STATUS_LINE_RE = re.compile(r"(?mi)^- Last status:.*$")


def _mark_checked_content_issue(text: str) -> str | None:
    """Whatever would make `mark_checked()` fail on this descriptor content, computed
    without writing anything -- shared by the dry-run and apply paths so a dry-run
    plan can never claim success where apply would deterministically fail.

    Case-insensitive, matching `parse_fields()`/`decide_source()`'s own casefolded
    field-name matching: a descriptor with `- last checked:` is accepted as due by the
    scheduler, so the writer must recognize the same line, not just the canonical
    casing, or a source that was due to be marked checked would be unmarkable.
    """
    checked_matches = LAST_CHECKED_LINE_RE.findall(text)
    status_matches = LAST_STATUS_LINE_RE.findall(text)
    if len(checked_matches) != 1 or len(status_matches) != 1:
        return "descriptor must have exactly one 'Last checked:'/'Last status:' line"
    return None


def mark_checked(descriptor_path: Path, today: date, status: str) -> None:
    if status not in VALID_STATUS:
        raise ValueError(f"invalid status: {status!r} (expected one of {VALID_STATUS})")
    if not descriptor_path.exists():
        raise FileNotFoundError(f"descriptor not found: {descriptor_path}")
    if descriptor_path.is_symlink():
        raise ValueError(f"descriptor must not be a symlink: {descriptor_path}")
    # _read_no_follow(), not plain read_text(): a swap from regular file to symlink
    # between the is_symlink() check above and this read must be rejected by the
    # open() call itself, not silently followed.
    try:
        text = _read_no_follow(descriptor_path)
    except OSError as error:
        raise ValueError(f"descriptor is not safely readable: {descriptor_path}: {error}") from error
    issue = _mark_checked_content_issue(text)
    if issue is not None:
        raise ValueError(f"{issue}: {descriptor_path}")
    text, _ = LAST_STATUS_LINE_RE.subn(f"- Last status: {status}", text, count=1)
    if status in WATERMARK_STATUSES:
        text, _ = LAST_CHECKED_LINE_RE.subn(f"- Last checked: {today.isoformat()}", text, count=1)
    # else: degraded leaves the watermark untouched so the source stays due for retry
    # and no unread window is silently skipped.
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
    list_due.add_argument(
        "--cwd",
        help="Session cwd used only to select an environment profile (default: brain root). "
        "Never affects which sources are evaluated -- source ingestion is brain-scoped.",
    )

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
        args.cwd = None
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

    try:
        content_issue = _mark_checked_content_issue(_read_no_follow(descriptor_path))
    except UnicodeDecodeError:
        content_issue = "descriptor is not valid UTF-8"
    except OSError as error:
        content_issue = f"descriptor is not safely readable: {error}"
    if content_issue is not None:
        # Checked before the dry-run/apply branch so a dry-run plan can never claim
        # success where apply would deterministically fail on the same input.
        reporter.write(f"mark-checked failed: {content_issue}")
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

    # The published contract is that this script also decides whether the capability
    # is active at all (TOOL.source-scheduler.md's own "Purpose"); list-due must not
    # dispatch a dormant brain's sources just because a caller bypassed the WIP.md
    # link check.
    activated = registry_activated(brain_root)
    cwd = Path(args.cwd).expanduser().resolve() if args.cwd else None
    decisions = decide_sources(brain_root, today, cwd) if activated else []
    if args.json:
        print(json.dumps(
            {"activated": activated, "decisions": [decision.__dict__ for decision in decisions]},
            ensure_ascii=False, indent=2,
        ))
    else:
        print("# Source scheduler")
        print(f"brain_root: {brain_root}")
        print(f"today: {today.isoformat()}")
        if not activated:
            print("dormant: no link to sources.registry in WIP/WIP.md")
            return 0
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
