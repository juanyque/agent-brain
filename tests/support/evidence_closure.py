from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from evidence_approval_reports import (
    GATE_CONTRACT,
    TOOLING_CONTRACT,
    ReportBindings,
    create_report_summary,
    verify_report_summary,
)
from evidence_closure_records import (
    PinnedFile,
    PinnedJson,
    file_ref,
    pin_file,
    pin_json,
    plan_checklist_bytes,
    provenance_ref,
    state_ref,
    verify_evidence_records,
    verify_file_ref,
    verify_json_ref,
    verify_provenance_ref,
    verify_state_ref,
)
from evidence_implementation import (
    active_plan_sha_from_snapshot,
    implementation_sha,
    manifest_implementation_git_sha,
    manifest_implementation_sha,
    verify_implementation_snapshot,
)
from evidence_json import (
    ContractError,
    JsonValue,
    canonical_bytes,
    create_bytes_pair,
    digest,
    parse_json_bytes,
    read_bytes_no_follow,
)
from evidence_review import verify_plan_review
from evidence_state import compare_state_values
from evidence_todo import verify_run, verify_todo

SCHEMA = "agent-brain-wave-closure-v2"
PLAN_KEYS = {"checked_todos", "path", "sha256", "unchecked_todos"}
IMPL_KEYS = {
    "archive_path",
    "archive_sha256",
    "archive_size",
    "manifest_path",
    "manifest_sha256",
    "manifest_size",
    "root",
    "sha256",
}
RECEIPT_KEYS = {"evidence_root", "path", "sha256", "size", "todo"}
STATE_KEYS = {"after", "before"}
LEGACY_TOP_KEYS = {
    "accepted_task_receipts",
    "active_plan",
    "approval_command_sidecar",
    "cleanup",
    "created_at",
    "governed_runs",
    "implementation",
    "reports",
    "schema_version",
    "source_and_brain",
    "superseded_receipts",
    "verdict",
    "wave",
}
APPROVAL_REQUIRED_KEYS = {"draft", "independent_gate", "review_seal", "tooling_review"}
TOP_KEYS = LEGACY_TOP_KEYS | {"approval_required"}


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _rows(values: list[list[str]] | None) -> list[dict[str, JsonValue]]:
    result: list[dict[str, JsonValue]] = []
    for item in values or []:
        todo = int(item[0])
        path = Path(item[1])
        row = file_ref(path)
        row["todo"] = todo
        if len(item) == 3:
            row["evidence_root"] = str(Path(item[2]))
        result.append(row)
    return result


def _state(before: list[str], after: list[str]) -> dict[str, JsonValue]:
    return {
        "after": state_ref(Path(after[0]), Path(after[1])),
        "before": state_ref(Path(before[0]), Path(before[1])),
    }


def create_wave_closure(arguments) -> None:
    plan_data = read_bytes_no_follow(arguments.plan)
    checked, unchecked = plan_checklist_bytes(plan_data, arguments.plan)
    task_rows = _rows(arguments.task_receipt)
    run_rows = _rows(arguments.governed_run)
    archive = pin_file(arguments.implementation_archive)
    manifest = pin_json(arguments.implementation_manifest)
    implementation_product_sha = manifest_implementation_sha(manifest)
    verify_implementation_snapshot(
        manifest,
        archive,
        implementation_product_sha,
    )
    if implementation_sha(arguments.impl_root) != implementation_product_sha:
        raise ContractError("current implementation does not match closure")
    if active_plan_sha_from_snapshot(manifest, archive) != digest(plan_data):
        raise ContractError("closure plan does not match implementation snapshot")
    implementation = {
        "archive_path": str(arguments.implementation_archive),
        "archive_sha256": digest(archive.data),
        "archive_size": len(archive.data),
        "manifest_path": str(arguments.implementation_manifest),
        "manifest_sha256": digest(manifest.data),
        "manifest_size": len(manifest.data),
        "root": str(arguments.impl_root),
        "sha256": implementation_product_sha,
    }
    report_paths = [Path(path) for path in arguments.report or []]
    approval_paths = (
        arguments.draft,
        arguments.review_seal,
        arguments.tooling_review,
        arguments.independent_gate,
    )
    tooling_summary: Path | None = None
    gate_summary: Path | None = None
    if all(path is not None for path in approval_paths):
        git_state = manifest_implementation_git_sha(manifest)
        if git_state is None:
            raise ContractError("closure approval report requires Git state")
        bindings = _report_bindings(
            str(implementation["sha256"]),
            git_state,
            digest(plan_data),
            task_rows,
            run_rows,
        )
        tooling_summary = arguments.output.with_name("tooling-review-summary.json")
        gate_summary = arguments.output.with_name("independent-gate-summary.json")
        create_report_summary(arguments.tooling_review, tooling_summary, TOOLING_CONTRACT, bindings)
        create_report_summary(arguments.independent_gate, gate_summary, GATE_CONTRACT, bindings)
        report_paths.extend([arguments.tooling_review, arguments.independent_gate])
    elif any(path is not None for path in approval_paths):
        raise ContractError("closure approval provenance is incomplete")
    receipt: dict[str, JsonValue] = {
        "accepted_task_receipts": task_rows,
        "active_plan": {
            "checked_todos": checked,
            "path": str(arguments.plan),
            "sha256": digest(plan_data),
            "unchecked_todos": unchecked,
        },
        "approval_command_sidecar": str(arguments.output.parent / "approval-command.txt"),
        "cleanup": [file_ref(Path(path)) for path in arguments.cleanup or []],
        "created_at": _now(),
        "governed_runs": run_rows,
        "implementation": implementation,
        "reports": [file_ref(path) for path in report_paths],
        "schema_version": SCHEMA,
        "source_and_brain": {
            "brain": _state(arguments.brain_before, arguments.brain_after),
            "source": _state(arguments.source_before, arguments.source_after),
        },
        "superseded_receipts": _rows(arguments.superseded_receipt),
        "verdict": "READY",
        "wave": arguments.wave,
    }
    if tooling_summary is not None and gate_summary is not None:
        receipt["approval_required"] = {
            "draft": provenance_ref(arguments.draft, "brain", "reviewed-draft"),
            "independent_gate": provenance_ref(gate_summary, "evidence", "independent-gate-report"),
            "review_seal": provenance_ref(arguments.review_seal, "evidence", "review-seal"),
            "tooling_review": provenance_ref(tooling_summary, "evidence", "tooling-review"),
        }
    receipt_data = canonical_bytes(receipt)
    command = f"APPROVE wave {arguments.wave} {digest(receipt_data)}\n".encode("utf-8")
    create_bytes_pair(
        (arguments.output, receipt_data),
        (arguments.output.parent / "approval-command.txt", command),
    )
    verify_wave_closure(arguments.output)


def _expect_keys(name: str, row: JsonValue, keys: set[str]) -> dict[str, JsonValue]:
    if not isinstance(row, dict) or set(row) != keys:
        raise ContractError(f"invalid {name} schema")
    return row


def _unique(values: list[int], name: str) -> None:
    if sorted(set(values)) != sorted(values):
        raise ContractError(f"duplicate {name}")


def _verify_task(row: dict[str, JsonValue], plan_sha: str, impl: dict[str, JsonValue]) -> dict[str, JsonValue]:
    receipt = _verify_row_file(row)
    root = Path(str(row["evidence_root"]))
    verify_todo(receipt.path, root, receipt.value)
    if receipt.value.get("plan_sha256") != plan_sha:
        raise ContractError("todo receipt plan does not match closure")
    if receipt.value.get("implementation_sha256") != impl["sha256"]:
        raise ContractError("todo receipt implementation does not match closure")
    manifest = receipt.value.get("implementation_manifest")
    archive = receipt.value.get("implementation_archive")
    if not isinstance(manifest, dict) or not isinstance(archive, dict):
        raise ContractError("todo receipt lacks immutable implementation")
    if manifest.get("sha256") != impl["manifest_sha256"]:
        raise ContractError("todo receipt manifest does not match closure")
    if archive.get("sha256") != impl["archive_sha256"]:
        raise ContractError("todo receipt archive does not match closure")
    verify_evidence_records(receipt.value, root)
    return receipt.value


def _run_sha_set(receipt: dict[str, JsonValue]) -> set[str]:
    runs = receipt.get("runs")
    if not isinstance(runs, list):
        raise ContractError("todo receipt runs must be an array")
    return {str(row["sha256"]) for row in runs if isinstance(row, dict)}


def _verify_row_file(row: dict[str, JsonValue]) -> PinnedJson:
    return verify_json_ref(
        {"path": row["path"], "sha256": row["sha256"], "size": row["size"]}
    )


def verify_wave_closure(
    receipt_path: Path,
    pinned: PinnedJson | None = None,
) -> dict[str, JsonValue]:
    receipt, _manifest, _archive = _verified_wave_closure(receipt_path, pinned)
    return receipt


def _verified_wave_closure(
    receipt_path: Path,
    pinned: PinnedJson | None = None,
) -> tuple[dict[str, JsonValue], PinnedJson, PinnedFile]:
    closure = pin_json(receipt_path) if pinned is None else pinned
    receipt = closure.value
    keys = set(receipt)
    if keys == TOP_KEYS:
        legacy = False
    elif keys == LEGACY_TOP_KEYS:
        legacy = True
    else:
        raise ContractError("invalid closure schema")
    if closure.data != canonical_bytes(receipt):
        raise ContractError("closure receipt is not canonical")
    if receipt["schema_version"] != SCHEMA or receipt["verdict"] != "READY":
        raise ContractError("invalid closure status")
    plan = _expect_keys("active plan", receipt["active_plan"], PLAN_KEYS)
    plan_path = Path(str(plan["path"]))
    plan_data = read_bytes_no_follow(plan_path)
    checked, unchecked = plan_checklist_bytes(plan_data, plan_path)
    if digest(plan_data) != plan["sha256"]:
        raise ContractError("active plan changed")
    if checked != plan["checked_todos"] or unchecked != plan["unchecked_todos"]:
        raise ContractError("active plan checklist changed")
    impl = _expect_keys("implementation", receipt["implementation"], IMPL_KEYS)
    manifest, archive = _verify_implementation(impl)
    if active_plan_sha_from_snapshot(manifest, archive) != plan["sha256"]:
        raise ContractError("closure plan does not match implementation snapshot")
    task_receipts = _verify_tasks(receipt, str(plan["sha256"]), impl)
    _verify_runs(receipt, str(plan["sha256"]), str(impl["sha256"]), task_receipts)
    _verify_states(receipt["source_and_brain"])
    _verify_superseded(receipt["superseded_receipts"])
    if not legacy:
        _verify_approval_required(receipt, receipt_path, manifest)
    for section in ("reports", "cleanup"):
        for row in receipt[section]:
            verify_file_ref(row)
    sidecar = Path(str(receipt["approval_command_sidecar"]))
    expected = f"APPROVE wave {receipt['wave']} {digest(closure.data)}\n".encode()
    if read_bytes_no_follow(sidecar) != expected:
        raise ContractError("approval command binding mismatch")
    return receipt, manifest, archive


def verify_wave4_closure_for_approval(
    receipt_path: Path,
    impl_root: Path | None,
    pinned: PinnedJson | None = None,
) -> None:
    receipt, manifest, _archive = _verified_wave_closure(receipt_path, pinned)
    if "approval_required" not in receipt:
        raise ContractError("closure approval provenance is missing")
    if receipt.get("wave") != 4:
        raise ContractError("closure approval requires wave 4")
    impl = _expect_keys("implementation", receipt["implementation"], IMPL_KEYS)
    if impl_root is not None and Path(str(impl["root"])).resolve() != impl_root.resolve():
        raise ContractError("closure implementation root mismatch")
    git_state = manifest_implementation_git_sha(manifest)
    if git_state is None:
        raise ContractError("closure implementation Git state is missing")
    task_rows = [_expect_keys("task receipt", row, RECEIPT_KEYS) for row in receipt["accepted_task_receipts"]]
    run_rows = [_expect_keys("governed run", row, RECEIPT_KEYS) for row in receipt["governed_runs"]]
    expected_todos = list(range(1, 20))
    if sorted(int(row["todo"]) for row in task_rows) != expected_todos:
        raise ContractError("closure wave 4 task receipt coverage mismatch")
    if sorted(int(row["todo"]) for row in run_rows) != expected_todos:
        raise ContractError("closure wave 4 governed run coverage mismatch")
    plan = _expect_keys("active plan", receipt["active_plan"], PLAN_KEYS)
    if plan["checked_todos"] != expected_todos:
        raise ContractError("closure wave 4 plan coverage mismatch")
    source_records: set[str] = set()
    brain_records: set[str] = set()
    qa_manifests: set[str] = set()
    for row in task_rows:
        root = Path(str(row["evidence_root"]))
        todo = _verify_row_file(row)
        verify_todo(todo.path, root, todo.value)
        if todo.value.get("implementation_git_state_sha256") != git_state:
            raise ContractError("todo receipt Git state does not match closure")
        source_records.add(canonical_bytes(todo.value.get("source_state")).decode("ascii"))
        brain_records.add(canonical_bytes(todo.value.get("brain_state")).decode("ascii"))
        qa_sha = todo.value.get("qa_manifest_sha256")
        if not isinstance(qa_sha, str):
            raise ContractError("todo receipt tooling provenance is missing")
        qa_manifests.add(qa_sha)
        verify_evidence_records(todo.value, root)
    if len(source_records) != 1 or len(brain_records) != 1 or len(qa_manifests) != 1:
        raise ContractError("closure wave 4 receipt provenance mismatch")
    if not receipt["reports"]:
        raise ContractError("closure wave 4 gate provenance is missing")


def _verify_approval_required(
    receipt: dict[str, JsonValue],
    receipt_path: Path,
    manifest: PinnedJson,
) -> None:
    value = _expect_keys("approval required", receipt["approval_required"], APPROVAL_REQUIRED_KEYS)
    draft = verify_provenance_ref(value["draft"], "brain", "reviewed-draft")
    review_seal = verify_provenance_ref(value["review_seal"], "evidence", "review-seal")
    tooling_summary = verify_provenance_ref(value["tooling_review"], "evidence", "tooling-review")
    gate_summary = verify_provenance_ref(value["independent_gate"], "evidence", "independent-gate-report")
    brain_root = draft.path.parents[2]
    evidence_root = receipt_path.parent
    draft_record = value["draft"]
    plan = _expect_keys("active plan", receipt["active_plan"], PLAN_KEYS)
    impl = _expect_keys("implementation", receipt["implementation"], IMPL_KEYS)
    review = parse_json_bytes(review_seal.data, review_seal.path)
    verify_plan_review(
        review_seal.path,
        evidence_root,
        brain_root,
        Path(str(impl["root"])),
        review,
    )
    if review.get("draft_sha256") != draft_record["hash"]:
        raise ContractError("approval draft does not match review seal")
    if review.get("plan_sha256") != plan["sha256"]:
        raise ContractError("approval review seal does not match closure plan")
    git_state = manifest_implementation_git_sha(manifest)
    if git_state is None:
        raise ContractError("approval report Git state is missing")
    bindings = _report_bindings(
        str(impl["sha256"]),
        git_state,
        str(plan["sha256"]),
        [_expect_keys("task receipt", row, RECEIPT_KEYS) for row in receipt["accepted_task_receipts"]],
        [_expect_keys("governed run", row, RECEIPT_KEYS) for row in receipt["governed_runs"]],
    )
    tooling_value = parse_json_bytes(tooling_summary.data, tooling_summary.path)
    gate_value = parse_json_bytes(gate_summary.data, gate_summary.path)
    verify_report_summary(
        tooling_summary.path,
        TOOLING_CONTRACT,
        bindings,
        tooling_value,
        tooling_summary.data,
    )
    verify_report_summary(
        gate_summary.path,
        GATE_CONTRACT,
        bindings,
        gate_value,
        gate_summary.data,
    )


def _report_bindings(
    product_sha: str,
    git_state_sha: str,
    plan_sha: str,
    task_rows: list[dict[str, JsonValue]],
    run_rows: list[dict[str, JsonValue]],
) -> ReportBindings:
    return ReportBindings(
        git_state_sha256=git_state_sha,
        governed_runs_sha256=digest(canonical_bytes(run_rows)),
        plan_sha256=plan_sha,
        product_sha256=product_sha,
        task_receipts_sha256=digest(canonical_bytes(task_rows)),
    )


def _verify_implementation(
    impl: dict[str, JsonValue],
) -> tuple[PinnedJson, PinnedFile]:
    manifest = Path(str(impl["manifest_path"]))
    archive = Path(str(impl["archive_path"]))
    pinned_manifest = pin_json(manifest)
    pinned_archive = pin_file(archive)
    if digest(pinned_manifest.data) != impl["manifest_sha256"]:
        raise ContractError("implementation manifest changed")
    if digest(pinned_archive.data) != impl["archive_sha256"]:
        raise ContractError("implementation archive changed")
    if (
        len(pinned_manifest.data) != impl["manifest_size"]
        or len(pinned_archive.data) != impl["archive_size"]
    ):
        raise ContractError("implementation artifact size changed")
    verify_implementation_snapshot(pinned_manifest, pinned_archive, str(impl["sha256"]))
    if implementation_sha(Path(str(impl["root"]))) != impl["sha256"]:
        raise ContractError("current implementation does not match closure")
    return pinned_manifest, pinned_archive


def _verify_tasks(
    receipt: dict[str, JsonValue],
    plan_sha: str,
    impl: dict[str, JsonValue],
) -> dict[int, set[str]]:
    task_rows = [_expect_keys("task receipt", row, RECEIPT_KEYS) for row in receipt["accepted_task_receipts"]]
    _unique([int(row["todo"]) for row in task_rows], "task receipt")
    return {int(row["todo"]): _run_sha_set(_verify_task(row, plan_sha, impl)) for row in task_rows}


def _verify_runs(
    receipt: dict[str, JsonValue],
    plan_sha: str,
    impl_sha: str,
    task_receipts: dict[int, set[str]],
) -> None:
    run_rows = [_expect_keys("governed run", row, RECEIPT_KEYS) for row in receipt["governed_runs"]]
    _unique([int(row["todo"]) for row in run_rows], "governed run")
    for row in run_rows:
        pinned = _verify_row_file(row)
        run = verify_run(
            pinned.path,
            Path(str(row["evidence_root"])),
            pinned.value,
        )
        if run.get("plan_sha256") != plan_sha or run.get("implementation_sha256") != impl_sha:
            raise ContractError("governed run provenance mismatch")
        if row["sha256"] not in task_receipts.get(int(row["todo"]), set()):
            raise ContractError("governed run is not bound by todo receipt")


def _verify_states(row: JsonValue) -> None:
    states = _expect_keys("source and brain", row, {"brain", "source"})
    for state in states.values():
        pair = _expect_keys("state pair", state, STATE_KEYS)
        before, before_sidecars = verify_state_ref(pair["before"])
        after, after_sidecars = verify_state_ref(pair["after"])
        if not compare_state_values(before, before_sidecars, after, after_sidecars):
            raise ContractError("source/brain state changed")


def _verify_superseded(rows: JsonValue) -> None:
    if not isinstance(rows, list):
        raise ContractError("superseded receipts must be an array")
    paths: set[str] = set()
    for row in rows:
        record = _expect_keys("superseded receipt", row, RECEIPT_KEYS)
        path = str(record["path"])
        if path in paths:
            raise ContractError("duplicate superseded receipt")
        paths.add(path)
        _verify_row_file(record)
