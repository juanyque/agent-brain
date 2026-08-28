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
import stat
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
from _common import Reporter, build_command_string  # noqa: E402


SOURCE_HEADING_RE = re.compile(r"^###\s+(.+?)\s*$")
FIELD_RE = re.compile(r"^-\s+([A-Za-z][A-Za-z0-9 ()]*):\s*(.*?)\s*$")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
CAPABILITY_RE = re.compile(r"^[a-z][a-z0-9_.-]*$")
SOURCE_TYPE_RE = re.compile(r"^[a-z][a-z0-9-]*$")
# Requires an actual closing "]]": the old pattern only required the opening "[["
# and stopped capturing at "]"/"|"/"#", which never verified a closing "]]" existed
# at all -- an unclosed, malformed token like "[[sources.registry" (no closing
# brackets anywhere) was extracted as if it were a real, rendered wikilink. The
# interior may still carry a "|alias" and/or "#fragment"; those are split off by
# the caller after the full "[[...]]" shape is confirmed, not excluded here.
WIKILINK_TARGET_RE = re.compile(r"\[\[([^\[\]\n]+)\]\]")
# A Markdown link destination: either <...>-bracketed (CommonMark's form for a
# destination containing spaces) or a bare run of non-whitespace, non-")" characters
# (matching up to a "#fragment" is handled by the caller, not this regex, so both
# forms are trimmed the same way). An optional title (quoted, or parenthesized) may
# follow, separated by whitespace, before the closing ")" -- captured but discarded,
# so a titled link like `[x](y.md "Title")` still resolves to the destination alone.
MARKDOWN_LINK_TARGET_RE = re.compile(
    r"\]\(\s*(?:<(?P<angle>[^<>\n]*)>|(?P<bare>[^\s)]+))"
    r"(?:\s+(?:\"[^\"]*\"|'[^']*'|\([^()]*\)))?\s*\)"
)
# An unclosed HTML comment block runs through end of document under CommonMark
# (it is raw HTML, not prose, with no closing delimiter required) -- a "closed
# comments only" pattern would leave a later, unrendered Markdown link in place
# for the extractor to pick up as if it were live text.
HTML_COMMENT_RE = re.compile(r"<!--.*?(?:-->|\Z)", re.DOTALL)
# A fenced block opener: 3+ backticks or tildes, optionally indented 0-3 spaces
# (CommonMark's own fence-indentation allowance). Matching and removing an entire
# fenced region needs a length-aware CLOSING scan (a closer must have length >=
# the opener's, not exactly equal -- a single static regex backreference can only
# express "exactly equal", which incorrectly leaves a valid longer closer
# unrecognized) -- see `_strip_fenced_code()`.
FENCE_OPEN_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
# An inline code span: N backticks, content, the same N backticks again (CommonMark
# allows any run length, e.g. double backticks to embed a literal single backtick).
# Both delimiter runs must be MAXIMAL (not preceded/followed by another backtick):
# without the lookaround, a bare backreference lets a short opening run match as a
# PREFIX of a longer, unrelated closing run (e.g. an opening `` pairing against the
# first two backticks of a later ```), incorrectly treating a genuinely rendered
# link between mismatched-length runs as code and hiding it from activation.
INLINE_CODE_RE = re.compile(r"(?<!`)(`+)(?!`).*?(?<!`)\1(?!`)", re.DOTALL)
# Any URI scheme prefix (RFC 3986: scheme ":" ...), not only the hierarchical
# "scheme://" form -- a destination like `https:/x` or `mailto:/x` still has a
# scheme and is not a brain-relative path, but omitting "//" let it slip past a
# `://`-only check and be misread as local once its scheme was ignored.
URL_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
PROTOCOL_RELATIVE_RE = re.compile(r"^//")
# CommonMark allows a backslash to escape ASCII punctuation anywhere, including in a
# link destination; the escaped form (e.g. "sources\.registry.md") renders with the
# backslash removed, but the raw source text still has it, so a basename comparison
# against the un-unescaped text can never match. Not full URL-decoding, just this
# one specific, narrow CommonMark rule.
BACKSLASH_ESCAPE_RE = re.compile(r"\\(.)", re.DOTALL)
_ESCAPABLE_PUNCTUATION = frozenset("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~")
REGISTRY_LINK_BASENAMES = {"sources.registry", "sources.registry.md"}

VALID_STATUS = ("ok", "no_activity", "degraded")
WATERMARK_STATUSES = ("ok", "no_activity")
NEVER_CHECKED_SENTINELS = {"", "not checked", "none"}

# `Scan targets:` (optional, descriptor-authored) and `Quiet streak (checks):` (script-owned,
# like the two watermark fields) -- see mark_checked()/decide_source()/check-health.
SCAN_TARGETS_FIELD = "scan targets"
QUIET_STREAK_FIELD = "quiet streak (checks)"
# A hardcoded constant, not a per-source configurable field: keeps the advisory's scope to "one
# reasonable default" rather than one more thing every descriptor has to think about.
QUIET_STREAK_ADVISORY_THRESHOLD = 10
# A plain, unsigned, bounded decimal -- not whatever int() would accept (leading '+', a sign,
# underscores as digit separators, non-ASCII digits, or an arbitrarily long run of them). A
# corrupted counter must fail closed as "malformed", not be silently reinterpreted. `[0-9]`,
# not `\d`: `\d` is Unicode-aware by default and matches fullwidth/other non-ASCII decimal
# digits, which `int()` then happily normalizes -- silently accepting exactly the kind of
# value this pattern exists to reject.
QUIET_STREAK_VALUE_RE = re.compile(r"^[0-9]{1,9}$")


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


def _strip_one_backtick_pair(value: str) -> str:
    """A field value is often written as inline code (`` `issues.search` ``,
    `` `always` ``) -- natural Markdown style for a technical token. Strip one
    surrounding pair so parsing doesn't depend on the author's styling."""
    if len(value) >= 2 and value.startswith("`") and value.endswith("`"):
        return value[1:-1].strip()
    return value


def parse_fields(lines: list[str]) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in lines:
        match = FIELD_RE.match(line)
        if match:
            value = _strip_one_backtick_pair(match.group(2).strip())
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
                # "" (not "disabled") when the field is absent, so a missing
                # Status: is distinguishable from an explicit "Status: disabled" --
                # both are currently indeterminable to decide_sources() and must be
                # blocked and visible, not silently treated as an ordinary opt-out.
                # NOT casefolded: the contract requires the exact value "enabled"
                # or "disabled", and casefolding here would silently normalize a
                # non-canonical spelling like "ENABLED" into the canonical one
                # before decide_sources() ever got a chance to reject it.
                status=fields.get("status", "").strip(),
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


def _open_parent_no_follow(path: Path, safe_root: Path) -> tuple[int, str]:
    """Open `path`'s parent directory via a chain of O_DIRECTORY|O_NOFOLLOW opens
    starting at `safe_root`, walking one path component at a time with each `open()`
    relative to the previous one (`dir_fd=`). No intermediate component -- not just the
    leaf -- can be a symlink that redirects the eventual leaf open/write outside the
    brain: a swap of any directory along the way is rejected by the `open()` call for
    that specific component, not missed by an earlier, now-stale check.
    """
    parts = path.relative_to(safe_root).parts
    if not parts:
        raise OSError(f"refusing safe-root path as a file: {path}")
    directory_flags = (
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    descriptor = os.open(safe_root, directory_flags)
    try:
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise OSError(f"refusing non-directory safe root: {safe_root}")
        for part in parts[:-1]:
            next_descriptor = os.open(part, directory_flags, dir_fd=descriptor)
            if not stat.S_ISDIR(os.fstat(next_descriptor).st_mode):
                os.close(next_descriptor)
                raise OSError(f"refusing non-directory path component: {path}")
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor, parts[-1]
    except OSError:
        os.close(descriptor)
        raise


def _read_no_follow(path: Path, brain_root: Path) -> str:
    """Read `path` as UTF-8 text via the directory-fd chain in `_open_parent_no_follow()`,
    so a symlink swap anywhere along the path -- not only at the final component -- is
    rejected by the relevant `open()` call itself.

    The leaf open includes `O_NONBLOCK`: a FIFO with no writer would otherwise block
    indefinitely inside a plain blocking `open()`, well before the `S_ISREG` check
    below ever runs, hanging session start instead of yielding a blocked decision.
    `O_NONBLOCK` has no effect on an ordinary regular file's open or subsequent reads.
    """
    parent_fd, leaf = _open_parent_no_follow(path, brain_root)
    try:
        fd = os.open(
            leaf,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
            dir_fd=parent_fd,
        )
    finally:
        os.close(parent_fd)
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise OSError(f"not a regular file: {path}")
    with os.fdopen(fd, "r", encoding="utf-8") as handle:
        return handle.read()


def _read_source_file_or_issue(brain_root: Path, path: Path, label: str) -> tuple[str | None, str | None]:
    """Shared safety-and-read logic for the registry, a descriptor, or a source-type
    guide: the directory-fd chain in `_read_no_follow()` validates path shape (every
    component a real, non-symlinked directory; the leaf a real, non-symlinked regular
    file) as part of the same operation that reads it, rather than a separate shape
    check a race could invalidate before a subsequent plain open(). Returns
    (text, None) or (None, issue)."""
    try:
        return _read_no_follow(path, brain_root), None
    except (FileNotFoundError, NotADirectoryError):
        return None, f"{label} not found"
    except UnicodeDecodeError:
        return None, f"{label} is not valid UTF-8"
    except OSError as error:
        return None, f"{label} is not safely readable: {error}"


def _strip_fenced_code(text: str) -> str:
    """Remove every CommonMark fenced code block from `text`, line by line.

    A single static regex can express a closing fence's CHARACTER matching the
    opener's (backtick or tilde), but not its LENGTH constraint: CommonMark
    requires the closer to have at least as many characters as the opener, not
    exactly the same count. A backreference (`\\1`) can only express "exactly
    equal," which correctly rejects a too-short closer but also incorrectly
    rejects a valid, longer one -- leaving it to fall through to the "unclosed"
    case and swallow a genuinely rendered link after it. Scanning line by line
    lets the closing pattern be rebuilt per-opener with its actual length.
    """
    lines = text.split("\n")
    out: list[str] = []
    index = 0
    total = len(lines)
    while index < total:
        opener = FENCE_OPEN_RE.match(lines[index])
        if opener is None:
            out.append(lines[index])
            index += 1
            continue
        fence_char = opener.group(1)[0]
        fence_length = len(opener.group(1))
        closing_re = re.compile(rf"^ {{0,3}}{re.escape(fence_char)}{{{fence_length},}}[ \t]*$")
        closing_index = index + 1
        while closing_index < total and not closing_re.match(lines[closing_index]):
            closing_index += 1
        out.append("")
        # Unclosed (closing_index reached EOF without a match): the rest of the
        # document is code, per CommonMark's own unclosed-fence-to-EOF rule.
        index = closing_index + 1 if closing_index < total else total
    return "\n".join(out)


def _strip_indented_code(text: str) -> str:
    """Remove every CommonMark indented code block (4+ leading spaces, or a
    leading tab) from `text`, line by line.

    Not every 4-space-indented line is code: CommonMark's own rule is that an
    indented code block cannot INTERRUPT a paragraph -- a "    line" immediately
    following ordinary prose with no intervening blank line is a lazy
    continuation of that paragraph, rendered as ordinary text, not code. Only a
    blank line (or the start of the document, or an already-open code block)
    lets an indented line start a new code block. Treating every indented line
    as code regardless of context would hide a legitimately rendered link that
    merely happens to follow non-blank prose in the same paragraph.
    """
    lines = text.split("\n")
    out: list[str] = []
    in_code = False
    boundary = True
    for line in lines:
        is_blank = line.strip() == ""
        is_indented = line.startswith("    ") or line.startswith("\t")
        if in_code:
            if is_blank:
                out.append(line)
                continue
            if is_indented:
                out.append("")
                continue
            in_code = False
            boundary = False
        if is_blank:
            out.append(line)
            boundary = True
            continue
        if is_indented and boundary:
            in_code = True
            out.append("")
            continue
        out.append(line)
        boundary = False
    return "\n".join(out)


def _unescape_commonmark_punctuation(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        char = match.group(1)
        return char if char in _ESCAPABLE_PUNCTUATION else match.group(0)

    return BACKSLASH_ESCAPE_RE.sub(repl, text)


def _link_target_basenames(text: str) -> list[str]:
    """Every link target's basename in `text` -- wikilink and local Markdown links,
    alias/heading/fragment stripped -- so activation can compare exact filenames
    instead of a raw substring match (which would also match `not-sources.registry.md`
    or `sources.registry.backup`, and miss a valid link with a `#fragment`).

    Excludes: HTML comments, fenced code blocks (backtick or tilde, closed by a
    same-character run at least as long as the opener, or running to end of file
    if unclosed), indented code blocks (4+ leading spaces or a tab, unless the
    indentation is merely a paragraph's lazy continuation line), and inline code
    spans of any backtick-run length (a link shown only as example text is not a
    rendered link). Excludes external Markdown link
    destinations, both `scheme://...` and protocol-relative `//host/...` forms -- an
    external link that merely ends in a filename matching the registry's is not a
    local link to it. A `<...>`-bracketed destination (CommonMark's syntax for a
    destination containing spaces) is unwrapped by `MARKDOWN_LINK_TARGET_RE` itself,
    before the external/protocol-relative classification runs -- classifying the
    still-bracketed form first would let `(<https://...>)` slip past both checks
    (neither regex matches a leading `<`) and be misread as a local path. A
    backslash-escaped ASCII punctuation character (e.g. `` sources\\.registry.md ``) is
    unescaped before that same classification, since CommonMark renders the
    destination with the backslash removed -- comparing the still-escaped text could
    never match the registry's actual basename.
    """
    stripped = HTML_COMMENT_RE.sub("", text)
    stripped = _strip_fenced_code(stripped)
    stripped = _strip_indented_code(stripped)
    stripped = INLINE_CODE_RE.sub("", stripped)
    targets = [
        match.group(1).split("|", 1)[0].split("#", 1)[0].strip()
        for match in WIKILINK_TARGET_RE.finditer(stripped)
    ]
    for match in MARKDOWN_LINK_TARGET_RE.finditer(stripped):
        raw_target = match.group("angle") if match.group("angle") is not None else match.group("bare")
        raw_target = _unescape_commonmark_punctuation(raw_target)
        # Fragment stripping happens here, uniformly for both destination forms,
        # rather than excluding "#" from the regex's character classes -- the bare
        # alternative must still be able to stop at a title's leading whitespace.
        target = raw_target.split("#", 1)[0].strip()
        if not target or URL_SCHEME_RE.match(target) or PROTOCOL_RELATIVE_RE.match(target):
            continue
        targets.append(target)
    return [Path(target).name for target in targets if target]


def registry_activated(brain_root: Path) -> bool:
    """Whether source ingestion is switched on for this brain.

    Brain-scoped: a direct link to `sources.registry` anywhere in WIP/WIP.md activates
    the capability for the whole brain, with no per-project heading match and no
    presentational preview-length limit. A bare textual mention of the filename (e.g.
    prose that happens to say "sources.registry") is not enough -- an actual, local,
    rendered wikilink or Markdown link, resolved to its exact target basename, is
    required. See `_link_target_basenames()` for exactly what is excluded. Any read
    issue (missing, unsafe, unreadable, or undecodable WIP.md) is treated as dormant,
    matching the general fail-closed activation doctrine -- an unreadable dashboard
    must never abort session start.
    """
    text, _issue = _read_source_file_or_issue(brain_root, brain_root / "WIP" / "WIP.md", "WIP.md")
    if text is None:
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
    except (RuntimeError, OSError) as error:
        # resolve_profile() normalizes `cwd` with Path.resolve(), which raises
        # RuntimeError (not ProfileError) on a symlink loop, and can raise other
        # OSError subclasses on comparable path-resolution failures. A malformed
        # or raced `cwd` is exactly the kind of indeterminable input this function
        # already exists to turn into a blocked decision instead of an escaping
        # exception -- ProfileError alone doesn't cover it.
        return None, f"could not resolve session cwd: {error}"
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
    # Exactly one target, not "at least one": the documented contract
    # (TEMPLATE.source-registry.common.md) is a single wikilink naming this slug,
    # nothing else. Accepting the field whenever ANY extracted target matched let a
    # value naming both this slug and a second, conflicting one (e.g.
    # "[[sources.slug]] and [[sources.other]]") pass validation -- not a redirect
    # (the read still uses the deterministic path), but a silent loss of exactly
    # the ambiguous/stale-metadata detection this cross-check exists to provide.
    targets = _link_target_basenames(entry.descriptor)
    expected = {f"sources.{entry.slug}", f"sources.{entry.slug}.md"}
    if len(targets) != 1 or targets[0] not in expected:
        return "registry 'Descriptor' field must name exactly this slug"
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
    # No separate lstat_entry() preflight: it only distinguishes "missing" via
    # FileNotFoundError, so an unreadable SOURCE_TYPES/ directory (e.g. mode 000)
    # raised a bare PermissionError here instead of a blocked decision. The
    # hardened read below is the single authority for every outcome, missing
    # included -- it already maps FileNotFoundError/NotADirectoryError to a "not
    # found" issue string.
    guide_text, guide_issue = _read_source_file_or_issue(brain_root, guide_path, "source type guide")
    if guide_issue is not None:
        if guide_issue == "source type guide not found":
            return blocked(f"no guide for type {entry.source_type!r}")
        return blocked(guide_issue)
    if not guide_text.strip():
        return blocked("source type guide is empty")

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

    _, targets_issue = _declared_scan_targets(fields)
    if targets_issue is not None:
        return blocked(targets_issue)

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

    # Before the `always`-cadence early return below, not after: an `always` source
    # with a corrupted counter must be blocked here rather than dispatched forever --
    # mark_checked() would refuse to write the same malformed value, so leaving this
    # check only in the non-`always` path would make such a source perpetually due
    # and permanently unmarkable.
    _, streak_issue = _parse_quiet_streak(fields)
    if streak_issue is not None:
        return blocked(streak_issue)

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

    # A syntactically valid but extreme 'Last checked' date (e.g. 9999-12-31)
    # combined with any positive cadence overflows `date.max` on addition; an
    # arbitrarily large cadence can overflow `timedelta` construction itself. Either
    # is a malformed descriptor, not a crash -- block it like any other bad cadence.
    try:
        next_due = last_checked + timedelta(days=cadence_days)
    except OverflowError:
        return blocked("'Last checked' plus cadence overflows the representable date range")
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
    routed_capabilities, profile_error = capability_routes(brain_root, cwd)

    # Iterate every parsed entry, not just `enabled` ones: a duplicate slug is
    # reportable even when both colliding sections are `disabled` (the enabled-only
    # filter would silently drop that case, since neither entry would ever reach this
    # loop to be flagged). Entries that are not duplicates and not enabled are simply
    # skipped, unchanged from prior behavior.
    decisions: list[SourceDecision] = []
    reported_duplicates: set[str] = set()
    for entry in all_entries:
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
        if entry.status not in ("enabled", "disabled"):
            # A missing Status: field (now parsed as "", not defaulted to
            # "disabled") or an unrecognized value (e.g. a typo like "enabld") is
            # a fourth, indeterminable state the enabled/disabled filter below
            # would otherwise skip in total silence -- neither due nor visibly
            # blocked, so a mistyped field could stop ingestion for a source with
            # no diagnostic at all.
            decisions.append(
                SourceDecision(
                    entry.slug, entry.source_type, False, True,
                    f"missing or invalid registry 'Status': {entry.status!r}",
                    "none", 0,
                )
            )
            continue
        if entry.status != "enabled":
            # A duplicate FIELD (as opposed to a duplicate slug, handled above) is
            # still reportable even on a `disabled` entry: decide_source() would
            # catch it, but decide_source() is never called for a non-enabled
            # entry, so this loop -- not that function -- must surface it here.
            # This also makes the outcome order-independent when the duplicated
            # field is `Status:` itself: whichever value parse_fields() happened to
            # keep, the corruption is still flagged rather than silently skipped.
            if entry.duplicate_fields:
                decisions.append(
                    SourceDecision(
                        entry.slug, entry.source_type, False, True,
                        f"duplicate field(s) in registry entry: {', '.join(sorted(entry.duplicate_fields))}",
                        "none", 0,
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


@dataclass
class SourceHealth:
    slug: str
    source_type: str
    quiet_streak: int | None
    advisory: bool
    issue: str | None


def source_health(brain_root: Path) -> list[SourceHealth]:
    """Every enabled source's quiet-streak advisory state -- purely informational,
    descriptor-local, and read-only: no capability/profile resolution (an advisory
    has nothing to do with which environment profile a session's cwd selects), and
    nothing here ever writes, blocks a session, or disables a source.

    Mirrors `decide_sources()`'s own visibility doctrine (an unreadable registry, a
    duplicate slug, or an invalid `Status:` is reported rather than silently
    dropped) without duplicating its due/blocked decision logic, which is entirely
    irrelevant to a quiet-streak advisory.
    """
    sources_dir = brain_root / "WIP" / "SOURCES"
    registry_path = sources_dir / "sources.registry.md"

    registry_text, registry_issue = _read_source_file_or_issue(brain_root, registry_path, "sources.registry.md")
    if registry_issue is not None:
        return [SourceHealth("(registry)", "", None, False, registry_issue)]

    all_entries = parse_registry_entries(registry_text)
    duplicate_slugs = {
        slug for slug in {entry.slug for entry in all_entries}
        if sum(1 for entry in all_entries if entry.slug == slug) > 1
    }

    results: list[SourceHealth] = []
    reported_duplicates: set[str] = set()
    for entry in all_entries:
        if entry.slug in duplicate_slugs:
            if entry.slug in reported_duplicates:
                continue
            reported_duplicates.add(entry.slug)
            results.append(
                SourceHealth(entry.slug, entry.source_type, None, False, "duplicate registry entry for this slug")
            )
            continue
        if entry.status not in ("enabled", "disabled"):
            results.append(
                SourceHealth(
                    entry.slug, entry.source_type, None, False,
                    f"missing or invalid registry 'Status': {entry.status!r}",
                )
            )
            continue
        # A duplicate registry FIELD (as opposed to a duplicate slug, handled
        # above) is reportable regardless of status -- checked before the
        # enabled/disabled branch below, not after, so a disabled entry (or one
        # whose duplicated field is `Status:` itself, landing on "disabled" as
        # whichever value parse_fields() happened to keep) doesn't silently
        # disappear from health output instead of surfacing the corruption.
        if entry.duplicate_fields:
            results.append(
                SourceHealth(
                    entry.slug, entry.source_type, None, False,
                    f"duplicate field(s) in registry entry: {', '.join(sorted(entry.duplicate_fields))}",
                )
            )
            continue
        if entry.status != "enabled":
            continue
        try:
            descriptor_path = descriptor_path_for(sources_dir, entry.slug)
        except ValueError as error:
            # A registry heading is parsed as an arbitrary string, not validated
            # against SLUG_RE anywhere upstream -- mirrors decide_source()'s own
            # try/except around the same call, so a malformed slug is reported the
            # same informational way here instead of raising past this function.
            results.append(SourceHealth(entry.slug, entry.source_type, None, False, str(error)))
            continue
        descriptor_text, descriptor_issue = _read_source_file_or_issue(brain_root, descriptor_path, "descriptor")
        if descriptor_issue is not None:
            results.append(SourceHealth(entry.slug, entry.source_type, None, False, descriptor_issue))
            continue
        fields = parse_fields(descriptor_text.splitlines())
        duplicates = _duplicate_field_keys(descriptor_text.splitlines())
        if duplicates:
            results.append(
                SourceHealth(
                    entry.slug, entry.source_type, None, False,
                    f"duplicate field(s) in descriptor: {', '.join(sorted(duplicates))}",
                )
            )
            continue
        streak, streak_issue = _parse_quiet_streak(fields)
        if streak_issue is not None:
            results.append(SourceHealth(entry.slug, entry.source_type, None, False, streak_issue))
            continue
        results.append(
            SourceHealth(entry.slug, entry.source_type, streak, streak >= QUIET_STREAK_ADVISORY_THRESHOLD, None)
        )
    return results


def _atomic_write(path: Path, content: str, brain_root: Path) -> None:
    """Write `content` to `path` via a uniquely named temp file created with
    O_EXCL|O_CREAT in the same directory, then an atomic rename -- all relative to a
    parent directory file descriptor opened through `_open_parent_no_follow()`.

    A pathname-based `tempfile.mkstemp(dir=path.parent, ...)` resolves `path.parent`
    fresh at call time: if any directory component between `brain_root` and `path` is
    swapped for a symlink after the caller's own checks but before this call, the temp
    file (and then the final rename target) is created and replaced inside whatever
    external directory the symlink now points to. Opening the parent through the
    dir-fd chain instead means every component was verified to be a real directory,
    under `brain_root`, at the moment it was opened -- a later swap of any of them
    cannot redirect an already-open descriptor.

    `O_EXCL|O_CREAT` still guards the temp name itself: it fails outright if the
    generated name already exists in any form -- including a pre-planted symlink --
    so it can never be tricked into opening through one. The original file's mode is
    preserved explicitly: a freshly created file gets the process default mode, which
    would otherwise silently relax a private (e.g. 0600) descriptor to that default on
    every write. `os.rename()`, not `os.replace()`: `os.replace` does not support
    `dir_fd` on every platform this runs on, while POSIX `rename()` already atomically
    overwrites an existing destination -- the `replace`/`rename` distinction only
    matters on Windows.
    """
    parent_fd, leaf = _open_parent_no_follow(path, brain_root)
    try:
        # follow_symlinks=False, not a plain stat(): the caller's own no-follow read
        # happens strictly before this call, leaving a window for the leaf to be
        # swapped for a symlink in between. A default follow_symlinks=True stat would
        # silently copy the symlink TARGET's mode onto the new temp file instead of
        # rejecting the swap -- recreating a private descriptor world-readable if the
        # target happens to be, without ever touching the target itself.
        leaf_status = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
        if not stat.S_ISREG(leaf_status.st_mode):
            raise OSError(f"refusing to write a non-regular-file target: {path}")
        original_mode = leaf_status.st_mode & 0o777
        tmp_name = f"{leaf}.{os.getpid()}.{os.urandom(8).hex()}.tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(tmp_name, flags, 0o600, dir_fd=parent_fd)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(content)
            os.chmod(tmp_name, original_mode, dir_fd=parent_fd)
            os.rename(tmp_name, leaf, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        except Exception:
            try:
                os.unlink(tmp_name, dir_fd=parent_fd)
            except OSError:
                pass
            raise
    finally:
        os.close(parent_fd)


# `-\s+`, not a literal single space, matching FIELD_RE's own whitespace tolerance:
# a descriptor with e.g. "-  Last checked:" (two spaces) is parsed as the field by
# decide_source() and must be recognized as the same field here, or a source
# decide_source() returns as due becomes one mark_checked() refuses to write.
LAST_CHECKED_LINE_RE = re.compile(r"(?mi)^-\s+Last checked:.*$")
LAST_STATUS_LINE_RE = re.compile(r"(?mi)^-\s+Last status:.*$")
# Same `-\s+` tolerance, for the same reason, applied to the third script-owned field.
QUIET_STREAK_LINE_RE = re.compile(r"(?mi)^-\s+Quiet streak \(checks\):.*$")


def _parse_target_list(raw: str) -> tuple[tuple[str, ...] | None, str | None]:
    """Split a comma-separated list of opaque scan-target identifiers, tolerating
    surrounding whitespace around each one. Returns `(tokens, None)` or
    `(None, issue)`. Used for both a descriptor's declared `Scan targets:` and a
    `--scanned` claim -- the same shape, the same rules.

    No per-token backtick handling here: a declared `Scan targets:` value already
    gets ONE backtick pair stripped from the WHOLE field by `parse_fields()` (the
    same convenience every other field value gets, e.g. `` `issues.search` ``), so
    wrapping the entire list once (`` `a, b, c` ``) already works for free. Wrapping
    each identifier individually would collide with that whole-value stripping
    (the first and last identifier's backticks would be consumed as the field's
    own pair, not each token's), so it is intentionally not supported.
    """
    if not raw.strip():
        return None, "empty value"
    tokens: list[str] = []
    for piece in raw.split(","):
        token = piece.strip()
        if not token:
            return None, "an identifier in the list is empty"
        # str.isprintable(), not an ASCII-only control-character regex: the ASCII
        # C0/DEL range alone misses Unicode C1 controls (e.g. U+009B, an ANSI CSI
        # introducer), which would otherwise reach terminal/log diagnostics
        # verbatim when a declared target goes unreported by --scanned.
        if not token.isprintable():
            return None, "an identifier contains a non-printable character"
        tokens.append(token)
    return tuple(tokens), None


def _declared_scan_targets(fields: dict[str, str]) -> tuple[tuple[str, ...] | None, str | None]:
    """`(None, None)` when `Scan targets:` is absent -- the source does not fan out
    to multiple targets, and every coverage rule below is simply skipped, unchanged
    from before this feature existed. `(tokens, None)` for a valid declaration.
    `(None, issue)` when the field is present but malformed."""
    raw = fields.get(SCAN_TARGETS_FIELD)
    if raw is None:
        return None, None
    tokens, issue = _parse_target_list(raw)
    if issue is not None:
        return None, f"malformed 'Scan targets': {issue}"
    return tokens, None


def _coverage_issue(declared: tuple[str, ...] | None, scanned: str | None, status: str) -> str | None:
    """Whether a `--scanned` claim satisfies a descriptor's declared `Scan targets:`
    for the given status -- the whole of the coverage-manifest policy, in one place,
    so the dry-run preview and the actual write can never disagree about it.

    `ok`/`no_activity` are completeness claims ("I checked and here's what I found");
    `degraded` is not ("I could not complete this check"), so it never requires or
    validates `--scanned` -- consistent with `degraded` already leaving the watermark
    untouched. Coverage must be a SUPERSET of the declared set: scanning more than
    required is fine, scanning less is exactly the gap this feature exists to catch.
    """
    if declared is None:
        if scanned is not None:
            return "descriptor declares no 'Scan targets': --scanned is not accepted"
        return None
    if status not in WATERMARK_STATUSES:
        return None
    if scanned is None:
        return f"descriptor declares 'Scan targets': --scanned is required for status {status!r}"
    scanned_tokens, issue = _parse_target_list(scanned)
    if issue is not None:
        return f"malformed --scanned: {issue}"
    missing = sorted(target for target in declared if target not in scanned_tokens)
    if missing:
        return "incomplete coverage: --scanned is missing declared scan target(s): " + ", ".join(missing)
    return None


def _parse_quiet_streak(fields: dict[str, str]) -> tuple[int, str | None]:
    """`(0, None)` when `Quiet streak (checks):` is absent -- absent means zero,
    the same as a freshly templated descriptor. `(n, None)` for a valid counter.
    `(0, issue)` when the field is present but not a plain, bounded, unsigned
    decimal -- not whatever `int()` would otherwise accept (a leading sign,
    underscore digit separators, non-ASCII digits, an unbounded number of digits)."""
    raw = fields.get(QUIET_STREAK_FIELD)
    if raw is None:
        return 0, None
    if not QUIET_STREAK_VALUE_RE.match(raw):
        return 0, f"malformed 'Quiet streak (checks)': {raw!r}"
    return int(raw), None


_QUIET_STREAK_MAX = 999_999_999  # the largest value QUIET_STREAK_VALUE_RE accepts


def _next_quiet_streak(current: int, status: str) -> int | None:
    """The streak value after this check, or `None` to leave the field completely
    untouched -- a `degraded` check tells us nothing about actual activity, so it
    must not reset OR advance the streak, matching its existing watermark behavior.

    Saturates at `_QUIET_STREAK_MAX` rather than incrementing past it: the counter
    is purely advisory, and every value at or above the (much lower) advisory
    threshold already means the same thing, so there is nothing to gain from an
    unbounded counter -- and incrementing one already at the grammar's own maximum
    would otherwise write a value `_parse_quiet_streak()` itself then rejects as
    malformed on the very next read.
    """
    if status == "no_activity":
        return min(current + 1, _QUIET_STREAK_MAX)
    if status == "ok":
        return 0
    return None


def _quiet_streak_needs_write(next_streak: int | None, fields: dict[str, str]) -> bool:
    """Whether writing the streak has anything to say: `None` means `degraded`
    (never written); otherwise skip only when there is no prior field AND nothing
    to reset it to, so an ordinary descriptor that has never gone quiet stays
    byte-identical after an `ok` check. Shared by `mark_checked()`'s actual write
    and `run_mark_checked()`'s dry-run preview so the two can never disagree about
    whether a line would change."""
    return next_streak is not None and (next_streak != 0 or QUIET_STREAK_FIELD in fields)


def _set_or_insert_quiet_streak(text: str, value: int) -> str:
    """Write `value` into the descriptor's `Quiet streak (checks):` line: update it
    in place if present, or insert a new line immediately after `Last status:` if
    absent -- an anchor guaranteed to exist and be unique by the time this runs
    (`_mark_checked_content_issue()` already required exactly one). A function
    replacement, never a template string, so `value` (always a plain int here) can
    never be misread as a regex backreference."""
    replacement = f"- Quiet streak (checks): {value}"
    if QUIET_STREAK_LINE_RE.search(text):
        return QUIET_STREAK_LINE_RE.sub(lambda _match: replacement, text, count=1)
    return LAST_STATUS_LINE_RE.sub(lambda match: match.group(0) + f"\n{replacement}", text, count=1)


def _mark_checked_content_issue(text: str, status: str, scanned: str | None) -> str | None:
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
    # _duplicate_field_keys(), not a second field-specific line-count regex: it
    # already casefolds field names the same way parse_fields() does, so it also
    # catches two case-varied lines (e.g. "Scan targets:" + "scan targets:") that a
    # single exact-string regex count would treat as unrelated. decide_source()
    # already rejects any duplicated field via this same helper before a source is
    # ever dispatched; mark_checked() must reach the same conclusion independently,
    # since it can be invoked without decide_source() ever having run.
    duplicate_field_keys = _duplicate_field_keys(text.splitlines())
    if SCAN_TARGETS_FIELD in duplicate_field_keys:
        return "descriptor must have at most one 'Scan targets:' line"
    if QUIET_STREAK_FIELD in duplicate_field_keys:
        return "descriptor must have at most one 'Quiet streak (checks):' line"
    fields = parse_fields(text.splitlines())
    _, streak_issue = _parse_quiet_streak(fields)
    if streak_issue is not None:
        return streak_issue
    declared, targets_issue = _declared_scan_targets(fields)
    if targets_issue is not None:
        return targets_issue
    return _coverage_issue(declared, scanned, status)


def mark_checked(
    descriptor_path: Path, today: date, status: str, brain_root: Path, scanned: str | None = None
) -> None:
    if status not in VALID_STATUS:
        raise ValueError(f"invalid status: {status!r} (expected one of {VALID_STATUS})")
    # _read_no_follow(), not an exists()/is_symlink() pre-check plus a plain
    # read_text(): both the leaf and every parent directory component are opened
    # through a dir-fd chain rooted at `brain_root`, so a swap of the descriptor
    # itself -- or of any directory between it and the brain root -- after an earlier
    # check is rejected by the open() calls themselves, not silently followed.
    try:
        text = _read_no_follow(descriptor_path, brain_root)
    except (FileNotFoundError, NotADirectoryError) as error:
        raise FileNotFoundError(f"descriptor not found: {descriptor_path}") from error
    except OSError as error:
        raise ValueError(f"descriptor is not safely readable: {descriptor_path}: {error}") from error
    issue = _mark_checked_content_issue(text, status, scanned)
    if issue is not None:
        raise ValueError(f"{issue}: {descriptor_path}")
    # Recomputed from THIS read, not passed in from a caller's earlier snapshot (e.g.
    # run_mark_checked()'s dry-run preview): the same independent-read discipline
    # `_read_no_follow()` itself follows, so a descriptor swapped between an earlier
    # check and this write is judged on what is actually about to be written.
    fields = parse_fields(text.splitlines())
    current_streak, _ = _parse_quiet_streak(fields)
    next_streak = _next_quiet_streak(current_streak, status)
    text, _ = LAST_STATUS_LINE_RE.subn(f"- Last status: {status}", text, count=1)
    if status in WATERMARK_STATUSES:
        text, _ = LAST_CHECKED_LINE_RE.subn(f"- Last checked: {today.isoformat()}", text, count=1)
    # else: degraded leaves the watermark untouched so the source stays due for retry
    # and no unread window is silently skipped.
    if _quiet_streak_needs_write(next_streak, fields):
        text = _set_or_insert_quiet_streak(text, next_streak)
    _atomic_write(descriptor_path, text, brain_root)


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
    mark.add_argument(
        "--scanned",
        help="Comma-separated identifiers actually covered by this check. Required when the "
        "descriptor declares 'Scan targets:' and --status is ok or no_activity; must cover "
        "every declared target (covering more is fine). Never written to the descriptor.",
    )

    health = subparsers.add_parser(
        "check-health",
        help="Report enabled sources whose quiet streak has reached the advisory threshold "
        "(read-only, informational only -- never blocks or disables a source)",
    )
    health.add_argument("--json", action="store_true", help="Print machine-readable JSON")

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


def _single_line(text: str) -> str:
    """Escape any control character (in particular a newline) to a visible `\\xHH`
    sequence before writing untrusted text to the audit log. `build_command_string()`
    shell-quotes each argument, but `shlex.quote()` only makes a value shell-safe to
    RE-RUN -- it does not strip an embedded newline, so an unvalidated `--scanned`
    (echoed here before its own validation ever runs) could otherwise make the
    logged command line span multiple lines and forge what looks like a distinct,
    later, successful log entry."""
    return "".join(f"\\x{ord(char):02x}" if ord(char) < 0x20 or ord(char) == 0x7F else char for char in text)


def run_mark_checked(
    brain_root: Path, today: date, source: str, status: str, apply: bool, scanned: str | None = None
) -> int:
    log_path = SCRIPT_DIR / "source_scheduler.log"
    reporter = Reporter(log_path)
    reporter.write("# Source scheduler: mark-checked")
    reporter.write(f"mode: {'apply' if apply else 'dry-run'}")
    reporter.write(f"brain_root: {brain_root}")
    reporter.write(f"command: {_single_line(build_command_string())}")
    reporter.write("")

    sources_dir = brain_root / "WIP" / "SOURCES"
    try:
        descriptor_path = descriptor_path_for(sources_dir, source)
    except ValueError as error:
        reporter.write(f"mark-checked failed: {error}")
        reporter.flush()
        return 1

    # Delegates the entire "is this descriptor safely readable" question to the same
    # hardened, dir-fd-chained read the decision path and the writer both use --
    # rather than duplicating a separate lstat-based pre-check here that could drift
    # out of sync with what `mark_checked()` itself actually enforces.
    descriptor_text, descriptor_issue = _read_source_file_or_issue(brain_root, descriptor_path, "descriptor")
    if descriptor_issue is not None:
        reporter.write(f"mark-checked failed: {descriptor_issue}")
        reporter.flush()
        return 1
    content_issue = _mark_checked_content_issue(descriptor_text, status, scanned)
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

    # Preview only -- computed from this snapshot for the reporter's benefit; the
    # authoritative recomputation happens again inside mark_checked() from its own
    # independent read, and that is the one that actually governs the write.
    fields = parse_fields(descriptor_text.splitlines())
    declared, _ = _declared_scan_targets(fields)
    if declared is not None:
        if status in WATERMARK_STATUSES:
            scanned_tokens, _ = _parse_target_list(scanned)
            extra = len(set(scanned_tokens) - set(declared))
            line = f"  coverage: {len(declared)}/{len(declared)} declared scan target(s) covered"
            if extra:
                line += f" ({extra} additional identifier(s) reported)"
            reporter.write(line)
        else:
            reporter.write("  coverage: not required (degraded)")
            if scanned is not None:
                scanned_tokens, scanned_issue = _parse_target_list(scanned)
                if scanned_issue is None:
                    reporter.write(f"  reported scanned: {len(scanned_tokens)} identifier(s)")
    current_streak, _ = _parse_quiet_streak(fields)
    next_streak = _next_quiet_streak(current_streak, status)
    if next_streak is None:
        reporter.write("  Quiet streak (checks): unchanged (degraded)")
    elif _quiet_streak_needs_write(next_streak, fields):
        reset_note = " (reset)" if next_streak == 0 else ""
        reporter.write(f"  Quiet streak (checks): {current_streak} -> {next_streak}{reset_note}")

    if not apply:
        reporter.write("")
        reporter.write("(dry-run: no file changed. Re-run with --apply.)")
        reporter.flush()
        return 0

    try:
        mark_checked(descriptor_path, today, status, brain_root, scanned)
    except (OSError, ValueError) as error:
        # OSError, not just the FileNotFoundError/ValueError mark_checked() itself
        # raises deliberately: an environmental write failure (e.g. a non-writable
        # SOURCES/ directory) surfaces as a raw OSError from _atomic_write(), which
        # this call passes through unchanged -- it must be reported the same way as
        # any other mark-checked failure, not escape as an uncaught traceback after
        # the plan was already logged.
        reporter.write(f"mark-checked failed: {error}")
        reporter.flush()
        return 1
    reporter.write("  applied.")
    reporter.flush()
    return 0


def run_check_health(brain_root: Path, as_json: bool) -> int:
    """Read-only, informational only: never writes, never advances a watermark,
    never disables a source, always exits 0 (barring an unusable brain root).
    Dormant/`--json` contract mirrors `list-due`'s exactly."""
    activated = registry_activated(brain_root)
    sources = source_health(brain_root) if activated else []

    if as_json:
        print(json.dumps(
            {
                "activated": activated,
                "threshold": QUIET_STREAK_ADVISORY_THRESHOLD,
                "sources": [health.__dict__ for health in sources],
            },
            ensure_ascii=False, indent=2,
        ))
        return 0

    print("# Source scheduler: health")
    print(f"brain_root: {brain_root}")
    print(f"threshold: {QUIET_STREAK_ADVISORY_THRESHOLD} consecutive quiet checks")
    if not activated:
        print("dormant: no link to sources.registry in WIP/WIP.md")
        return 0

    advisories = [health for health in sources if health.advisory]
    unknown = [health for health in sources if health.issue is not None]
    if not advisories and not unknown:
        print(f"no advisories: no enabled source has reached {QUIET_STREAK_ADVISORY_THRESHOLD} consecutive quiet checks.")
        return 0

    if advisories:
        print()
        print("## Advisories")
        for health in advisories:
            type_label = health.source_type or "unknown type"
            print(
                f"- {health.slug} ({type_label}): quiet streak {health.quiet_streak} checks "
                f"(threshold {QUIET_STREAK_ADVISORY_THRESHOLD})"
            )
            print(
                f"  advisory: nothing has been found here for {health.quiet_streak} consecutive "
                "checks -- reconsider whether this source is still worth checking, or whether its "
                "Locator has gone stale. No action taken."
            )
    if unknown:
        print()
        print("## Health unknown")
        for health in unknown:
            print(f"- {health.slug}: {health.issue}")
    return 0


def main() -> int:
    args = parse_args()
    brain_root = Path(args.brain_root).expanduser().resolve()
    if not brain_root.is_dir():
        print(f"Brain root not found: {brain_root}")
        return 1

    # Dispatched before any --date parsing: check-health needs neither `today` nor
    # `--cwd` (it is descriptor-local, read-only advice), and its subparser defines
    # no --date argument at all -- reading `args.date` for it would raise
    # AttributeError, exactly the uncaught-traceback failure mode every other
    # subcommand here is already guarded against.
    if args.command == "check-health":
        return run_check_health(brain_root, args.json)

    if args.date:
        try:
            today = date.fromisoformat(args.date)
        except ValueError:
            print(f"Invalid --date value: {args.date!r} (expected YYYY-MM-DD)")
            return 1
    else:
        today = datetime.now().date()

    if args.command == "mark-checked":
        return run_mark_checked(brain_root, today, args.source, args.status, args.apply, args.scanned)

    # The published contract is that this script also decides whether the capability
    # is active at all (TOOL.source-scheduler.md's own "Purpose"); list-due must not
    # dispatch a dormant brain's sources just because a caller bypassed the WIP.md
    # link check.
    activated = registry_activated(brain_root)
    cwd = None
    if args.cwd:
        try:
            cwd = Path(args.cwd).expanduser().resolve()
        except (RuntimeError, OSError) as error:
            print(f"Invalid --cwd value: {args.cwd!r} ({error})")
            return 1
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
