#!/usr/bin/env python3
"""Pre-push privacy and hygiene gate.

Audits an outgoing commit range for secret shapes, Spanish PII,
owner-specific absolute paths, add-like binary attachments, and changes
to protected paths. Read-only: it never mutates the repository, the
index, or the worktree.

Exit codes: 0 clean, 1 blocking findings, 2 operational failure.
Matched values are redacted in reports (first characters only); other
metadata (paths, refs) is reported as-is.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from re import Pattern
from typing import Any

CONFIG_SCHEMA = "push-gate/config-v1"
OID_RE = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
ADD_LIKE_STATUSES = frozenset({"A", "C", "R"})

SECRET_PATTERNS: tuple[tuple[str, Pattern[str]], ...] = (
    ("aws-access-key-id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github-pat-classic", re.compile(r"\bghp_[A-Za-z0-9]{36}\b")),
    ("github-pat-fine", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,}\b")),
    ("github-token-family", re.compile(r"\bgh[soru]_[A-Za-z0-9]{36}\b")),
    ("gitlab-pat", re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b")),
    (
        "slack-token",
        re.compile(
            r"\b(?:xox[bcapres]-[A-Za-z0-9-]{10,}|xapp-[A-Za-z0-9-]{10,})\b"
        ),
    ),
    ("openai-key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    (
        "private-key-block",
        re.compile(
            r"-----BEGIN (?:RSA |EC |DSA |ENCRYPTED |OPENSSH |PGP )?"
            r"PRIVATE KEY(?: BLOCK)?-----"
        ),
    ),
    (
        "jwt",
        re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    ),
    (
        "assigned-secret-literal",
        re.compile(
            r"(?i)\b(?:api[_-]?key|apikey|secret|secret[_-]?key|client[_-]?secret|"
            r"token|access[_-]?token|refresh[_-]?token|password|passwd)\b"
            r"[\"']?\s*[:=]\s*(?:[\"'][A-Za-z0-9+/_=-]{16,}[\"']|"
            r"[A-Za-z0-9+/_=-]{20,})"
        ),
    ),
)

PII_PATTERNS: tuple[tuple[str, Pattern[str]], ...] = (
    ("dni-nif", re.compile(r"(?i)\b\d{8}[- ]?[a-z]\b")),
    ("nie", re.compile(r"(?i)\b[xyz]\d{7}[- ]?[a-z]\b")),
    ("iban-es", re.compile(r"\bES\d{2}(?:[ ]?\d{4}){5}\b")),
    (
        "phone-es",
        re.compile(
            r"(?<![\w+-])\+34[ -]?[67]\d{2}(?:[ -]?\d{3}){2}(?![\w+-])"
        ),
    ),
)

OWNER_PATH_PATTERNS: tuple[tuple[str, Pattern[str]], ...] = (
    (
        "home-users-path",
        re.compile(
            r"/Users/(?!foo/|bar/|baz/|test/|example/|user/|someone/)"
            r"[A-Za-z][A-Za-z0-9._-]*/"
        ),
    ),
    (
        "home-linux-path",
        re.compile(
            r"/home/(?!foo/|bar/|baz/|test/|example/|user/|someone/)"
            r"[A-Za-z][A-Za-z0-9._-]*/"
        ),
    ),
)

PATH_PII_PATTERNS: tuple[tuple[str, Pattern[str]], ...] = (
    (
        "dni-nif",
        re.compile(r"(?<![A-Za-z0-9])\d{8}[A-HJ-NP-TV-Z](?![A-Za-z0-9])"),
    ),
    (
        "nie",
        re.compile(r"(?<![A-Za-z0-9])[XYZ]\d{7}[A-HJ-NP-TV-Z](?![A-Za-z0-9])"),
    ),
)

ATTACHMENT_EXTENSIONS = frozenset({
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic",
    ".xlsx", ".xls", ".docx", ".doc", ".pptx", ".zip", ".7z", ".dmg",
})

REDACT_KEEP = 4
STDERR_SNIPPET = 200


def display_safe(value: str) -> str:
    return value.encode("utf-8", "replace").decode("utf-8")


@dataclass(frozen=True, slots=True)
class Finding:
    detector: str
    kind: str
    path: str
    line: int | None
    redacted: str
    commit: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "detector": self.detector,
            "kind": self.kind,
            "path": display_safe(self.path),
            "line": self.line,
            "match": self.redacted,
            "commit": self.commit,
        }


def is_zero_sha(value: str) -> bool:
    return len(value) >= 40 and set(value) == {"0"}


def empty_tree_oid(repo_root: Path) -> str:
    """Hash-algo-correct empty tree OID, computed read-only (no -w)."""
    result = subprocess.run(
        ["git", "-C", str(repo_root), "hash-object", "-t", "tree",
         os.devnull],
        capture_output=True,
        text=True,
        check=False,
    )
    oid = result.stdout.strip().lower()
    if result.returncode != 0 or not OID_RE.match(oid):
        raise RuntimeError("could not compute the empty tree OID")
    return oid


def redact(value: str) -> str:
    if len(value) <= REDACT_KEEP:
        return value[0] + "…" if value else value
    return value[:REDACT_KEEP] + "…(" + str(len(value)) + " chars)"


class GateConfig:
    def __init__(self, data: dict[str, Any]) -> None:
        if not isinstance(data, dict):
            raise ValueError("push-gate config must be a JSON object")
        string_lists = {
            "allow_paths": data.get("allow_paths", []),
            "allow_strings": data.get("allow_strings", []),
            "disabled_detectors": data.get("disabled_detectors", []),
            "protected_paths": data.get("protected_paths", []),
        }
        for field, values in string_lists.items():
            if not isinstance(values, list) or not all(
                isinstance(value, str) and value.strip() for value in values
            ):
                raise ValueError(
                    f"push-gate config field '{field}' must be a list of "
                    f"non-empty strings"
                )
        self.allow_paths: tuple[str, ...] = tuple(string_lists["allow_paths"])
        self.allow_strings: frozenset[str] = frozenset(
            string_lists["allow_strings"]
        )
        self.disabled_detectors: frozenset[str] = frozenset(
            string_lists["disabled_detectors"]
        )
        self.protected_paths: tuple[str, ...] = tuple(
            string_lists["protected_paths"]
        )

    @classmethod
    def load(cls, path: Path) -> "GateConfig":
        data: dict[str, Any] = {}
        if path.exists():
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict):
                raise ValueError(
                    f"push-gate config must be a JSON object: {path}"
                )
            data = loaded
            if data.get("schema_version") != CONFIG_SCHEMA:
                raise ValueError(
                    f"push-gate config schema mismatch in {path}: "
                    f"expected {CONFIG_SCHEMA}"
                )
        return cls(data)

    def path_allowed(self, path: str) -> bool:
        return any(path.startswith(prefix) for prefix in self.allow_paths)

    def string_allowed(self, value: str) -> bool:
        """Exact or contained exemption.

        A matched span may wrap an allowed synthetic token (an
        assignment match includes the key and quotes), so an allow
        string occurring inside the matched value also exempts it.
        """
        if value in self.allow_strings:
            return True
        return any(allowed in value for allowed in self.allow_strings)

    def detector_enabled(self, detector: str) -> bool:
        return detector not in self.disabled_detectors

    def matched_protected(self, path: str) -> str | None:
        for pattern in self.protected_paths:
            if fnmatch.fnmatch(path, pattern):
                return pattern
        return None


HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def parse_added_lines(diff_text: str) -> list[tuple[int, str]]:
    """Added (line-number, text) pairs from a single-path diff.

    The diff is produced per file with the path as a git pathspec, so the
    caller already knows the path and header lines are never trusted to
    carry one (a filename containing `` b/`` cannot impersonate another
    path).
    """
    added: list[tuple[int, str]] = []
    line_no = 0
    in_hunk = False
    for raw in diff_text.splitlines():
        hunk_match = HUNK_RE.match(raw)
        if hunk_match:
            line_no = int(hunk_match.group(1))
            in_hunk = True
            continue
        if not in_hunk:
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            added.append((line_no, raw[1:]))
            line_no += 1
        elif raw.startswith("-") or raw.startswith("\\"):
            continue
        else:
            line_no += 1
    return added


def _scan_line(
    patterns: tuple[tuple[str, Pattern[str]], ...],
    detector: str,
    kind_suffix: str,
    path: str,
    line_no: int | None,
    text: str,
    config: GateConfig,
    findings: list[Finding],
) -> None:
    if not config.detector_enabled(detector):
        return
    for kind, pattern in patterns:
        for match in pattern.finditer(text):
            value = match.group(0)
            if config.string_allowed(value):
                continue
            findings.append(
                Finding(
                    detector=detector,
                    kind=kind + kind_suffix,
                    path=path,
                    line=line_no,
                    redacted=redact(value),
                )
            )


def audit_diff(
    added_by_path: dict[str, list[tuple[int, str]]],
    name_status: list[tuple[str, str, str | None]],
    config: GateConfig,
) -> list[Finding]:
    """Audit one commit: per-path added lines plus -z name-status records.

    name_status entries are (status_letter, path, original_path) where
    original_path is set for renames/copies; protected-path rules apply
    to both paths. Paths come exclusively from the -z records (the
    authoritative, unambiguous source); diff output is produced per file
    and its headers are never parsed, so a path containing `` b/``
    cannot impersonate an allowlisted one. Binary files contribute no
    lines, so attachment findings rely on status and extension. Changed
    paths' names are scanned themselves (suffix ``-in-path``).
    """
    findings: list[Finding] = []
    for status, path, orig_path in name_status:
        for candidate in (path, orig_path):
            if candidate is None:
                continue
            protected = config.matched_protected(candidate)
            if protected is not None:
                findings.append(
                    Finding(
                        detector="protected-paths",
                        kind="protected-path-change",
                        path=candidate,
                        line=None,
                        redacted=f"status={status}",
                    )
                )
        if config.path_allowed(path):
            continue
        for candidate in (path, orig_path):
            if candidate is None:
                continue
            _scan_line(
                PATH_PII_PATTERNS,
                "pii",
                "-in-path",
                candidate,
                None,
                candidate,
                config,
                findings,
            )
            _scan_line(
                OWNER_PATH_PATTERNS,
                "owner-paths",
                "-in-path",
                candidate,
                None,
                candidate,
                config,
                findings,
            )
        if (
            status in ADD_LIKE_STATUSES
            and config.detector_enabled("attachments")
            and Path(path).suffix.lower() in ATTACHMENT_EXTENSIONS
        ):
            findings.append(
                Finding(
                    detector="attachments",
                    kind=f"binary-extension{Path(path).suffix.lower()}",
                    path=path,
                    line=None,
                    redacted=f"add-like binary/attachment change (status={status})",
                )
            )
    for path, lines in added_by_path.items():
        if config.path_allowed(path):
            continue
        for line_no, text in lines:
            _scan_line(
                SECRET_PATTERNS, "secrets", "", path, line_no, text, config, findings
            )
            _scan_line(
                PII_PATTERNS, "pii", "", path, line_no, text, config, findings
            )
            _scan_line(
                OWNER_PATH_PATTERNS,
                "owner-paths",
                "",
                path,
                line_no,
                text,
                config,
                findings,
            )
    return findings


def git(repo_root: Path, args: list[Any], errors: str = "replace") -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "-c", "core.quotepath=false",
         "-c", "diff.noprefix=false",
         "-c", "diff.srcPrefix=a/", "-c", "diff.dstPrefix=b/", *args],
        capture_output=True,
        text=True,
        errors=errors,
        check=False,
    )
    if result.returncode != 0:
        snippet = result.stderr.strip()[:STDERR_SNIPPET]
        raise RuntimeError(f"git {' '.join(str(a) for a in args[:2])}… failed: {snippet}")
    return result.stdout


def resolve_oid(repo_root: Path, revision: str) -> str:
    probe = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "--verify", "--quiet",
         f"{revision}^{{commit}}"],
        capture_output=True,
        text=True,
        check=False,
    )
    oid = probe.stdout.strip().lower()
    if probe.returncode != 0 or not OID_RE.match(oid):
        raise RuntimeError(f"not a resolvable commit revision: {revision!r}")
    return oid


def resolve_range(repo_root: Path, explicit: str | None) -> str:
    if explicit:
        if ".." not in explicit or "..." in explicit:
            raise RuntimeError(
                "range must be exactly two dotted revisions: <base>..<tip>"
            )
        base, tip = explicit.split("..", 1)
        if not base or not tip:
            raise RuntimeError("range endpoints must be non-empty")
        if is_zero_sha(base):
            base_oid = empty_tree_oid(repo_root)
        else:
            base_oid = resolve_oid(repo_root, base)
        tip_oid = resolve_oid(repo_root, tip)
        return f"{base_oid}..{tip_oid}"
    probe = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "--abbrev-ref",
         "--symbolic-full-name", "@{upstream}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode != 0:
        raise RuntimeError(
            "no upstream configured; pass --range explicitly "
            "(e.g. --range origin/main..HEAD)"
        )
    return resolve_range(repo_root, "@{upstream}..HEAD")


def _name_status(
    repo_root: Path,
    base: str,
    tip: str,
) -> list[tuple[str, str, str | None]]:
    raw_status = git(
        repo_root,
        ["diff", "--no-color", "--name-status", "-z", f"{base}..{tip}"],
        errors="surrogateescape",
    )
    fields = [field for field in raw_status.split("\0") if field != ""]
    name_status: list[tuple[str, str, str | None]] = []
    index = 0
    while index < len(fields):
        status = fields[index]
        index += 1
        first_path = fields[index]
        index += 1
        path = first_path
        orig_path: str | None = None
        if status and status[0] in {"R", "C"} and index < len(fields):
            orig_path = first_path
            path = fields[index]
            index += 1
        name_status.append((status[0] if status else "?", path, orig_path))
    return name_status


def _added_for_path(
    repo_root: Path,
    base: str,
    tip: str,
    path: str,
) -> list[tuple[int, str]]:
    diff_text = git(
        repo_root,
        ["diff", "--no-color", "--text", "-U0", "--no-ext-diff",
         f"{base}..{tip}", "--", os.fsencode(f":(literal){path}")],
    )
    return parse_added_lines(diff_text)


def collect(
    repo_root: Path,
    revision_range: str,
) -> list[tuple[str, dict[str, list[tuple[int, str]]], list[tuple[str, str, str | None]]]]:
    """Per-commit snapshots for the range, oldest first.

    An endpoint-only diff is blind to content introduced and later
    removed inside the range (it still ships in pushed history), so the
    gate audits each commit against its own parent. ``-z`` name-status
    records for renames/copies emit the ORIGINAL path first and the new
    path second; each file's added lines are collected with the path as
    an explicit pathspec, never parsed from diff headers.
    """
    base, tip = revision_range.split("..", 1)
    listing = git(repo_root, ["rev-list", "--reverse", f"{base}..{tip}"])
    commits = [line.strip() for line in listing.splitlines() if line.strip()]
    snapshots: list[tuple[str, dict[str, list[tuple[int, str]]], list[tuple[str, str, str | None]]]] = []
    for commit in commits:
        parent = f"{commit}^"
        probe = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--verify", "--quiet",
             f"{commit}^"],
            capture_output=True,
            text=True,
            check=False,
        )
        if probe.returncode != 0:
            parent = empty_tree_oid(repo_root)
        status_records = _name_status(repo_root, parent, commit)
        added_by_path: dict[str, list[tuple[int, str]]] = {}
        for _, path, _orig in status_records:
            if path in added_by_path:
                continue
            added_by_path[path] = _added_for_path(
                repo_root, parent, commit, path
            )
        snapshots.append((commit, added_by_path, status_records))
    return snapshots


def render(
    findings: list[Finding],
    revision_range: str,
    repo_root: Path,
) -> str:
    try:
        display_root = str(repo_root.relative_to(Path.cwd()))
    except ValueError:
        display_root = repo_root.name
    lines = [
        "# push-gate audit",
        f"repo: {display_root}",
        f"range: {revision_range}",
        f"findings: {len(findings)}",
        "",
    ]
    for finding in findings:
        where = f"{finding.path}:{finding.line}" if finding.line else finding.path
        if finding.commit:
            where = f"{where} @{finding.commit[:8]}"
        lines.append(
            f"- [{finding.detector}/{finding.kind}] {display_safe(where)}  "
            f"match: {finding.redacted}"
        )
    if findings:
        lines.append("")
        lines.append(
            "Blocking findings: fix them, extend allowlists in push-gate.json "
            "deliberately, or bypass once with `git push --no-verify` (leave a reason)."
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo-root", default=".", help="Repository root")
    parser.add_argument(
        "--range",
        dest="revision_range",
        default=None,
        help="Commit range to audit (default: @{upstream}..HEAD)",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Config path (default: <repo-root>/push-gate.json)",
    )
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    try:
        config_path = (
            Path(args.config).resolve()
            if args.config
            else repo_root / "push-gate.json"
        )
        config = GateConfig.load(config_path)
        revision_range = resolve_range(repo_root, args.revision_range)
        snapshots = collect(repo_root, revision_range)
        seen: set[tuple[str, str, str, int | None, str]] = set()
        findings: list[Finding] = []
        for commit, added_by_path, status_records in snapshots:
            for finding in audit_diff(added_by_path, status_records, config):
                key = (
                    finding.detector,
                    finding.kind,
                    finding.path,
                    finding.line,
                    finding.redacted,
                )
                if key not in seen:
                    seen.add(key)
                    findings.append(
                        Finding(
                            detector=finding.detector,
                            kind=finding.kind,
                            path=finding.path,
                            line=finding.line,
                            redacted=finding.redacted,
                            commit=commit,
                        )
                    )
    except (RuntimeError, ValueError, json.JSONDecodeError) as error:
        print(f"push-gate operational failure: {error}", file=sys.stderr)
        return 2

    if args.json:
        print(
            json.dumps(
                {
                    "repo": str(repo_root),
                    "range": revision_range,
                    "findings": [f.as_dict() for f in findings],
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        print(render(findings, revision_range, repo_root), end="")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
