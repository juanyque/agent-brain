from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from evidence_json import ContractError, JsonValue, digest, read_file_record

V1_SCHEMA = "agent-brain-evidence/v1"
V1_TOP_KEYS = {
    "created_at",
    "draft",
    "draft_sha256",
    "plan",
    "plan_sha256",
    "reviewers",
    "round_id",
    "schema_version",
}
V1_REVIEWER_KEYS = {"launch_id", "receipt", "verdict"}
FILE_RECORD_KEYS = {"path_b64", "root", "sha256", "size"}
SHA256_RE = re.compile(r"[0-9a-f]{64}")
RFC3339_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})"
)


def verify_successor_predecessor_v1(
    seal: dict[str, JsonValue],
    evidence_root: Path,
    brain_root: Path,
) -> None:
    if set(seal) != V1_TOP_KEYS or seal.get("schema_version") != V1_SCHEMA:
        raise ContractError("invalid successor predecessor schema")
    _require_rfc3339(seal.get("created_at"), "predecessor created_at")
    round_id = _require_string(seal.get("round_id"), "predecessor round_id")
    plan_sha = _require_sha256(seal.get("plan_sha256"), "predecessor plan_sha256")
    draft_sha = _require_sha256(seal.get("draft_sha256"), "predecessor draft_sha256")
    _plan_path, plan_data = _read_record(seal.get("plan"), "brain", brain_root)
    _draft_path, draft_data = _read_record(seal.get("draft"), "brain", brain_root)
    if digest(plan_data) != plan_sha or digest(draft_data) != draft_sha:
        raise ContractError("predecessor record hash does not match top-level hash")
    reviewers = seal.get("reviewers")
    if not isinstance(reviewers, dict) or set(reviewers) != {"momus", "independent"}:
        raise ContractError("predecessor must contain both reviewers")
    launches: set[str] = set()
    for name in ("momus", "independent"):
        reviewer = reviewers[name]
        if not isinstance(reviewer, dict) or set(reviewer) != V1_REVIEWER_KEYS:
            raise ContractError(f"invalid {name} predecessor review record")
        launch_id = _require_string(
            reviewer.get("launch_id"), f"{name} predecessor launch_id"
        )
        if reviewer.get("verdict") != "OKAY":
            raise ContractError(f"invalid {name} predecessor verdict")
        _receipt_path, receipt_data = _read_record(
            reviewer.get("receipt"), "evidence", evidence_root
        )
        header = _receipt_header(receipt_data, name)
        if (
            header["round_id"] != round_id
            or header["plan_sha256"] != plan_sha
            or header["launch_id"] != launch_id
        ):
            raise ContractError(f"{name} predecessor receipt binding mismatch")
        launches.add(launch_id)
    if len(launches) != 2:
        raise ContractError("predecessor review launch IDs must be distinct")


def _read_record(record: JsonValue, root: str, base: Path) -> tuple[Path, bytes]:
    if not isinstance(record, dict) or set(record) != FILE_RECORD_KEYS:
        raise ContractError(f"invalid {root} predecessor file record")
    if record.get("root") != root or not isinstance(record.get("path_b64"), str):
        raise ContractError(f"invalid {root} predecessor file record")
    _require_sha256(record.get("sha256"), f"{root} predecessor record sha256")
    size = record.get("size")
    if type(size) is not int or size < 0:
        raise ContractError(f"invalid {root} predecessor record size")
    return read_file_record(record, {root: base})


def _receipt_header(data: bytes, reviewer: str) -> dict[str, str]:
    try:
        lines = data.decode("utf-8").splitlines()
        header = json.loads(lines[0])
    except (UnicodeDecodeError, json.JSONDecodeError, IndexError) as error:
        raise ContractError(f"invalid {reviewer} predecessor receipt") from error
    required = {"round_id", "plan_sha256", "launch_id", "reviewer"}
    if not isinstance(header, dict) or set(header) != required:
        raise ContractError(f"invalid {reviewer} predecessor receipt header")
    if not all(isinstance(header[key], str) and header[key] for key in required):
        raise ContractError(f"invalid {reviewer} predecessor receipt header")
    _require_sha256(
        header["plan_sha256"], f"{reviewer} predecessor receipt plan_sha256"
    )
    if header["reviewer"] != reviewer or lines[-1] != "OKAY":
        raise ContractError(f"{reviewer} predecessor receipt is not an unconditional OKAY")
    return {key: header[key] for key in required}


def _require_string(value: JsonValue, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ContractError(f"{label} must be a non-empty string")
    return value


def _require_sha256(value: JsonValue, label: str) -> str:
    text = _require_string(value, label)
    if SHA256_RE.fullmatch(text) is None:
        raise ContractError(f"{label} must be lowercase SHA-256")
    return text


def _require_rfc3339(value: JsonValue, label: str) -> str:
    text = _require_string(value, label)
    if RFC3339_RE.fullmatch(text) is None:
        raise ContractError(f"{label} must be RFC3339")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise ContractError(f"{label} must be RFC3339") from error
    if parsed.tzinfo is None:
        raise ContractError(f"{label} must be RFC3339")
    return text
