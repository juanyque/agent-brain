from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from evidence_closure_records import PinnedFile, PinnedJson, pin_json
from evidence_json import (
    ContractError,
    JsonValue,
    digest,
    file_record,
    load_json,
    parse_json_bytes,
    read_bytes_no_follow,
    read_file_record,
)
from evidence_invocations import expected_todo_proof, expected_todo_proof_from_bindings
from evidence_implementation import (
    active_plan_sha_from_snapshot,
    manifest_implementation_git_sha,
    implementation_snapshot,
    verify_implementation_snapshot,
)
from evidence_review import verify_plan_review

_VERIFIED_IMPLEMENTATIONS: set[tuple[str, str, str]] = set()


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _verify_record(record: JsonValue, roots: dict[str, Path]) -> Path:
    path, _data = read_file_record(record, roots)
    return path


def verify_run(
    path: Path,
    evidence_root: Path,
    value: dict[str, JsonValue] | None = None,
) -> dict[str, JsonValue]:
    run = load_json(path) if value is None else value
    if run.get("schema_version") != "agent-brain-run/v1":
        raise ContractError("invalid run schema")
    roots = {"evidence": evidence_root}
    _stdout, stdout_data = read_file_record(run.get("stdout"), roots)
    _stderr, stderr_data = read_file_record(run.get("stderr"), roots)
    if "stdout_sha256" in run and run.get("stdout_sha256") != digest(stdout_data):
        raise ContractError("stdout hash binding mismatch")
    if "stderr_sha256" in run and run.get("stderr_sha256") != digest(stderr_data):
        raise ContractError("stderr hash binding mismatch")
    if "status_sha256" in run and run.get("status_sha256") != digest(f"{run.get('exit_status')}\n".encode("ascii")):
        raise ContractError("status hash binding mismatch")
    if run.get("exit_status") != 0:
        raise ContractError(f"run failed: {path}")
    return run


def _binding_values(run: dict[str, JsonValue]) -> dict[str, str]:
    bindings = run.get("environment_bindings")
    if not isinstance(bindings, dict):
        raise ContractError("todo run wrapper proof mismatch")
    values: dict[str, str] = {}
    for name, value in bindings.items():
        if not isinstance(value, str):
            raise ContractError("todo run wrapper proof mismatch")
        values[name] = value
    return values


def _binding_records(run: dict[str, JsonValue]) -> list[dict[str, JsonValue]]:
    records = run.get("environment_binding_records")
    if not isinstance(records, list):
        raise ContractError("todo run wrapper proof mismatch")
    result: list[dict[str, JsonValue]] = []
    for item in records:
        if not isinstance(item, dict):
            raise ContractError("todo run wrapper proof mismatch")
        result.append(item)
    return result


def _reviewed_plan_run(run: dict[str, JsonValue]) -> bool:
    if "environment_binding_records" not in run:
        return False
    return any(
        item.get("name") == "PLAN"
        and item.get("root") == "brain"
        and item.get("role") == "reviewed-plan"
        for item in _binding_records(run)
    )


def _seal_record(
    seal: dict[str, JsonValue],
    role: str,
    brain_root: Path,
) -> PinnedFile:
    record = seal.get(role)
    if not isinstance(record, dict) or record.get("root") != "brain":
        raise ContractError("review seal binding mismatch")
    try:
        path, data = read_file_record(record, {"brain": brain_root})
        return PinnedFile(path, data)
    except (OSError, ValueError) as error:
        raise ContractError("review seal binding mismatch") from error


def _verify_reviewed_plan_seal(run: dict[str, JsonValue], evidence_root: Path) -> None:
    values = _binding_values(run)
    try:
        brain = Path(values["BRAIN_ROOT"]).resolve(strict=True)
        plan = Path(values["PLAN"]).resolve(strict=True)
        draft = Path(values["DRAFT"]).resolve(strict=True)
        review_seal = Path(values["REVIEW_SEAL"]).resolve(strict=True)
    except (KeyError, OSError) as error:
        raise ContractError("review seal binding mismatch") from error
    review_data = read_bytes_no_follow(review_seal)
    seal = parse_json_bytes(review_data, review_seal)
    verify_plan_review(review_seal, evidence_root, brain, value=seal)
    plan_record = _seal_record(seal, "plan", brain)
    draft_record = _seal_record(seal, "draft", brain)
    if (
        plan_record.path != plan
        or draft_record.path != draft
        or seal.get("plan_sha256") != digest(plan_record.data)
        or seal.get("draft_sha256") != digest(draft_record.data)
    ):
        raise ContractError("review seal binding mismatch")


def _legacy_evidence_only_run(run: dict[str, JsonValue], evidence_root: Path) -> bool:
    return (
        "environment_binding_records" not in run
        and run.get("environment_bindings") == {"EVIDENCE_ROOT": str(evidence_root.resolve())}
    )


def _verify_todo_proof(
    run: dict[str, JsonValue],
    todo: int,
    step: int,
    impl_root: Path,
    evidence_root: Path,
) -> None:
    if _legacy_evidence_only_run(run, evidence_root):
        expected = expected_todo_proof(todo, step, impl_root, evidence_root).record_fields()
        expected.pop("environment_binding_records", None)
        if expected.get("environment_bindings") == {}:
            expected["environment_bindings"] = run.get("environment_bindings")
            expected["environment_binding_sha256"] = run.get("environment_binding_sha256")
    else:
        expected = expected_todo_proof_from_bindings(
            todo,
            step,
            impl_root,
            evidence_root,
            _binding_values(run),
        ).record_fields()
    for key, value in expected.items():
        if run.get(key) != value:
            raise ContractError("todo run wrapper proof mismatch")
    if _reviewed_plan_run(run):
        _verify_reviewed_plan_seal(run, evidence_root)


def _receipt_implementation_paths(output: Path) -> tuple[Path, Path]:
    return output.with_suffix(".implementation-manifest.json"), output.with_suffix(".implementation.tar")


def _verify_run_state(
    run: dict[str, JsonValue],
    plan_sha256: str,
    implementation_sha256: str,
    git_state_sha256: str | None = None,
) -> None:
    if run.get("plan_sha256") != plan_sha256:
        raise ContractError("todo run plan does not match receipt")
    if run.get("implementation_sha256") != implementation_sha256:
        raise ContractError("todo run implementation does not match receipt")
    if "implementation_product_sha256" in run and run.get("implementation_product_sha256") != implementation_sha256:
        raise ContractError("todo run product implementation does not match receipt")
    if git_state_sha256 is not None and run.get("implementation_git_state_sha256") != git_state_sha256:
        raise ContractError("todo run Git state does not match receipt")


def seal_todo(
    todo: int,
    plan: Path,
    baseline_commit: str,
    impl_root: Path,
    source_baseline: Path,
    brain_baseline: Path,
    runs: Path,
    task_log: Path,
    output: Path,
    implementation_manifest: Path | None = None,
    implementation_archive: Path | None = None,
) -> None:
    from evidence_json import create_json

    impl_root = impl_root.resolve()
    qa = pin_json(impl_root / "tests/fixtures/operating-model-qa-commands.json")
    todo_spec = next(item for item in qa.value["todos"] if item["todo"] == todo)
    run_paths = sorted(runs.glob("*.json"), key=lambda path: int(path.stem))
    if len(run_paths) != len(todo_spec["steps"]):
        raise ContractError("todo run count differs from QA manifest")
    evidence_root = output.parent.resolve()
    if (implementation_manifest is None) != (implementation_archive is None):
        raise ContractError("implementation manifest and archive must be provided together")
    if implementation_manifest is None or implementation_archive is None:
        implementation_manifest, implementation_archive = _receipt_implementation_paths(output)
    snapshot = implementation_snapshot(impl_root, implementation_manifest, implementation_archive)
    plan_sha256 = digest(read_bytes_no_follow(plan))
    run_records: list[dict[str, JsonValue]] = []
    for index, path in enumerate(run_paths, start=1):
        pinned_run = pin_json(path)
        run = verify_run(path, evidence_root, pinned_run.value)
        if run.get("step") != index or run.get("identity") != f"task-{todo}":
            raise ContractError("todo run ordering mismatch")
        _verify_todo_proof(run, todo, index, impl_root, evidence_root)
        _verify_run_state(run, plan_sha256, snapshot.sha256, snapshot.git_state_sha256)
        run_records.append(
            file_record(
                "evidence",
                evidence_root,
                path.resolve(),
                data=pinned_run.data,
            )
        )
    create_json(
        output,
        {
            "baseline_commit": baseline_commit,
            "brain_state": file_record("evidence", evidence_root, brain_baseline.resolve()),
            "completed_at": _now(),
            "implementation_archive": file_record(
                "evidence",
                evidence_root,
                implementation_archive.resolve(),
                data=snapshot.archive.data,
            ),
            "implementation_git_state_sha256": snapshot.git_state_sha256,
            "implementation_manifest": file_record(
                "evidence",
                evidence_root,
                implementation_manifest.resolve(),
                data=snapshot.manifest.data,
            ),
            "implementation_sha256": snapshot.sha256,
            "plan_sha256": plan_sha256,
            "qa_manifest_sha256": digest(qa.data),
            "runs": run_records,
            "schema_version": "agent-brain-todo-receipt/v1",
            "source_state": file_record("evidence", evidence_root, source_baseline.resolve()),
            "task_log": file_record("evidence", evidence_root, task_log.resolve()),
            "todo": todo,
        },
    )


def verify_todo(
    receipt: Path,
    evidence_root: Path,
    value: dict[str, JsonValue] | None = None,
) -> None:
    evidence_root = evidence_root.resolve()
    value = load_json(receipt) if value is None else value
    if value.get("schema_version") != "agent-brain-todo-receipt/v1":
        raise ContractError("invalid todo receipt")
    roots = {"evidence": evidence_root}
    for role in ("source_state", "brain_state", "task_log"):
        _verify_record(value.get(role), roots)
    plan_sha256 = value.get("plan_sha256")
    implementation_sha256 = value.get("implementation_sha256")
    if not isinstance(plan_sha256, str) or not isinstance(implementation_sha256, str):
        raise ContractError("todo receipt state hashes are missing")
    manifest_path, manifest_data = read_file_record(value.get("implementation_manifest"), roots)
    archive_path, archive_data = read_file_record(value.get("implementation_archive"), roots)
    manifest = PinnedJson(
        manifest_path,
        manifest_data,
        parse_json_bytes(manifest_data, manifest_path),
    )
    archive = PinnedFile(archive_path, archive_data)
    cache_key = (digest(manifest_data), digest(archive_data), implementation_sha256)
    if cache_key not in _VERIFIED_IMPLEMENTATIONS:
        verify_implementation_snapshot(manifest, archive, implementation_sha256)
        _VERIFIED_IMPLEMENTATIONS.add(cache_key)
    git_state_sha256 = manifest_implementation_git_sha(manifest)
    if git_state_sha256 is not None and value.get("implementation_git_state_sha256") != git_state_sha256:
        raise ContractError("todo receipt Git state does not match implementation snapshot")
    if active_plan_sha_from_snapshot(manifest, archive) != plan_sha256:
        raise ContractError("todo receipt active plan does not match implementation snapshot")
    runs = value.get("runs")
    if not isinstance(runs, list):
        raise ContractError("todo receipt runs must be an array")
    todo = value.get("todo")
    if not isinstance(todo, int):
        raise ContractError("todo receipt todo is missing")
    for index, record in enumerate(runs, start=1):
        run_path, run_data = read_file_record(record, roots)
        run = verify_run(
            run_path,
            evidence_root,
            parse_json_bytes(run_data, run_path),
        )
        cwd = run.get("cwd")
        if not isinstance(cwd, str):
            raise ContractError("todo run cwd is missing")
        _verify_todo_proof(run, todo, index, Path(cwd), evidence_root)
        _verify_run_state(run, plan_sha256, implementation_sha256, git_state_sha256)
