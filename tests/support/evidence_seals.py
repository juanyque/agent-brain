from __future__ import annotations

import base64
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import assert_never

from evidence_closure_records import PinnedFile, PinnedJson, pin_file, pin_json
from evidence_json import (
    ContractError,
    JsonValue,
    canonical_bytes,
    create_bytes_pair,
    create_json,
    decode_path,
    digest,
    encode_path,
    file_record,
    load_json,
    parse_json_bytes,
    read_bytes_no_follow,
    read_file_record,
)
from evidence_implementation import implementation_git_state_sha, implementation_sha, implementation_snapshot
from evidence_ledger import LEDGER_RELATIVE_PATH, create_ledger_checkpoint, verify_ledger_checkpoint
from evidence_review import verify_plan_review
from evidence_todo import seal_todo, verify_run, verify_todo


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _verify_record(record: JsonValue, roots: dict[str, Path]) -> Path:
    path, _data = read_file_record(record, roots)
    return path


def _pinned_record(record: JsonValue, roots: dict[str, Path]) -> PinnedFile:
    path, data = read_file_record(record, roots)
    return PinnedFile(path, data)


def _pinned_json_record(record: JsonValue, roots: dict[str, Path]) -> PinnedJson:
    pinned = _pinned_record(record, roots)
    return PinnedJson(
        pinned.path,
        pinned.data,
        parse_json_bytes(pinned.data, pinned.path),
    )


def _evidence_relative(path: Path, evidence_root: Path) -> bytes:
    try:
        return os.fsencode(path.relative_to(evidence_root))
    except ValueError as error:
        raise ContractError(f"path is outside evidence root: {path}") from error


def _allowed_post_freeze(relative: bytes) -> bool:
    text = os.fsdecode(relative)
    if text in {"F1-runs", "F2-runs", "F3-runs", "F4-runs"}:
        return True
    if re.fullmatch(r"F[1-4]-runs/[^/]+", text):
        return True
    if re.fullmatch(r"F[1-4]-pycache(/.*)?", text):
        return True
    if re.fullmatch(r"f[1-4]-freeze-[^/]+\.json", text):
        return True
    if text in {
        "f1-plan-compliance.json",
        "f2-code-quality.json",
        "f3-manual-qa.json",
        "f3-artifacts.tar",
        "f3-artifacts.manifest.json",
        "f4-scope-fidelity.json",
    }:
        return True
    return False


def _scan_evidence_files(
    evidence_root: Path,
    excluded: set[bytes],
    pinned_files: dict[bytes, bytes] | None = None,
) -> list[dict[str, JsonValue]]:
    base = os.fsencode(evidence_root)
    pinned_files = {} if pinned_files is None else pinned_files
    records: list[dict[str, JsonValue]] = []

    def visit(relative: bytes) -> None:
        absolute = base + (b"/" + relative if relative else b"")
        with os.scandir(absolute) as iterator:
            children = sorted(iterator, key=lambda item: os.fsencode(item.name))
        for child in children:
            name = os.fsencode(child.name)
            child_relative = name if not relative else relative + b"/" + name
            if child_relative in excluded or _allowed_post_freeze(child_relative):
                continue
            info = child.stat(follow_symlinks=False)
            if os.path.islink(base + b"/" + child_relative):
                raise ContractError("freeze evidence contains symlink")
            if os.path.isdir(base + b"/" + child_relative):
                records.append({
                    "path_b64": encode_path(child_relative),
                    "root": "evidence",
                    "type": "directory",
                })
                visit(child_relative)
                continue
            if not os.path.isfile(base + b"/" + child_relative):
                raise ContractError("freeze evidence contains unsupported entry")
            child_absolute = base + b"/" + child_relative
            data = pinned_files.get(child_absolute)
            if data is None:
                data = read_bytes_no_follow(Path(os.fsdecode(child_absolute)))
            records.append({
                "path_b64": encode_path(child_relative),
                "root": "evidence",
                "sha256": digest(data),
                "size": len(data),
                "type": "file",
            })

    visit(b"")
    return sorted(records, key=lambda record: decode_path(record["path_b64"]))


def _verify_frozen_evidence(
    records: JsonValue,
    evidence_root: Path,
    excluded: set[bytes],
) -> None:
    if not isinstance(records, list):
        raise ContractError("freeze evidence must be an array")
    expected = _scan_evidence_files(evidence_root, excluded)
    if canonical_bytes(records) != canonical_bytes(expected):
        raise ContractError("freeze evidence closure mismatch")
    for record in records:
        if isinstance(record, dict) and record.get("type") == "file":
            _verify_record(record, {"evidence": evidence_root})


def approve(
    kind: str,
    number: str,
    receipt: Path,
    message: Path,
    output: Path,
    impl_root: Path | None = None,
    evidence_root: Path | None = None,
    prior_ledger_checkpoint: Path | None = None,
) -> None:
    pinned_receipt = pin_json(receipt)
    receipt_sha = digest(pinned_receipt.data)
    expected = f"APPROVE {kind} {number} {receipt_sha}\n".encode()
    message_data = pin_file(message).data
    if message_data != expected:
        raise ContractError("approval text/hash mismatch")
    receipt_value = pinned_receipt.value
    receipt_schema = receipt_value.get("schema_version")
    if not isinstance(receipt_schema, str):
        raise ContractError("approval receipt schema is missing")
    ledger_record: JsonValue = None
    if kind == "wave" and number == "4":
        from evidence_closure import verify_wave4_closure_for_approval
        from evidence_wave import verify_wave_receipt

        if impl_root is None or evidence_root is None:
            raise ContractError("wave 4 approval requires implementation and evidence roots")
        match receipt_schema:
            case "agent-brain-wave-receipt/v1":
                verify_wave_receipt(4, evidence_root, impl_root, receipt, pinned_receipt)
            case "agent-brain-wave-closure-v2":
                verify_wave4_closure_for_approval(receipt, impl_root, pinned_receipt)
            case _:
                raise ContractError("unsupported wave receipt schema")
        checkpoint = output.with_suffix(".ledger-checkpoint.json")
        bytes_output = output.with_suffix(".ledger.jsonl")
        create_ledger_checkpoint(
            impl_root,
            evidence_root,
            checkpoint,
            bytes_output,
            prior_ledger_checkpoint,
            phase="wave-4-approval",
        )
        ledger_record = file_record("evidence", evidence_root, checkpoint)
    elif impl_root is not None or evidence_root is not None:
        raise ContractError("ledger checkpoint is only bound at wave 4 approval")
    value = {
        "approved_at": _now(),
        "ledger_checkpoint": ledger_record,
        "message_bytes_b64": base64.b64encode(message_data).decode("ascii"),
        "message_lf": message_data.endswith(b"\n"),
        "message_path": str(message.resolve()),
        "message_sha256": digest(message_data),
        "message_size": len(message_data),
        "receipt_path": str(receipt.resolve()),
        "receipt_schema": receipt_schema,
        "receipt_sha256": receipt_sha,
        "receipt_size": len(pinned_receipt.data),
        "schema_version": f"agent-brain-{kind}-approval/v1",
    }
    create_json(output, value)


def freeze(
    plan: Path,
    draft: Path,
    review_seal: Path,
    impl_root: Path,
    evidence_root: Path,
    output: Path,
    prior_ledger_checkpoint: Path | None = None,
) -> None:
    from evidence_wave import verify_wave

    verify_wave(4, evidence_root, impl_root)
    review = pin_json(review_seal)
    verify_plan_review(
        review_seal,
        evidence_root,
        draft.parents[2],
        impl_root,
        review.value,
    )
    plan_sha = digest(read_bytes_no_follow(plan))
    draft_sha = digest(read_bytes_no_follow(draft))
    if (
        review.value.get("plan_sha256") != plan_sha
        or review.value.get("draft_sha256") != draft_sha
    ):
        raise ContractError("freeze review seal does not bind plan and draft")
    ledger_checkpoint = output.with_suffix(".ledger-checkpoint.json")
    ledger_bytes = output.with_suffix(".ledger.jsonl")
    manifest = output.with_suffix(".implementation-manifest.json")
    archive = output.with_suffix(".implementation.tar")
    if (impl_root / LEDGER_RELATIVE_PATH).exists() or (impl_root / LEDGER_RELATIVE_PATH).is_symlink():
        if prior_ledger_checkpoint is None:
            raise ContractError("freeze requires wave 4 ledger checkpoint")
        create_ledger_checkpoint(
            impl_root,
            evidence_root,
            ledger_checkpoint,
            ledger_bytes,
            prior_ledger_checkpoint,
            phase="final-freeze",
            prior_phase="wave-4-approval",
        )
    snapshot = implementation_snapshot(impl_root, manifest, archive)
    excluded = {_evidence_relative(output, evidence_root)}
    records = _scan_evidence_files(
        evidence_root,
        excluded,
        {
            os.fsencode(archive): snapshot.archive.data,
            os.fsencode(manifest): snapshot.manifest.data,
        },
    )
    value = {
        "created_at": _now(),
        "draft_sha256": draft_sha,
        "evidence": records,
        "implementation": {
            "archive": os.fsdecode(_evidence_relative(archive, evidence_root)),
            "git_state_sha256": snapshot.git_state_sha256,
            "manifest": os.fsdecode(_evidence_relative(manifest, evidence_root)),
            "sha256": snapshot.sha256,
        },
        "implementation_git_state_sha256": snapshot.git_state_sha256,
        "implementation_sha256": snapshot.sha256,
        "ledger_checkpoint": (
            file_record("evidence", evidence_root, ledger_checkpoint)
            if ledger_checkpoint.exists()
            else None
        ),
        "plan_sha256": plan_sha,
        "review_seal_sha256": digest(review.data),
        "schema_version": "agent-brain-final-freeze/v1",
    }
    create_json(output, value)


def verify_freeze(
    freeze_path: Path,
    evidence_root: Path,
    recompute: Path | None,
    impl_root: Path,
) -> PinnedJson:
    freeze = pin_json(freeze_path)
    value = freeze.value
    if value.get("schema_version") != "agent-brain-final-freeze/v1":
        raise ContractError("invalid freeze schema")
    expected_product = value.get("implementation_sha256")
    if not isinstance(expected_product, str) or implementation_sha(impl_root) != expected_product:
        raise ContractError("freeze implementation product mismatch")
    expected_git = value.get("implementation_git_state_sha256")
    if isinstance(expected_git, str) and implementation_git_state_sha(impl_root) != expected_git:
        raise ContractError("freeze implementation Git state mismatch")
    excluded = {_evidence_relative(freeze_path, evidence_root)}
    if recompute is not None:
        try:
            recompute_relative = _evidence_relative(recompute, evidence_root)
        except ContractError:
            recompute_relative = b""
        if recompute_relative:
            excluded.add(recompute_relative)
    _verify_frozen_evidence(value.get("evidence"), evidence_root, excluded)
    ledger_checkpoint = value.get("ledger_checkpoint")
    if ledger_checkpoint is None:
        raise ContractError("freeze ledger checkpoint is missing")
    checkpoint = _pinned_json_record(
        ledger_checkpoint,
        {"evidence": evidence_root},
    )
    verify_ledger_checkpoint(
        checkpoint.path,
        evidence_root,
        "final-freeze",
        value=checkpoint.value,
    )
    if recompute is not None:
        create_json(recompute, value)
    return freeze


def final_review(
    freeze_path: Path,
    lanes: list[Path],
    output: Path,
    impl_root: Path | None = None,
    evidence_root: Path | None = None,
    prior_ledger_checkpoint: Path | None = None,
) -> None:
    if impl_root is None or evidence_root is None or prior_ledger_checkpoint is None:
        raise ContractError("final review requires implementation, evidence, and freeze checkpoint")
    freeze = verify_freeze(freeze_path, evidence_root, None, impl_root)
    lane_records = _verify_lane_set(freeze, lanes, evidence_root)
    checkpoint = output.with_suffix(".ledger-checkpoint.json")
    bytes_output = output.with_suffix(".ledger.jsonl")
    create_ledger_checkpoint(
        impl_root,
        evidence_root,
        checkpoint,
        bytes_output,
        prior_ledger_checkpoint,
        phase="final-review",
        prior_phase="final-freeze",
    )
    ledger_record: JsonValue = file_record("evidence", evidence_root, checkpoint)
    create_json(
        output,
        {
            "created_at": _now(),
            "freeze": file_record(
                "evidence",
                evidence_root,
                freeze_path,
                data=freeze.data,
            ),
            "freeze_sha256": digest(freeze.data),
            "lanes": lane_records,
            "ledger_checkpoint": ledger_record,
            "schema_version": "agent-brain-final-review/v1",
        },
    )


def lane_record(
    lane: str,
    freeze_path: Path,
    runs: Path,
    before: Path,
    after: Path,
    output: Path,
    extra_fields: dict[str, JsonValue] | None = None,
) -> None:
    freeze = pin_json(freeze_path)
    freeze_data = freeze.data
    before_data = read_bytes_no_follow(before)
    after_data = read_bytes_no_follow(after)
    if before_data != freeze_data or after_data != freeze_data:
        raise ContractError("freeze changed during lane")
    run_paths = sorted(runs.glob("*.json"), key=lambda path: int(path.stem))
    if not run_paths:
        raise ContractError("lane has no run records")
    freeze_value = freeze.value
    expected_product = freeze_value.get("implementation_sha256")
    expected_git = freeze_value.get("implementation_git_state_sha256")
    if not isinstance(expected_product, str) or not isinstance(expected_git, str):
        raise ContractError("freeze implementation hashes are missing")
    run_records: list[dict[str, JsonValue]] = []
    command_manifest: list[dict[str, JsonValue]] = []
    for path in run_paths:
        pinned_run = pin_json(path)
        run = verify_run(path, output.parent, pinned_run.value)
        if run.get("scope") != "lane" or run.get("identity") != lane:
            raise ContractError("lane run identity mismatch")
        if run.get("freeze_sha256") != digest(freeze_data):
            raise ContractError("lane run freeze mismatch")
        if run.get("implementation_product_sha256") != expected_product:
            raise ContractError("lane run product mismatch")
        if run.get("implementation_git_state_sha256") != expected_git:
            raise ContractError("lane run Git mismatch")
        command_manifest.append({
            "command": run.get("command"),
            "exit_status": run.get("exit_status"),
            "mode": run.get("mode"),
            "step": run.get("step"),
        })
        run_records.append(
            file_record("evidence", output.parent, path, data=pinned_run.data)
        )
    value: dict[str, JsonValue] = {
        "after": file_record("evidence", output.parent, after, data=after_data),
        "before": file_record("evidence", output.parent, before, data=before_data),
        "command_manifest": command_manifest,
        "findings": [],
        "freeze_sha256": digest(freeze_data),
        "implementation_git_state_sha256": expected_git,
        "implementation_sha256": expected_product,
        "lane": lane,
        "run_count": len(run_records),
        "runs": run_records,
        "schema_version": "agent-brain-final-lane/v1",
        "verdict": "APPROVE",
    }
    if extra_fields is not None:
        value.update(extra_fields)
    create_json(
        output,
        value,
    )


LANE_OUTPUTS: dict[str, str] = {
    "F1": "f1-plan-compliance.json",
    "F2": "f2-code-quality.json",
    "F3": "f3-manual-qa.json",
    "F4": "f4-scope-fidelity.json",
}


def _verify_lane_record(
    pinned: PinnedJson,
    freeze: PinnedJson,
    evidence_root: Path,
) -> tuple[dict[str, JsonValue], str]:
    path = pinned.path
    lane = pinned.value
    if lane.get("schema_version") != "agent-brain-final-lane/v1":
        raise ContractError("invalid final lane schema")
    lane_name = lane.get("lane")
    if not isinstance(lane_name, str) or LANE_OUTPUTS.get(lane_name) != path.name:
        raise ContractError("final lane identity mismatch")
    if lane.get("verdict") != "APPROVE" or lane.get("findings") != []:
        raise ContractError("final lane did not approve")
    freeze_sha = digest(freeze.data)
    if lane.get("freeze_sha256") != freeze_sha:
        raise ContractError("final lane freeze mismatch")
    freeze_value = freeze.value
    expected_product = freeze_value.get("implementation_sha256")
    expected_git = freeze_value.get("implementation_git_state_sha256")
    if lane.get("implementation_sha256") != expected_product:
        raise ContractError("final lane product mismatch")
    if lane.get("implementation_git_state_sha256") != expected_git:
        raise ContractError("final lane Git mismatch")
    roots = {"evidence": evidence_root}
    for role in ("before", "after"):
        _path, data = read_file_record(lane.get(role), roots)
        if data != freeze.data:
            raise ContractError("final lane freeze copy mismatch")
    runs = lane.get("runs")
    if not isinstance(runs, list) or not runs:
        raise ContractError("final lane run records are missing")
    if lane.get("run_count") != len(runs):
        raise ContractError("final lane run count mismatch")
    expected_manifest = lane.get("command_manifest")
    if not isinstance(expected_manifest, list) or len(expected_manifest) != len(runs):
        raise ContractError("final lane command manifest is missing")
    actual_manifest: list[dict[str, JsonValue]] = []
    for index, record in enumerate(runs, start=1):
        run_path, run_bytes = read_file_record(record, roots)
        run = verify_run(
            run_path,
            evidence_root,
            parse_json_bytes(run_bytes, run_path),
        )
        if run.get("scope") != "lane" or run.get("identity") != lane_name or run.get("step") != index:
            raise ContractError("final lane run ordering mismatch")
        if run.get("freeze_sha256") != freeze_sha:
            raise ContractError("final lane run freeze mismatch")
        if run.get("implementation_product_sha256") != expected_product:
            raise ContractError("final lane run product mismatch")
        if run.get("implementation_git_state_sha256") != expected_git:
            raise ContractError("final lane run Git mismatch")
        environment = run.get("environment_contract")
        if not isinstance(environment, dict):
            raise ContractError("final lane run environment is missing")
        for key, value in {
            "GIT_OPTIONAL_LOCKS": "0",
            "LC_ALL": "C",
            "PYTHONDONTWRITEBYTECODE": "1",
        }.items():
            if environment.get(key) != value:
                raise ContractError("final lane run environment mismatch")
        pycache = environment.get("PYTHONPYCACHEPREFIX")
        if not isinstance(pycache, str):
            raise ContractError("final lane pycache route is missing")
        try:
            Path(pycache).resolve().relative_to(evidence_root.resolve())
        except ValueError as error:
            raise ContractError("final lane pycache route escapes evidence") from error
        actual_manifest.append({
            "command": run.get("command"),
            "exit_status": run.get("exit_status"),
            "mode": run.get("mode"),
            "step": run.get("step"),
        })
    if actual_manifest != expected_manifest:
        raise ContractError("final lane command manifest mismatch")
    if lane_name == "F3":
        _verify_f3_lane_bindings(lane, roots)
    return (
        file_record("evidence", evidence_root, path, data=pinned.data),
        lane_name,
    )


def _verify_f3_lane_bindings(lane: dict[str, JsonValue], roots: dict[str, Path]) -> None:
    for role in ("artifact", "artifact_manifest"):
        _verify_record(lane.get(role), roots)
    parity = lane.get("parity")
    if parity != {
        "connected_brain_equal": True,
        "frozen_equal": True,
        "source_equal": True,
        "temp_brain_equal": True,
    }:
        raise ContractError("F3 parity binding mismatch")
    statuses = lane.get("command_statuses")
    manifest = lane.get("command_manifest")
    if not isinstance(statuses, list) or not isinstance(manifest, list):
        raise ContractError("F3 command status binding is missing")
    actual_statuses = [
        entry.get("exit_status")
        for entry in manifest
        if isinstance(entry, dict)
    ]
    if statuses != actual_statuses or statuses != [0] * len(actual_statuses):
        raise ContractError("F3 command status binding mismatch")


def _verify_lane_set(
    freeze: PinnedJson,
    lanes: list[Path | PinnedJson],
    evidence_root: Path,
) -> list[dict[str, JsonValue]]:
    if len(lanes) != len(LANE_OUTPUTS):
        raise ContractError("final review lane coverage mismatch")
    records: list[dict[str, JsonValue]] = []
    seen: set[str] = set()
    pinned_lanes: list[PinnedJson] = []
    for candidate in lanes:
        match candidate:
            case Path():
                pinned_lanes.append(pin_json(candidate))
            case PinnedJson():
                pinned_lanes.append(candidate)
            case unreachable:
                assert_never(unreachable)
    for pinned_lane in sorted(pinned_lanes, key=lambda candidate: candidate.path.name):
        record, lane_name = _verify_lane_record(
            pinned_lane,
            freeze,
            evidence_root,
        )
        if lane_name in seen:
            raise ContractError("final review duplicate lane")
        seen.add(lane_name)
        records.append(record)
    if seen != set(LANE_OUTPUTS):
        raise ContractError("final review lane coverage mismatch")
    return records


def final_approve(review: Path, message: Path, output: Path) -> None:
    review_sha = digest(read_bytes_no_follow(review))
    expected = f"APPROVE final {review_sha}\n".encode()
    if read_bytes_no_follow(message) != expected:
        raise ContractError("final approval text/hash mismatch")
    create_json(
        output,
        {
            "approved_at": _now(),
            "message_sha256": digest(expected),
            "review_sha256": review_sha,
            "schema_version": "agent-brain-final-approval/v1",
        },
    )


def finalize(
    review: Path,
    approval: Path,
    evidence_root: Path,
    output: Path,
    impl_root: Path | None = None,
    prior_ledger_checkpoint: Path | None = None,
) -> None:
    pinned_approval = pin_json(approval)
    pinned_review = pin_json(review)
    approval_value = pinned_approval.value
    if approval_value.get("review_sha256") != digest(pinned_review.data):
        raise ContractError("final approval does not bind review")
    if impl_root is None or prior_ledger_checkpoint is None:
        raise ContractError("completion requires implementation root and final review checkpoint")
    checkpoint = output.with_suffix(".ledger-checkpoint.json")
    bytes_output = output.with_suffix(".ledger.jsonl")
    create_ledger_checkpoint(
        impl_root,
        evidence_root,
        checkpoint,
        bytes_output,
        prior_ledger_checkpoint,
        phase="completion",
        prior_phase="final-review",
    )
    ledger_record: JsonValue = file_record("evidence", evidence_root, checkpoint)
    create_json(
        output,
        {
            "approval": file_record(
                "evidence",
                evidence_root,
                approval,
                data=pinned_approval.data,
            ),
            "completed_at": _now(),
            "ledger_checkpoint": ledger_record,
            "review": file_record(
                "evidence",
                evidence_root,
                review,
                data=pinned_review.data,
            ),
            "schema_version": "agent-brain-completion/v1",
        },
    )


def verify_completion(path: Path, evidence_root: Path) -> None:
    value = pin_json(path).value
    if value.get("schema_version") != "agent-brain-completion/v1":
        raise ContractError("invalid completion schema")
    roots = {"evidence": evidence_root}
    review = _pinned_json_record(value.get("review"), roots)
    approval = _pinned_json_record(value.get("approval"), roots)
    ledger_checkpoint = value.get("ledger_checkpoint")
    if ledger_checkpoint is None:
        raise ContractError("completion ledger checkpoint is missing")
    checkpoint = _pinned_json_record(ledger_checkpoint, roots)
    verify_ledger_checkpoint(
        checkpoint.path,
        evidence_root,
        "completion",
        value=checkpoint.value,
    )
    if approval.value.get("review_sha256") != digest(review.data):
        raise ContractError("completion approval binding mismatch")
    freeze = _pinned_json_record(review.value.get("freeze"), roots)
    lanes = review.value.get("lanes")
    if not isinstance(lanes, list):
        raise ContractError("completion final review lanes are missing")
    pinned_lanes = [_pinned_json_record(record, roots) for record in lanes]
    _verify_lane_set(freeze, pinned_lanes, evidence_root)


def freeze_context(source: Path, source_digest: Path, output: Path, output_digest: Path) -> None:
    data = read_bytes_no_follow(source)
    expected = read_bytes_no_follow(source_digest).decode("ascii").strip()
    if digest(data) != expected:
        raise ContractError("context baseline digest mismatch")
    create_bytes_pair((output, data), (output_digest, (expected + "\n").encode()))
