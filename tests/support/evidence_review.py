from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

from evidence_json import (
    ContractError,
    JsonValue,
    create_json,
    digest,
    encode_path,
    load_json,
    read_bytes_no_follow,
    validate_root,
)
from evidence_review_successor import (
    SUCCESSOR_SCHEMA,
    create_successor_plan_review as _create_successor_plan_review,
    verify_successor_plan_review,
)
from evidence_review_predecessor import verify_successor_predecessor_v1

V1_SCHEMA = "agent-brain-evidence/v1"


def _record(
    root: str,
    base: Path,
    path: Path,
    data: bytes | None = None,
) -> dict[str, JsonValue]:
    validate_root(root)
    try:
        relative = path.relative_to(base)
    except ValueError as error:
        raise ContractError(f"path is outside {root} root: {path}") from error
    data = read_bytes_no_follow(path) if data is None else data
    return {
        "path_b64": encode_path(bytes(relative)),
        "root": root,
        "sha256": digest(data),
        "size": len(data),
    }


def _receipt(path: Path, reviewer: str, data: bytes | None = None) -> dict[str, str]:
    try:
        lines = (read_bytes_no_follow(path) if data is None else data).decode(
            "utf-8"
        ).splitlines()
        header = json.loads(lines[0])
    except (UnicodeDecodeError, json.JSONDecodeError, IndexError) as error:
        raise ContractError(f"invalid {reviewer} receipt") from error
    required = {"round_id", "plan_sha256", "launch_id", "reviewer"}
    if not isinstance(header, dict) or set(header) != required:
        raise ContractError(f"invalid {reviewer} receipt header")
    if not all(isinstance(header[key], str) and header[key] for key in required):
        raise ContractError(f"invalid {reviewer} receipt header")
    if header["reviewer"] != reviewer or not lines or lines[-1] != "OKAY":
        raise ContractError(f"{reviewer} receipt is not an unconditional OKAY")
    return {key: header[key] for key in required}


def _latest_round(draft: Path, data: bytes) -> dict[str, JsonValue]:
    text = data.decode("utf-8")
    blocks = re.findall(r"```json\n(\{.*?\})\n```", text, flags=re.DOTALL)
    if not blocks:
        raise ContractError("draft has no review round")
    try:
        value = json.loads(blocks[-1])
    except json.JSONDecodeError as error:
        raise ContractError("latest draft review round is invalid") from error
    if not isinstance(value, dict):
        raise ContractError("latest draft review round must be an object")
    return value


def create_plan_review(
    plan: Path,
    draft: Path,
    momus_receipt: Path,
    independent_receipt: Path,
    output: Path,
) -> None:
    if output.exists() or output.is_symlink():
        raise ContractError("plan review seal is create-only")
    plan_data = read_bytes_no_follow(plan)
    draft_data = read_bytes_no_follow(draft)
    plan_sha = digest(plan_data)
    latest = _latest_round(draft, draft_data)
    round_id = latest.get("review_round_id")
    if latest.get("plan_sha256") != plan_sha or latest.get("round_status") != "approved":
        raise ContractError("latest draft review round does not approve this plan")
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
    reviewers: dict[str, JsonValue] = {}
    evidence_root = output.parents[1]
    for name, header in headers.items():
        expected = latest.get("review", {}).get(name, {})
        if (
            header["round_id"] != round_id
            or header["plan_sha256"] != plan_sha
            or header["launch_id"] != expected.get("launch_id")
        ):
            raise ContractError(f"{name} receipt does not match latest draft round")
        receipt_path = momus_receipt if name == "momus" else independent_receipt
        reviewers[name] = {
            "launch_id": header["launch_id"],
            "receipt": _record(
                "evidence",
                evidence_root,
                receipt_path,
                receipt_data[name],
            ),
            "verdict": "OKAY",
        }
    brain_root = plan.parents[2]
    value = {
        "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "draft": _record("brain", brain_root, draft, draft_data),
        "draft_sha256": digest(draft_data),
        "plan": _record("brain", brain_root, plan, plan_data),
        "plan_sha256": plan_sha,
        "reviewers": reviewers,
        "round_id": round_id,
        "schema_version": V1_SCHEMA,
    }
    create_json(output, value)


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
) -> None:
    def verify_prior(value: dict[str, JsonValue]) -> None:
        verify_successor_predecessor_v1(value, evidence_root, brain_root)

    _create_successor_plan_review(
        plan,
        impl_root,
        draft,
        brain_root,
        prior_seal,
        evidence_root,
        momus_receipt,
        independent_receipt,
        output,
        verify_prior,
    )


def verify_plan_review(
    seal_path: Path,
    evidence_root: Path,
    brain_root: Path | None,
    implementation_root: Path | None = None,
    value: dict[str, JsonValue] | None = None,
) -> None:
    seal = load_json(seal_path) if value is None else value
    match seal.get("schema_version"):
        case "agent-brain-evidence/v1":
            _verify_plan_review_v1(seal, evidence_root, brain_root)
        case schema if schema == SUCCESSOR_SCHEMA:
            verify_successor_plan_review(
                seal,
                evidence_root,
                brain_root,
                implementation_root,
                lambda prior: verify_successor_predecessor_v1(
                    prior, evidence_root, brain_root
                ),
            )
        case _:
            raise ContractError("invalid plan review schema")


def _verify_plan_review_v1(
    seal: dict[str, JsonValue],
    evidence_root: Path,
    brain_root: Path | None,
) -> None:
    reviewers = seal.get("reviewers")
    if not isinstance(reviewers, dict) or set(reviewers) != {"momus", "independent"}:
        raise ContractError("plan review must contain both reviewers")
    launches: set[str] = set()
    for name in ("momus", "independent"):
        reviewer = reviewers[name]
        if not isinstance(reviewer, dict) or reviewer.get("verdict") != "OKAY":
            raise ContractError(f"invalid {name} review record")
        record = reviewer.get("receipt")
        if not isinstance(record, dict):
            raise ContractError(f"missing {name} receipt record")
        relative = __import__("base64").b64decode(record["path_b64"], validate=True)
        path = evidence_root / relative.decode("utf-8")
        data = read_bytes_no_follow(path)
        if len(data) != record["size"] or digest(data) != record["sha256"]:
            raise ContractError(f"{name} receipt changed")
        header = _receipt(path, name, data)
        if (
            header["round_id"] != seal.get("round_id")
            or header["plan_sha256"] != seal.get("plan_sha256")
            or header["launch_id"] != reviewer.get("launch_id")
        ):
            raise ContractError(f"{name} receipt binding mismatch")
        launches.add(header["launch_id"])
    if len(launches) != 2:
        raise ContractError("review launch IDs must be distinct")
    if brain_root is not None:
        for role in ("plan", "draft"):
            record = seal.get(role)
            if not isinstance(record, dict):
                raise ContractError(f"missing {role} record")
            relative = __import__("base64").b64decode(record["path_b64"], validate=True)
            data = read_bytes_no_follow(brain_root / relative.decode("utf-8"))
            if len(data) != record["size"] or digest(data) != record["sha256"]:
                raise ContractError(f"{role} changed")
