from __future__ import annotations

import base64
import binascii
from datetime import UTC, datetime
from pathlib import Path
from typing import assert_never

from evidence_closure import SCHEMA as CLOSURE_SCHEMA, verify_wave4_closure_for_approval
from evidence_closure_records import PinnedJson, pin_json
from evidence_implementation import implementation_git_state_sha, implementation_sha
from evidence_json import (
    ContractError,
    JsonValue,
    canonical_bytes,
    create_json,
    digest,
    file_record,
    load_json,
    parse_json_bytes,
    read_bytes_no_follow,
    read_file_record,
)
from evidence_ledger import verify_ledger_checkpoint
from evidence_review import verify_plan_review
from evidence_seals import verify_todo

WAVE_RECEIPT_SCHEMA = "agent-brain-wave-receipt/v1"


def wave(
    number: int,
    plan: Path,
    draft: Path,
    review_seal: Path,
    source_baseline: Path,
    brain_baseline: Path,
    impl_root: Path,
    evidence_root: Path,
    output: Path,
) -> None:
    wave_todos = {1: range(1, 5), 2: range(1, 10), 3: range(1, 15), 4: range(1, 20)}
    if number not in wave_todos:
        raise ContractError("wave must be 1 through 4")
    brain_root = plan.parents[2]
    review = pin_json(review_seal)
    verify_plan_review(review_seal, evidence_root, brain_root, value=review.value)
    plan_sha = digest(read_bytes_no_follow(plan))
    draft_sha = digest(read_bytes_no_follow(draft))
    if (
        review.value.get("plan_sha256") != plan_sha
        or review.value.get("draft_sha256") != draft_sha
    ):
        raise ContractError("wave review seal does not bind plan and draft")
    source_record = file_record("evidence", evidence_root, source_baseline)
    brain_record = file_record("evidence", evidence_root, brain_baseline)
    receipts = []
    for todo in wave_todos[number]:
        path = evidence_root / f"task-{todo}-receipt.json"
        receipt = pin_json(path)
        verify_todo(path, evidence_root, receipt.value)
        if (
            receipt.value.get("source_state") != source_record
            or receipt.value.get("brain_state") != brain_record
        ):
            raise ContractError("wave todo immutable state mismatch")
        receipts.append(
            file_record("evidence", evidence_root, path, data=receipt.data)
        )
    create_json(
        output,
        {
            "baseline_commit": "993247b2850ac86993c7c6dd18e6c4fd9ec6df7c",
            "brain_state": brain_record,
            "completed_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "draft_sha256": draft_sha,
            "implementation_sha256": implementation_sha(impl_root),
            "implementation_git_state_sha256": implementation_git_state_sha(impl_root),
            "plan_sha256": plan_sha,
            "review_seal": file_record(
                "evidence",
                evidence_root,
                review_seal,
                data=review.data,
            ),
            "schema_version": "agent-brain-wave-receipt/v1",
            "source_state": source_record,
            "todos": receipts,
            "wave": number,
        },
    )


def _required_string(value: dict[str, JsonValue], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str):
        raise ContractError(f"wave receipt {key} is missing")
    return item


def immutable_states(
    receipt: dict[str, JsonValue],
) -> tuple[JsonValue, JsonValue]:
    match receipt:
        case {"schema_version": "agent-brain-wave-receipt/v1"}:
            return receipt.get("source_state"), receipt.get("brain_state")
        case {
            "schema_version": "agent-brain-wave-closure-v2",
            "source_and_brain": dict(states),
        }:
            return states.get("source"), states.get("brain")
        case unreachable:
            assert_never(unreachable)


def verify_wave_receipt(
    number: int,
    evidence_root: Path,
    impl_root: Path | None = None,
    receipt_path: Path | None = None,
    pinned: PinnedJson | None = None,
) -> None:
    receipt = receipt_path or evidence_root / f"wave-{number}-receipt.json"
    pinned_receipt = pin_json(receipt) if pinned is None else pinned
    value = pinned_receipt.value
    if value.get("schema_version") != "agent-brain-wave-receipt/v1" or value.get("wave") != number:
        raise ContractError("wave receipt number mismatch")
    if number == 4:
        plan_sha = _required_string(value, "plan_sha256")
        draft_sha = _required_string(value, "draft_sha256")
        implementation_product = _required_string(value, "implementation_sha256")
        implementation_git = _required_string(value, "implementation_git_state_sha256")
        if impl_root is not None:
            if implementation_sha(impl_root) != implementation_product:
                raise ContractError("wave implementation product mismatch")
            if implementation_git_state_sha(impl_root) != implementation_git:
                raise ContractError("wave implementation Git state mismatch")
        source_record = value.get("source_state")
        brain_record = value.get("brain_state")
        if not isinstance(source_record, dict) or not isinstance(brain_record, dict):
            raise ContractError("wave immutable state records are missing")
        read_file_record(source_record, {"evidence": evidence_root})
        read_file_record(brain_record, {"evidence": evidence_root})
        todos = value.get("todos")
        if not isinstance(todos, list) or len(todos) != 19:
            raise ContractError("wave receipt todo coverage mismatch")
        if not isinstance(value.get("review_seal"), dict):
            raise ContractError("wave review seal is missing")
        review_path, review_data = read_file_record(
            value["review_seal"], {"evidence": evidence_root}
        )
        review = parse_json_bytes(review_data, review_path)
        if review.get("plan_sha256") != plan_sha or review.get("draft_sha256") != draft_sha:
            raise ContractError("wave review seal binding mismatch")
        seen: set[int] = set()
        for expected, record in enumerate(todos, start=1):
            if not isinstance(record, dict):
                raise ContractError("invalid wave todo record")
            path, data = read_file_record(record, {"evidence": evidence_root})
            todo = parse_json_bytes(data, path)
            verify_todo(path, evidence_root, todo)
            if todo.get("todo") != expected or expected in seen:
                raise ContractError("wave todo ordering mismatch")
            seen.add(expected)
            if todo.get("source_state") != source_record or todo.get("brain_state") != brain_record:
                raise ContractError("wave todo immutable state mismatch")
            if todo.get("plan_sha256") != plan_sha:
                raise ContractError("wave todo plan mismatch")
            if todo.get("implementation_sha256") != implementation_product:
                raise ContractError("wave todo implementation mismatch")
            if todo.get("implementation_git_state_sha256") != implementation_git:
                raise ContractError("wave todo Git state mismatch")
        return
    for record in value.get("todos", []):
        if not isinstance(record, dict):
            raise ContractError("invalid wave todo record")
        path, data = read_file_record(record, {"evidence": evidence_root})
        verify_todo(path, evidence_root, parse_json_bytes(data, path))


def verify_wave(
    number: int,
    evidence_root: Path,
    impl_root: Path | None = None,
) -> dict[str, JsonValue]:
    receipt = evidence_root / f"wave-{number}-receipt.json"
    approval = evidence_root / f"wave-{number}-approval.json"
    approval_value = load_json(approval)
    schema = approval_value.get("receipt_schema")
    if schema is None:
        pinned_receipt = pin_json(receipt)
        verify_wave_receipt(number, evidence_root, impl_root, receipt, pinned_receipt)
        if approval_value.get("receipt_sha256") != digest(pinned_receipt.data):
            raise ContractError("wave approval binding mismatch")
    else:
        pinned_receipt = _approval_receipt(approval_value)
        receipt = pinned_receipt.path
        _verify_approval_message(number, approval_value)
        match schema:
            case "agent-brain-wave-receipt/v1":
                verify_wave_receipt(
                    number,
                    evidence_root,
                    impl_root,
                    receipt,
                    pinned_receipt,
                )
            case "agent-brain-wave-closure-v2":
                if number != 4:
                    raise ContractError("closure approval requires wave 4")
                verify_wave4_closure_for_approval(receipt, impl_root, pinned_receipt)
            case _:
                raise ContractError("unsupported wave approval receipt schema")
    if number == 4:
        ledger = approval_value.get("ledger_checkpoint")
        if not isinstance(ledger, dict):
            raise ContractError("wave 4 approval ledger checkpoint is missing")
        checkpoint, checkpoint_data = read_file_record(
            ledger, {"evidence": evidence_root}
        )
        verify_ledger_checkpoint(
            checkpoint,
            evidence_root,
            "wave-4-approval",
            value=parse_json_bytes(checkpoint_data, checkpoint),
        )
    receipt_size = approval_value.get("receipt_size")
    if approval_value.get("receipt_sha256") != digest(pinned_receipt.data):
        raise ContractError("wave approval binding mismatch")
    if receipt_size is not None and receipt_size != len(pinned_receipt.data):
        raise ContractError("wave approval binding mismatch")
    if canonical_bytes(pinned_receipt.value) != pinned_receipt.data:
        raise ContractError("wave approval binding mismatch")
    if read_bytes_no_follow(receipt) != pinned_receipt.data:
        raise ContractError("wave approval binding mismatch")
    return pinned_receipt.value


def _approval_receipt(approval: dict[str, JsonValue]) -> PinnedJson:
    schema = approval.get("receipt_schema")
    path = approval.get("receipt_path")
    expected_hash = approval.get("receipt_sha256")
    expected_size = approval.get("receipt_size")
    if not isinstance(schema, str) or not isinstance(path, str):
        raise ContractError("wave approval receipt binding is missing")
    if not isinstance(expected_hash, str) or not isinstance(expected_size, int):
        raise ContractError("wave approval receipt hash binding is missing")
    receipt = Path(path)
    pinned = pin_json(receipt)
    if digest(pinned.data) != expected_hash or len(pinned.data) != expected_size:
        raise ContractError("wave approval binding mismatch")
    if pinned.value.get("schema_version") != schema:
        raise ContractError("wave approval receipt schema mismatch")
    return pinned


def _verify_approval_message(number: int, approval: dict[str, JsonValue]) -> None:
    path = approval.get("message_path")
    expected_hash = approval.get("message_sha256")
    expected_size = approval.get("message_size")
    expected_bytes = approval.get("message_bytes_b64")
    lf = approval.get("message_lf")
    receipt_hash = approval.get("receipt_sha256")
    if not isinstance(path, str):
        raise ContractError("wave approval message path binding is missing")
    if not isinstance(expected_hash, str) or not isinstance(expected_size, int):
        raise ContractError("wave approval message hash binding is missing")
    if not isinstance(expected_bytes, str) or lf is not True:
        raise ContractError("wave approval message byte binding is missing")
    if not isinstance(receipt_hash, str):
        raise ContractError("wave approval receipt hash binding is missing")
    try:
        bound_bytes = base64.b64decode(expected_bytes, validate=True)
    except (ValueError, binascii.Error) as error:
        raise ContractError("wave approval message byte binding is invalid") from error
    message = Path(path)
    data = read_bytes_no_follow(message)
    expected = f"APPROVE wave {number} {receipt_hash}\n".encode()
    if data != expected or bound_bytes != expected:
        raise ContractError("wave approval message content mismatch")
    if len(data) != expected_size or digest(data) != expected_hash:
        raise ContractError("wave approval message binding mismatch")
