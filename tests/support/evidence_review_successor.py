from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from evidence_json import (
    ContractError,
    JsonValue,
    create_json,
    digest,
    file_record,
    read_bytes_no_follow,
    read_file_record,
)

SUCCESSOR_SCHEMA = "agent-brain-successor-plan-review/v1"
SUCCESSOR_TOP_KEYS = {
    "created_at",
    "draft",
    "draft_sha256",
    "plan",
    "plan_sha256",
    "prior_draft_sha256",
    "prior_plan_sha256",
    "prior_seal",
    "prior_seal_sha256",
    "reviewers",
    "round_id",
    "schema_version",
}
SUCCESSOR_REVIEWER_KEYS = {"launch_id", "receipt", "role", "verdict"}
FILE_RECORD_KEYS = {"path_b64", "root", "sha256", "size"}
SHA256_RE = re.compile(r"[0-9a-f]{64}")
RFC3339_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})"
)


def create_successor_plan_review(
    plan: Path,
    impl_root: Path,
    draft: Path,
    brain_root: Path,
    prior_seal: Path,
    evidence_root: Path,
    momus_receipt: Path,
    independent_receipt: Path,
    output: Path,
    verify_prior: Callable[[dict[str, JsonValue]], None],
) -> None:
    if output.exists() or output.is_symlink():
        raise ContractError("plan review seal is create-only")
    plan_data = read_bytes_no_follow(plan)
    draft_data = read_bytes_no_follow(draft)
    prior_data = read_bytes_no_follow(prior_seal)
    plan_sha = digest(plan_data)
    draft_sha = digest(draft_data)
    prior_record = file_record(
        "evidence",
        evidence_root,
        prior_seal,
        data=prior_data,
    )
    prior = _load_object(prior_data, "prior review seal")
    verify_prior(prior)
    prior_plan_sha = prior.get("plan_sha256")
    prior_draft_sha = prior.get("draft_sha256")
    if prior_draft_sha != draft_sha:
        raise ContractError("prior review seal draft does not match successor draft")
    if prior_plan_sha == plan_sha:
        raise ContractError("successor review requires a changed plan")
    receipt_data = {
        "independent": read_bytes_no_follow(independent_receipt),
        "momus": read_bytes_no_follow(momus_receipt),
    }
    headers = {
        "independent": _receipt(
            independent_receipt,
            "independent",
            receipt_data["independent"],
        ),
        "momus": _receipt(momus_receipt, "momus", receipt_data["momus"]),
    }
    round_ids = {header["round_id"] for header in headers.values()}
    if len(round_ids) != 1:
        raise ContractError("successor receipts must share one round")
    reviewers: dict[str, JsonValue] = {}
    launches: set[str] = set()
    for name, header in headers.items():
        if header["plan_sha256"] != plan_sha:
            raise ContractError(f"{name} receipt does not match successor plan")
        if header["launch_id"] in launches:
            raise ContractError("review launch IDs must be distinct")
        launches.add(header["launch_id"])
        receipt_path = momus_receipt if name == "momus" else independent_receipt
        reviewers[name] = {
            "launch_id": header["launch_id"],
            "receipt": file_record(
                "evidence",
                evidence_root,
                receipt_path,
                data=receipt_data[name],
            ),
            "role": name,
            "verdict": "OKAY",
        }
    create_json(
        output,
        {
            "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "draft": file_record("brain", brain_root, draft, data=draft_data),
            "draft_sha256": draft_sha,
            "plan": file_record(
                "implementation",
                impl_root,
                plan,
                data=plan_data,
            ),
            "plan_sha256": plan_sha,
            "prior_draft_sha256": prior_draft_sha,
            "prior_plan_sha256": prior_plan_sha,
            "prior_seal": prior_record,
            "prior_seal_sha256": digest(prior_data),
            "reviewers": reviewers,
            "round_id": next(iter(round_ids)),
            "schema_version": SUCCESSOR_SCHEMA,
        },
    )


def verify_successor_plan_review(
    seal: dict[str, JsonValue],
    evidence_root: Path,
    brain_root: Path | None,
    implementation_root: Path | None,
    verify_prior: Callable[[dict[str, JsonValue]], None],
) -> None:
    if brain_root is None or implementation_root is None:
        raise ContractError("successor plan review requires brain and implementation roots")
    if set(seal) != SUCCESSOR_TOP_KEYS or seal.get("schema_version") != SUCCESSOR_SCHEMA:
        raise ContractError("invalid successor plan review schema")
    _require_rfc3339(seal.get("created_at"), "successor created_at")
    round_id = _require_string(seal.get("round_id"), "successor round_id")
    expected_plan_sha = _require_sha256(
        seal.get("plan_sha256"), "successor plan_sha256"
    )
    expected_draft_sha = _require_sha256(
        seal.get("draft_sha256"), "successor draft_sha256"
    )
    expected_prior_sha = _require_sha256(
        seal.get("prior_seal_sha256"), "successor prior_seal_sha256"
    )
    expected_prior_plan_sha = _require_sha256(
        seal.get("prior_plan_sha256"), "successor prior_plan_sha256"
    )
    expected_prior_draft_sha = _require_sha256(
        seal.get("prior_draft_sha256"), "successor prior_draft_sha256"
    )
    plan_path, plan_data = _read_exact_record(seal.get("plan"), "implementation", implementation_root)
    _draft_path, draft_data = _read_exact_record(seal.get("draft"), "brain", brain_root)
    prior_path, prior_data = _read_exact_record(seal.get("prior_seal"), "evidence", evidence_root)
    plan_sha = digest(plan_data)
    draft_sha = digest(draft_data)
    prior_sha = digest(prior_data)
    if expected_plan_sha != plan_sha:
        raise ContractError("successor plan changed")
    if expected_draft_sha != draft_sha:
        raise ContractError("successor draft changed")
    if expected_prior_sha != prior_sha:
        raise ContractError("successor prior seal changed")
    prior = _load_object(prior_data, "successor prior seal")
    verify_prior(prior)
    if prior.get("draft_sha256") != draft_sha or expected_prior_draft_sha != draft_sha:
        raise ContractError("successor prior draft mismatch")
    prior_plan_sha = prior.get("plan_sha256")
    if expected_prior_plan_sha != prior_plan_sha:
        raise ContractError("successor prior plan mismatch")
    if prior_plan_sha == plan_sha:
        raise ContractError("successor review requires a changed plan")
    _verify_reviewers(seal, evidence_root, plan_sha, round_id)
    if not plan_path.is_file():
        raise ContractError("successor plan record is not a file")


def _verify_reviewers(
    seal: dict[str, JsonValue],
    evidence_root: Path,
    plan_sha: str,
    round_id: str,
) -> None:
    reviewers = seal.get("reviewers")
    if not isinstance(reviewers, dict) or set(reviewers) != {"momus", "independent"}:
        raise ContractError("successor plan review must contain both reviewers")
    launches: set[str] = set()
    for name in ("momus", "independent"):
        reviewer = reviewers[name]
        if not isinstance(reviewer, dict) or set(reviewer) != SUCCESSOR_REVIEWER_KEYS:
            raise ContractError(f"invalid {name} successor review record")
        launch_id = _require_string(
            reviewer.get("launch_id"), f"{name} successor launch_id"
        )
        if reviewer.get("role") != name or reviewer.get("verdict") != "OKAY":
            raise ContractError(f"invalid {name} successor review record")
        receipt_path, receipt_data = _read_exact_record(
            reviewer.get("receipt"),
            "evidence",
            evidence_root,
        )
        header = _receipt(receipt_path, name, receipt_data)
        if (
            header["round_id"] != round_id
            or header["plan_sha256"] != plan_sha
            or header["launch_id"] != launch_id
        ):
            raise ContractError(f"{name} successor receipt binding mismatch")
        launches.add(header["launch_id"])
    if len(launches) != 2:
        raise ContractError("review launch IDs must be distinct")


def _receipt(path: Path, reviewer: str, data: bytes | None = None) -> dict[str, str]:
    try:
        lines = (
            read_bytes_no_follow(path) if data is None else data
        ).decode("utf-8").splitlines()
        header = json.loads(lines[0])
    except (UnicodeDecodeError, json.JSONDecodeError, IndexError) as error:
        raise ContractError(f"invalid {reviewer} receipt") from error
    required = {"round_id", "plan_sha256", "launch_id", "reviewer"}
    if not isinstance(header, dict) or set(header) != required:
        raise ContractError(f"invalid {reviewer} receipt header")
    if not all(isinstance(header[key], str) and header[key] for key in required):
        raise ContractError(f"invalid {reviewer} receipt header")
    _require_sha256(header["plan_sha256"], f"{reviewer} receipt plan_sha256")
    if header["reviewer"] != reviewer or not lines or lines[-1] != "OKAY":
        raise ContractError(f"{reviewer} receipt is not an unconditional OKAY")
    return {key: header[key] for key in required}


def _read_exact_record(record: JsonValue, root: str, base: Path) -> tuple[Path, bytes]:
    if not isinstance(record, dict) or set(record) != FILE_RECORD_KEYS:
        raise ContractError(f"invalid {root} record")
    if record.get("root") != root or not isinstance(record.get("path_b64"), str):
        raise ContractError(f"invalid {root} record")
    _require_sha256(record.get("sha256"), f"{root} record sha256")
    size = record.get("size")
    if type(size) is not int or size < 0:
        raise ContractError(f"invalid {root} record size")
    return read_file_record(record, {root: base})


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


def _load_object(data: bytes, label: str) -> dict[str, JsonValue]:
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ContractError(f"invalid {label}") from error
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be an object")
    return value
