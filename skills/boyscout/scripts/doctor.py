#!/usr/bin/env python3
"""boyscout doctor — self-test for the skill's own integrity.

Run before shipping a change to boyscout (and exposed as `/boyscout doctor`).
Each check prints PASS/FAIL; the process exits non-zero if any check fails, so
it can gate a pre-PR hook.

Checks:
  1. Every `references/*.common.md` named in SKILL.boyscout.common.md's Dependencies table
     exists and is non-empty.
  2. The deep-mode finding types (repeated-instruction, automation-opportunity,
     promotable-flow) declared in the Type enum of finding-schema.common.md each have a
     matching detection-<type>.common.md brief, and vice-versa.
  3. The backlog file (if present) parses cleanly via backlog.py validate.
  4. Subagent-brief consistency: references/deep-mode.common.md (the D4 fan-out) links
     every detection-*.common.md brief that exists.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

SKILL_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEEP_TYPES = ["repeated-instruction", "automation-opportunity", "promotable-flow"]


def read(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def check_dependencies(skill_dir):
    """Every references/*.common.md in SKILL.boyscout.common.md's Dependencies table exists + non-empty."""
    problems = []
    skill_md = os.path.join(skill_dir, "SKILL.boyscout.common.md")
    text = read(skill_md)
    referenced = sorted(set(re.findall(r"references/[A-Za-z0-9_-]+\.common\.md", text)))
    if not referenced:
        problems.append("SKILL.boyscout.common.md references no reference files (unexpected)")
    for rel in referenced:
        path = os.path.join(skill_dir, rel)
        if not os.path.exists(path):
            problems.append(f"missing reference file: {rel}")
        elif os.path.getsize(path) == 0:
            problems.append(f"empty reference file: {rel}")
    return referenced, problems


def check_type_enum(skill_dir):
    """Deep-mode types in finding-schema.common.md's enum each have a detection brief."""
    problems = []
    schema = read(os.path.join(skill_dir, "references", "finding-schema.common.md"))
    for t in DEEP_TYPES:
        if t not in schema:
            problems.append(f"finding-schema.common.md Type enum is missing '{t}'")
        brief = os.path.join(skill_dir, "references", f"detection-{t}.common.md")
        if not os.path.exists(brief):
            problems.append(f"missing detection brief: detection-{t}.common.md")
    # reverse: every detection-*.common.md corresponds to a known deep type
    refs = os.path.join(skill_dir, "references")
    for fn in os.listdir(refs):
        m = re.match(r"detection-(.+)\.common\.md$", fn)
        if m and m.group(1) not in DEEP_TYPES:
            problems.append(f"detection-{m.group(1)}.common.md has no matching entry in DEEP_TYPES")
    return problems


def check_backlog(skill_dir, backlog_path):
    """Backlog (if present) parses cleanly via backlog.py validate."""
    if not os.path.exists(backlog_path):
        return [], f"backlog not present at {backlog_path} (skipped)"
    backlog_py = os.path.join(skill_dir, "scripts", "backlog.py")
    res = subprocess.run([sys.executable, backlog_py, "--file", backlog_path, "validate"],
                         capture_output=True, text=True)
    if res.returncode != 0:
        return [res.stdout.strip() + res.stderr.strip()], None
    return [], res.stdout.strip()


def check_backlog_roundtrip(skill_dir):
    """Smoke-test backlog.py itself: round-trip a throwaway fixture through
    add → validate → list → touch → remove → validate and assert each step.

    Without this, a parser regression (the exact failure class backlog.py exists to
    prevent) would slip through — the other checks only read docs / a pre-existing file.
    """
    import json as _json
    import tempfile
    problems = []
    backlog_py = os.path.join(skill_dir, "scripts", "backlog.py")

    def run(*cmd_args):
        return subprocess.run([sys.executable, backlog_py, *cmd_args],
                              capture_output=True, text=True)

    with tempfile.TemporaryDirectory() as d:  # under the temp dir → write guard allows it
        f = os.path.join(d, "backlog.md")
        common = ["--file", f]
        if run(*common, "add", "--target", "rt / c", "--summary", "round trip",
               "--type", "docs-gap", "--effort", "XS", "--risk", "low").returncode != 0:
            return ["round-trip: add failed"]
        if run(*common, "validate").returncode != 0:
            problems.append("round-trip: validate failed after add")
        lst = run(*common, "list", "--json")
        try:
            items = _json.loads(lst.stdout)
            if len(items) != 1 or items[0]["summary"] != "round trip":
                problems.append(f"round-trip: list did not return the added finding (got {lst.stdout!r})")
        except Exception as e:
            problems.append(f"round-trip: list --json not parseable ({e})")
        if run(*common, "touch", "--target", "rt / c", "--summary", "round trip").returncode != 0:
            problems.append("round-trip: touch failed")
        else:
            items = _json.loads(run(*common, "list", "--json").stdout or "[]")
            if not items:
                problems.append("round-trip: finding disappeared after touch")
            elif items[0].get("times_seen") != "2":
                problems.append(f"round-trip: touch did not bump times_seen to 2 (got {items[0].get('times_seen')})")
        if run(*common, "remove", "--target", "rt / c", "--summary", "round trip").returncode != 0:
            problems.append("round-trip: remove failed")
        final = run(*common, "list", "--json")
        if _json.loads(final.stdout or "[]"):
            problems.append("round-trip: finding still present after remove")
    return problems


def check_subagent_briefs(skill_dir):
    """deep-mode.common.md (the D4 fan-out) links every detection-*.common.md that exists."""
    problems = []
    deep = read(os.path.join(skill_dir, "references", "deep-mode.common.md"))
    for t in DEEP_TYPES:
        brief = f"detection-{t}.common.md"
        if os.path.exists(os.path.join(skill_dir, "references", brief)) and brief not in deep:
            problems.append(f"deep-mode.common.md D4 does not link {brief}")
    return problems


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(description="boyscout skill self-test")
    p.add_argument("--skill-dir", default=SKILL_DIR)
    p.add_argument("--backlog", default=os.path.expanduser("~/.boyscout/backlog.md"))
    args = p.parse_args(argv)

    failed = False

    def report(name, problems, note=None):
        nonlocal failed
        if problems:
            failed = True
            print(f"FAIL  {name}")
            for pr in problems:
                print(f"        - {pr}")
        else:
            print(f"PASS  {name}" + (f" — {note}" if note else ""))

    referenced, dep_problems = check_dependencies(args.skill_dir)
    report(f"dependencies ({len(referenced)} reference files)", dep_problems)
    report("type-enum / detection-brief parity", check_type_enum(args.skill_dir))
    bl_problems, bl_note = check_backlog(args.skill_dir, args.backlog)
    report("backlog structure", bl_problems, bl_note)
    report("subagent-brief consistency (deep-mode.common.md D4)", check_subagent_briefs(args.skill_dir))
    report("backlog.py round-trip (parser smoke test)", check_backlog_roundtrip(args.skill_dir))

    print()
    if failed:
        print("boyscout doctor: FAIL")
        return 1
    print("boyscout doctor: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
