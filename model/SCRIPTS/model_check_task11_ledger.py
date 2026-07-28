from __future__ import annotations

import base64
import hashlib
import json
import tarfile
from dataclasses import dataclass
from pathlib import Path

from model_check_contract import CodeDef, Finding, JsonValue


TASK10_EVIDENCE_ROOT = (
    Path.home()
    / ".local/state/agent-brain/reviews"
    / "agent-brain-operating-model/wave-3-execution-20260723"
)
TASK10_POST_MANIFEST = TASK10_EVIDENCE_ROOT / "implementation-task-10-post.json"
TASK10_POST_ARCHIVE = TASK10_EVIDENCE_ROOT / "implementation-task-10-post.tar"


@dataclass(frozen=True, slots=True)
class EvidenceRange:
    path: str
    start_line: int
    end_line: int
    sha256: str


def _json_object(path: Path) -> dict[str, JsonValue]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _line_range(path: Path, start_line: int, end_line: int) -> bytes | None:
    try:
        lines = path.read_bytes().splitlines(keepends=True)
    except OSError:
        return None
    if start_line < 1 or end_line < start_line or end_line > len(lines):
        return None
    return b"".join(lines[start_line - 1 : end_line])


def _bytes_line_range(raw: bytes, start_line: int, end_line: int) -> bytes | None:
    lines = raw.splitlines(keepends=True)
    if start_line < 1 or end_line < start_line or end_line > len(lines):
        return None
    return b"".join(lines[start_line - 1 : end_line])


def _evidence_range(value: JsonValue) -> EvidenceRange | None:
    match value:
        case {
            "path": str(path),
            "start_line": int(start_line),
            "end_line": int(end_line),
            "sha256": str(digest),
        }:
            return EvidenceRange(
                path=path,
                start_line=start_line,
                end_line=end_line,
                sha256=digest,
            )
        case _:
            return None


def _finding(code: CodeDef, path: str, target: str, message: str) -> Finding:
    return Finding(
        code=code.code,
        family=code.family,
        severity=code.severity,
        path=path,
        target=target,
        message=message,
    )


def _task11_trim_claims(ledger: dict[str, JsonValue]) -> tuple[dict[str, JsonValue], ...]:
    raw_claims = ledger.get("task11_trim_claims", [])
    if not isinstance(raw_claims, list):
        return ()
    return tuple(row for row in raw_claims if isinstance(row, dict))


def _sealed_snapshot_file(manifest_path: Path, archive_path: Path, target_path: str) -> bytes | None:
    manifest = _json_object(manifest_path)
    entries = manifest.get("entries", [])
    if not isinstance(entries, list):
        return None
    digest: str | None = None
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("type") != "file":
            continue
        raw_path = entry.get("path_b64")
        raw_digest = entry.get("sha256")
        if not isinstance(raw_path, str) or not isinstance(raw_digest, str):
            continue
        try:
            path = base64.b64decode(raw_path).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            continue
        if path == target_path:
            digest = raw_digest
            break
    if digest is None:
        return None
    try:
        with tarfile.open(archive_path, "r") as archive:
            member = archive.extractfile(f"blobs/{digest}")
            if member is None:
                return None
            return member.read()
    except (OSError, tarfile.TarError):
        return None


def _validate_reference(
    root: Path,
    code: CodeDef,
    cluster_id: str,
    value: JsonValue,
) -> Finding | None:
    reference = _evidence_range(value)
    if reference is None:
        return _finding(code, "docs/migrations/2026-07-operating-model-ledger.json", cluster_id, "task11 reference range is malformed")
    raw = _line_range(root / reference.path, reference.start_line, reference.end_line)
    if raw is None:
        return _finding(code, reference.path, cluster_id, "task11 reference range cannot be read")
    digest = hashlib.sha256(raw).hexdigest()
    if digest != reference.sha256:
        return _finding(code, reference.path, cluster_id, "task11 reference range hash changed")
    return None


def task11_ledger_findings(root: Path, ledger_path: Path, code: CodeDef) -> list[Finding]:
    ledger = _json_object(ledger_path)
    pretrim_brain = _sealed_snapshot_file(
        TASK10_POST_MANIFEST,
        TASK10_POST_ARCHIVE,
        "model/BRAIN.common.md",
    )
    if pretrim_brain is None:
        return [
            _finding(
                code,
                "docs/migrations/2026-07-operating-model-ledger.json",
                "task11_trim_claims",
                "task11 sealed todo-10 BRAIN snapshot cannot be read",
            )
        ]
    findings: list[Finding] = []
    for claim in _task11_trim_claims(ledger):
        cluster_id = claim.get("cluster_id")
        if not isinstance(cluster_id, str):
            findings.append(
                _finding(
                    code,
                    "docs/migrations/2026-07-operating-model-ledger.json",
                    "task11_trim_claims",
                    "task11 trim claim is malformed",
                )
            )
            continue
        if claim.get("status") != "source-trimmed-task-11":
            findings.append(_finding(code, ledger_path.name, cluster_id, "task11 trim status is missing"))
            continue
        sources = claim.get("removed_source_evidence")
        if not isinstance(sources, list) or not sources:
            findings.append(_finding(code, ledger_path.name, cluster_id, "task11 removed source evidence is missing"))
            continue
        for source_value in sources:
            source = _evidence_range(source_value)
            if source is None or source.path != "model/BRAIN.common.md":
                findings.append(_finding(code, ledger_path.name, cluster_id, "task11 removed source range is malformed"))
                continue
            raw = _bytes_line_range(pretrim_brain, source.start_line, source.end_line)
            if raw is None:
                findings.append(_finding(code, source.path, cluster_id, "task11 removed source range cannot be read"))
                continue
            digest = hashlib.sha256(raw).hexdigest()
            if digest != source.sha256:
                findings.append(_finding(code, source.path, cluster_id, "task11 removed source range hash changed"))
        reference_finding = _validate_reference(
            root,
            code,
            cluster_id,
            claim.get("verified_reference"),
        )
        if reference_finding is not None:
            findings.append(reference_finding)
    return sorted(findings, key=lambda item: (item.path, item.target, item.message))
