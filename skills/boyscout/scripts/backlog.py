#!/usr/bin/env python3
"""Owns the boyscout backlog file format.

The boyscout backlog (`~/.boyscout/backlog.md` by default) is a Markdown file
the skill mutates across sessions. Doing that with prose "surgical edit" rules
is fragile — a dropped `###` heading once orphaned an entry under its neighbour.
This script makes the format an enforceable contract instead of a convention.

Subcommands:
  list         List findings (optionally filtered by target/type/stale).
  add          Append a new finding under its target section.
  remove       Delete a finding block by target + summary.
  touch        Bump last_seen / increment times_seen on a dedup match.
  sweep        Report (or remove) stale findings (last_seen older than N days).
  dedup-check  Report findings sharing the same (target, summary). Non-zero if any.
  validate     Assert structural integrity (every property block has a `###`
               heading parent) + anti-provenance lint. Non-zero on violation.

The file MAY be a symlink (e.g. into an Obsidian vault). Python file I/O follows
the link transparently, so this script works where the Claude Code harness
refuses Edit/Write through a symlink. Always edit via this script, not by hand.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
import tempfile

DEFAULT_FILE = os.path.expanduser("~/.boyscout/backlog.md")
# Set from --allow-foreign-file in main(); gates writes outside $HOME / the temp dir.
_ALLOW_FOREIGN = False
HEADING_RE = re.compile(r"^###\s+(?:\[(?P<effort>[^\]]*)\]\[(?P<type>[^\]]*)\]\s*)?(?P<summary>.+?)\s*$")
TARGET_RE = re.compile(r"^##\s+(?P<target>.+?)\s*$")
PROP_RE = re.compile(r"^-\s+(?P<key>[A-Za-z_][\w-]*):\s?(?P<value>.*)$")
# Provenance annotations that git history + session notes already cover.
BANNED_PROP_KEYS = {"version", "session", "session_id", "added_by", "author", "commit"}


class Finding:
    def __init__(self, target, effort, type_, summary, start):
        self.target = target
        self.effort = effort
        self.type = type_
        self.summary = summary
        self.fields = {}          # key -> value (first occurrence wins)
        self.start = start        # line index of the `### ` heading
        self.end = start          # exclusive end line index (set during parse)
        self.lines = []           # raw body lines including the heading

    def to_dict(self):
        return {
            "target": self.target,
            "effort": self.effort,
            "type": self.type,
            "summary": self.summary,
            **self.fields,
        }


def read_lines(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read().split("\n")


def _path_allowed(path):
    """True if `path` resolves under $HOME or the system temp dir.

    Least-privilege guard: the `Bash(python3 scripts/backlog.py:*)` grant pre-approves
    any `--file`, so without this a crafted invocation could overwrite an arbitrary
    writable file. Real backlogs live under $HOME (incl. a vault symlink, which realpath
    resolves into $HOME); tests use the temp dir. Anything else needs --allow-foreign-file.
    """
    real = os.path.realpath(path)
    home = os.path.realpath(os.path.expanduser("~"))
    tmp = os.path.realpath(tempfile.gettempdir())
    return real == home or real.startswith(home + os.sep) or real.startswith(tmp + os.sep)


def write_lines(path, lines):
    if not _ALLOW_FOREIGN and not _path_allowed(path):
        raise SystemExit(f"backlog.py: refusing to write outside $HOME or temp: {path} "
                         "(pass --allow-foreign-file to override)")
    parent = os.path.dirname(path)
    if parent:  # empty for a bare relative filename — makedirs("") would raise
        os.makedirs(parent, exist_ok=True)
    # `lines` is a split on "\n"; re-join preserves the original trailing newline shape.
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


def parse(lines):
    """Return (findings, problems).

    A *problem* is a structural defect: a property line that is not under a
    `###` heading (the orphan corruption), or a `###` not under a `##` target.
    """
    findings = []
    problems = []
    current_target = None
    current = None       # the Finding being built
    in_finding = False   # True between a `### ` line and the next `---`/`##`/`###`/EOF

    def close(end_idx):
        nonlocal current
        if current is not None:
            current.end = end_idx
            findings.append(current)
            current = None

    for i, raw in enumerate(lines):
        line = raw.rstrip("\n")
        tmatch = TARGET_RE.match(line)
        hmatch = HEADING_RE.match(line)
        if tmatch and not line.startswith("###"):
            close(i)
            current_target = tmatch.group("target")
            in_finding = False
            continue
        if hmatch:
            close(i)
            if current_target is None:
                problems.append((i + 1, "### heading with no parent ## target section"))
            current = Finding(current_target, hmatch.group("effort"),
                              hmatch.group("type"), hmatch.group("summary"), i)
            current.lines.append(line)
            in_finding = True
            continue
        if line.strip() == "---":
            close(i)
            in_finding = False
            continue
        pmatch = PROP_RE.match(line)
        if pmatch:
            if not in_finding or current is None:
                problems.append((i + 1, f"property line '- {pmatch.group('key')}:' has no ### heading parent (orphaned block)"))
            else:
                current.lines.append(line)
                current.fields.setdefault(pmatch.group("key"), pmatch.group("value").strip())
            continue
        # Any other line (blank, prose, comment): keep it in the current block if open.
        if current is not None and in_finding:
            current.lines.append(line)
    close(len(lines))
    return findings, problems


def parse_date(value):
    """Extract a YYYY-MM-DD prefix from a field value, or None."""
    if not value:
        return None
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", value)
    if not m:
        return None
    try:
        return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_validate(args):
    lines = read_lines(args.file)
    if not lines:
        print(f"validate: {args.file} is empty or missing — nothing to check.")
        return 0
    findings, problems = parse(lines)
    errors = list(problems)

    for f in findings:
        if "status" not in f.fields:
            errors.append((f.start + 1, f"finding '{f.summary}' has no '- status:' field"))
        # Anti-provenance lint: banned provenance fields and in-block HTML comments.
        for key in f.fields:
            if key in BANNED_PROP_KEYS:
                errors.append((f.start + 1, f"finding '{f.summary}' carries provenance field '- {key}:' "
                                           "(git history + session notes cover provenance — remove it)"))
        for ln in f.lines:
            # Flag only a standalone annotation comment line, not a property whose VALUE
            # legitimately contains "<!--" (e.g. a finding describing a `<!-- code-review -->`
            # bot tag). The rule targets `<!-- added in session X -->`-style noise.
            if ln.strip().startswith("<!--"):
                errors.append((f.start + 1, f"finding '{f.summary}' contains a standalone HTML comment "
                                           "(anti-provenance: do not annotate entries with comments)"))
                break

    if errors:
        print(f"validate: FAIL — {len(errors)} problem(s) in {args.file}:", file=sys.stderr)
        for lineno, msg in sorted(errors):
            print(f"  line {lineno}: {msg}", file=sys.stderr)
        return 1
    print(f"validate: OK — {len(findings)} finding(s), structure and provenance clean.")
    return 0


def cmd_list(args):
    lines = read_lines(args.file)
    findings, _ = parse(lines)
    today = datetime.date.today()
    out = []
    for f in findings:
        if args.target and f.target != args.target:
            continue
        if args.type and f.type != args.type:
            continue
        stale = False
        ls = parse_date(f.fields.get("last_seen"))
        if ls is not None and (today - ls).days > args.stale_days:
            stale = True
        if args.stale and not stale:
            continue
        d = f.to_dict()
        d["stale"] = stale
        out.append(d)
    if args.json:
        print(json.dumps(out, indent=2))
    else:
        if not out:
            print("(no matching findings)")
        for d in out:
            flag = " [STALE?]" if d.get("stale") else ""
            print(f"[{d.get('effort','?')}][{d.get('type','?')}] {d['summary']}{flag}")
            print(f"    target: {d['target']}  ·  times_seen: {d.get('times_seen','?')}  ·  last_seen: {d.get('last_seen','?')}")
    return 0


def _find_block(findings, target, summary):
    matches = [f for f in findings if f.target == target and f.summary.strip() == summary.strip()]
    if not matches:
        matches = [f for f in findings if f.target == target and summary.strip() in f.summary]
    return matches


def cmd_remove(args):
    lines = read_lines(args.file)
    findings, _ = parse(lines)
    matches = _find_block(findings, args.target, args.summary)
    if not matches:
        print(f"remove: no finding under target '{args.target}' matching '{args.summary}'", file=sys.stderr)
        return 1
    if len(matches) > 1:
        print(f"remove: '{args.summary}' is ambiguous ({len(matches)} matches) — use the exact summary", file=sys.stderr)
        return 1
    f = matches[0]
    # Drop the block [f.start, f.end). Also swallow a single trailing `---` + blank if present.
    end = f.end
    while end < len(lines) and lines[end].strip() == "":
        end += 1
    if end < len(lines) and lines[end].strip() == "---":
        end += 1
        while end < len(lines) and lines[end].strip() == "":
            end += 1
    new_lines = lines[:f.start] + lines[end:]
    # If the target section is now empty (no ### left under it), drop the ## heading too.
    new_lines = _prune_empty_targets(new_lines)
    write_lines(args.file, new_lines)
    print(f"remove: deleted '{f.summary}' from target '{f.target}'")
    return 0


def _prune_empty_targets(lines):
    findings, _ = parse(lines)
    targets_with_findings = {f.target for f in findings}
    out = []
    i = 0
    while i < len(lines):
        tmatch = TARGET_RE.match(lines[i].rstrip("\n"))
        if tmatch and not lines[i].startswith("###") and tmatch.group("target") not in targets_with_findings:
            # skip this heading and following blanks until next non-blank
            i += 1
            while i < len(lines) and lines[i].strip() == "":
                i += 1
            continue
        out.append(lines[i])
        i += 1
    return out


def cmd_touch(args):
    lines = read_lines(args.file)
    findings, _ = parse(lines)
    matches = _find_block(findings, args.target, args.summary)
    if len(matches) != 1:
        print(f"touch: need exactly one match (got {len(matches)}) for '{args.summary}' under '{args.target}'", file=sys.stderr)
        return 1
    f = matches[0]
    today = args.date or datetime.date.today().isoformat()
    try:
        seen = int(f.fields.get("times_seen", "1"))
    except ValueError:
        seen = 1
    new_lines = list(lines)
    found_ls = found_ts = False
    last_prop_idx = f.start  # heading line; fall back to inserting right after it
    for idx in range(f.start, f.end):
        line = new_lines[idx]
        m = PROP_RE.match(line.rstrip("\n"))
        if m:
            last_prop_idx = idx
            key = m.group("key")
            if key == "last_seen":
                # Preserve any "· session ..." suffix shape by replacing the date prefix only.
                rest = line.split(":", 1)[1]
                session = ""
                if "·" in rest:
                    session = " ·" + rest.split("·", 1)[1].rstrip()
                new_lines[idx] = f"- last_seen: {today}{session}"
                found_ls = True
            elif key == "times_seen":
                new_lines[idx] = f"- times_seen: {seen + 1}"
                found_ts = True
    # Legacy blocks may lack these fields (see references/backlog.md "Backward
    # compatibility"). Insert them so the bump actually persists instead of the message
    # diverging from the file.
    missing = []
    if not found_ls:
        missing.append(f"- last_seen: {today}")
    if not found_ts:
        missing.append(f"- times_seen: {seen + 1}")
    if missing:
        new_lines[last_prop_idx + 1:last_prop_idx + 1] = missing
    write_lines(args.file, new_lines)
    print(f"touch: '{f.summary}' last_seen={today} times_seen={seen + 1}")
    return 0


def cmd_add(args):
    lines = read_lines(args.file)
    if not lines or not any(l.strip() for l in lines):
        lines = ["# Boyscout Backlog", "", "<!-- Auto-managed by the boyscout skill. Edit manually with care. -->", ""]
    today = datetime.date.today().isoformat()
    detected = args.detected or today
    block = [
        f"### [{args.effort}][{args.type}] {args.summary}",
        "- status: pending",
        f"- detected: {detected}",
        f"- last_seen: {args.last_seen or detected}",
        f"- times_seen: {args.times_seen}",
        f"- location: {args.location}",
        f"- type: {args.type}",
        f"- effort: {args.effort}",
        f"- risk: {args.risk}",
    ]
    if args.impact:
        block.append(f"- impact: {args.impact}")
    if args.confidence:
        block.append(f"- confidence: {args.confidence}")
    if args.context:
        block.append(f"- context: {args.context}")
    if args.how_found:
        block.append(f"- how_found: {args.how_found}")
    if args.action:
        block.append(f"- action: {args.action}")

    # Locate the target section's last finding, or append a new section.
    findings, _ = parse(lines)
    same_target = [f for f in findings if f.target == args.target]
    if same_target:
        insert_at = max(f.end for f in same_target)
        # ensure a separator before the new block
        new_block = ["", "---", ""] + block
        new_lines = lines[:insert_at] + new_block + lines[insert_at:]
    else:
        tail = lines[:]
        while tail and tail[-1].strip() == "":
            tail.pop()
        new_lines = tail + ["", f"## {args.target}", ""] + block + [""]
    write_lines(args.file, new_lines)
    print(f"add: '{args.summary}' under target '{args.target}'")
    return 0


def cmd_sweep(args):
    lines = read_lines(args.file)
    findings, _ = parse(lines)
    today = datetime.date.today()
    stale = []
    for f in findings:
        ls = parse_date(f.fields.get("last_seen"))
        if ls is not None and (today - ls).days > args.days:
            stale.append(f)
    if not stale:
        print(f"sweep: no findings with last_seen older than {args.days} days.")
        return 0
    print(f"sweep: {len(stale)} stale finding(s) (last_seen > {args.days} days):")
    for f in stale:
        print(f"  [{f.target}] {f.summary} (last_seen {f.fields.get('last_seen')}, times_seen {f.fields.get('times_seen','?')})")
    if args.remove:
        # Remove one-by-one via cmd_remove; it re-reads the file each call so
        # indices stay valid across deletions. Track real successes — a removal can
        # fail (e.g. duplicate summary → ambiguous), and reporting it as removed would
        # be a silent no-op.
        removed = 0
        for f in stale:
            if cmd_remove(argparse.Namespace(file=args.file, target=f.target, summary=f.summary)) == 0:
                removed += 1
            else:
                print(f"sweep: could not remove '{f.summary}' under '{f.target}' — left in place", file=sys.stderr)
        print(f"sweep: removed {removed} of {len(stale)} stale finding(s).")
        return 0 if removed == len(stale) else 1
    print("sweep: dry-run (pass --remove to delete).")
    return 0


def cmd_dedup_check(args):
    lines = read_lines(args.file)
    findings, _ = parse(lines)
    seen = {}
    dups = []
    for f in findings:
        key = (f.target, f.summary.strip())
        if key in seen:
            dups.append((key, seen[key], f.start + 1))
        else:
            seen[key] = f.start + 1
    if dups:
        print(f"dedup-check: FAIL — {len(dups)} duplicate finding(s):", file=sys.stderr)
        for (target, summary), first, second in dups:
            print(f"  '{summary}' under '{target}' at lines {first} and {second}", file=sys.stderr)
        return 1
    print(f"dedup-check: OK — no duplicate (target, summary) pairs among {len(findings)} findings.")
    return 0


def build_parser():
    p = argparse.ArgumentParser(description="Manage the boyscout backlog file.")
    p.add_argument("--file", default=DEFAULT_FILE, help=f"backlog path (default {DEFAULT_FILE})")
    p.add_argument("--allow-foreign-file", action="store_true",
                   help="permit writing a --file outside $HOME / the temp dir (off by default)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("validate", help="check structure + anti-provenance")
    sp.set_defaults(func=cmd_validate)

    sp = sub.add_parser("list", help="list findings")
    sp.add_argument("--target")
    sp.add_argument("--type")
    sp.add_argument("--stale", action="store_true", help="only stale findings")
    sp.add_argument("--stale-days", type=int, default=7)
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("add", help="add a finding")
    sp.add_argument("--target", required=True)
    sp.add_argument("--summary", required=True)
    sp.add_argument("--type", required=True)
    sp.add_argument("--effort", required=True)
    sp.add_argument("--risk", required=True)
    sp.add_argument("--impact")
    sp.add_argument("--confidence")
    sp.add_argument("--location", default="")
    sp.add_argument("--context", default="")
    sp.add_argument("--how-found", dest="how_found", default="")
    sp.add_argument("--action", default="")
    sp.add_argument("--detected")
    sp.add_argument("--last-seen", dest="last_seen")
    sp.add_argument("--times-seen", dest="times_seen", default="1")
    sp.set_defaults(func=cmd_add)

    sp = sub.add_parser("remove", help="remove a finding by target + summary")
    sp.add_argument("--target", required=True)
    sp.add_argument("--summary", required=True)
    sp.set_defaults(func=cmd_remove)

    sp = sub.add_parser("touch", help="bump last_seen + times_seen on a dedup match")
    sp.add_argument("--target", required=True)
    sp.add_argument("--summary", required=True)
    sp.add_argument("--date")
    sp.set_defaults(func=cmd_touch)

    sp = sub.add_parser("sweep", help="report/remove stale findings")
    sp.add_argument("--days", type=int, default=7)
    sp.add_argument("--remove", action="store_true")
    sp.set_defaults(func=cmd_sweep)

    sp = sub.add_parser("dedup-check", help="report duplicate (target, summary) findings")
    sp.set_defaults(func=cmd_dedup_check)

    return p


def main(argv=None):
    global _ALLOW_FOREIGN
    args = build_parser().parse_args(argv)
    _ALLOW_FOREIGN = getattr(args, "allow_foreign_file", False)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
