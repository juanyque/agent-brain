from __future__ import annotations

# noqa: SIZE_OK: closure-v2 fixtures and adversarial lifecycle cases form one contract.

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tests" / "support" / "evidence_contract.py"
BASELINE = "993247b2850ac86993c7c6dd18e6c4fd9ec6df7c"
sys.path.insert(0, str(ROOT / "tests" / "support"))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_bytes(value: JsonValue) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
    ).encode("utf-8")


def tree_sha(root: Path) -> str:
    rows: list[tuple[str, str, int]] = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.is_symlink():
            rows.append((str(path.relative_to(root)), hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mode & 0o777))
        elif path.is_dir() and not path.is_symlink():
            rows.append((str(path.relative_to(root)), "dir", path.stat().st_mode & 0o777))
    return hashlib.sha256(canonical_bytes(rows)).hexdigest()


def write_json(path: Path, value: JsonValue) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value))


def run_cli(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["python3", "-B", str(CLI), *args],
        cwd=ROOT,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        check=False,
    )


def init_git(root: Path) -> None:
    root.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=root)
    subprocess.run(["git", "config", "user.name", "test"], cwd=root)
    (root / "tracked.md").write_text("tracked\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.md"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=root, check=True)


class ClosureFixture:
    def __init__(self, raw: str) -> None:
        self.base = Path(raw)
        self.impl = self.base / "impl"
        self.evidence = self.base / "evidence"
        self.source = self.base / "source"
        self.brain = self.base / "brain"
        self.evidence.mkdir()
        init_git(self.source)
        init_git(self.brain)
        self.write_impl()
        self.capture_states()
        self.capture_implementation()
        self.run_and_seal_todo()
        self.report = self.evidence / "suite.json"
        write_json(self.report, {"all_passed": True, "schema_version": "test-suite/v1"})
        self.receipt = self.evidence / "closure.json"

    def write_impl(self) -> None:
        (self.impl / ".omo/plans").mkdir(parents=True)
        (self.impl / "model").mkdir()
        (self.impl / "tests/fixtures").mkdir(parents=True)
        (self.impl / ".omo/plans/agent-brain-operating-model.md").write_text(
            "- [x] 5 closure fixture\n- [ ] 6 future\n", encoding="utf-8"
        )
        write_json(
            self.impl / "model/OPERATING-MODEL.json",
            {
                "baseline": {"plan_sha256": "0" * 64},
                "schema_version": "agent-brain-operating-model/v1",
            },
        )
        write_json(
            self.impl / "tests/fixtures/operating-model-qa-commands.json",
            {
                "schema_version": "agent-brain-qa-commands/v1",
                "todos": [
                    {
                        "steps": [
                            {
                                "command": "python3 -B -c 'print(1)'",
                                "mode": "argv",
                                "step": 1,
                            }
                        ],
                        "todo": 5,
                    }
                ],
            },
        )

    def capture_states(self) -> None:
        for kind, root in (("source", self.source), ("brain", self.brain)):
            for phase in ("before", "after"):
                result = run_cli(
                    "capture-state",
                    "--kind",
                    kind,
                    "--root",
                    str(root),
                    "--output",
                    str(self.evidence / f"{kind}-{phase}.json"),
                    "--sidecar-dir",
                    str(self.evidence / f"{kind}-{phase}-sidecars"),
                )
                self.assert_success(result)

    def capture_implementation(self) -> None:
        result = run_cli(
            "capture-worktree",
            "--root",
            str(self.impl),
            "--archive",
            str(self.evidence / "implementation.tar"),
            "--manifest",
            str(self.evidence / "implementation-manifest.json"),
        )
        self.assert_success(result)

    def run_and_seal_todo(self) -> None:
        result = run_cli(
            "run-todo",
            "--todo",
            "5",
            "--step",
            "1",
            "--cwd",
            str(self.impl),
            "--evidence-root",
            str(self.evidence),
            "--",
            "python3",
            "-B",
            "-c",
            "print(1)",
        )
        self.assert_success(result)
        (self.evidence / "task.log").write_text("task\n", encoding="utf-8")
        result = run_cli(
            "seal-todo",
            "--todo",
            "5",
            "--plan",
            str(self.impl / ".omo/plans/agent-brain-operating-model.md"),
            "--baseline-commit",
            BASELINE,
            "--impl-root",
            str(self.impl),
            "--source-baseline",
            str(self.evidence / "source-before.json"),
            "--brain-baseline",
            str(self.evidence / "brain-before.json"),
            "--runs",
            str(self.evidence / "task-5-runs"),
            "--task-log",
            str(self.evidence / "task.log"),
            "--implementation-manifest",
            str(self.evidence / "implementation-manifest.json"),
            "--implementation-archive",
            str(self.evidence / "implementation.tar"),
            "--output",
            str(self.evidence / "task-5-receipt.json"),
        )
        self.assert_success(result)

    def create_closure(self) -> subprocess.CompletedProcess[bytes]:
        return run_cli(
            "create-closure-v2",
            "--wave",
            "3",
            "--plan",
            str(self.impl / ".omo/plans/agent-brain-operating-model.md"),
            "--impl-root",
            str(self.impl),
            "--implementation-manifest",
            str(self.evidence / "implementation-manifest.json"),
            "--implementation-archive",
            str(self.evidence / "implementation.tar"),
            "--task-receipt", "5", str(self.evidence / "task-5-receipt.json"), str(self.evidence),
            "--governed-run", "5", str(self.evidence / "task-5-runs/1.json"), str(self.evidence),
            "--source-before", str(self.evidence / "source-before.json"), str(self.evidence / "source-before-sidecars"),
            "--source-after", str(self.evidence / "source-after.json"), str(self.evidence / "source-after-sidecars"),
            "--brain-before", str(self.evidence / "brain-before.json"), str(self.evidence / "brain-before-sidecars"),
            "--brain-after", str(self.evidence / "brain-after.json"), str(self.evidence / "brain-after-sidecars"),
            "--report",
            str(self.report),
            "--output",
            str(self.receipt),
        )

    @staticmethod
    def assert_success(result: subprocess.CompletedProcess[bytes]) -> None:
        if result.returncode != 0:
            raise AssertionError(result.stderr.decode("utf-8", "replace"))


class WaveClosureContractTests(unittest.TestCase):
    def test_approval_creation_consumes_one_pinned_receipt(self) -> None:
        import evidence_closure_records
        import evidence_seals

        with tempfile.TemporaryDirectory() as raw:
            # Given: a receipt replaced immediately after its first no-follow read.
            root = Path(raw)
            receipt = root / "receipt.json"
            message = root / "approval.txt"
            output = root / "approval.json"
            original = {"schema_version": "original-receipt/v1"}
            replacement = {
                "padding": "replacement-is-a-different-size",
                "schema_version": "replacement-receipt/v1",
            }
            original_data = canonical_bytes(original)
            write_json(receipt, original)
            message.write_bytes(
                f"APPROVE todo 5 {hashlib.sha256(original_data).hexdigest()}\n".encode()
            )
            actual_read = evidence_closure_records.read_bytes_no_follow
            replaced = False

            def replace_after_first_read(path: Path) -> bytes:
                nonlocal replaced
                data = actual_read(path)
                if path == receipt and not replaced:
                    replaced = True
                    write_json(receipt, replacement)
                return data

            # When: approval creation continues after the pathname replacement.
            with (
                patch(
                    "evidence_closure_records.read_bytes_no_follow",
                    side_effect=replace_after_first_read,
                ),
                patch(
                    "evidence_seals.read_bytes_no_follow",
                    side_effect=replace_after_first_read,
                ),
            ):
                evidence_seals.approve("todo", "5", receipt, message, output)

            # Then: every receipt field derives from the same original bytes.
            approval = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(replaced)
            self.assertEqual(approval["receipt_schema"], original["schema_version"])
            self.assertEqual(approval["receipt_sha256"], hashlib.sha256(original_data).hexdigest())
            self.assertEqual(approval["receipt_size"], len(original_data))

    def test_implementation_manifest_verification_consumes_one_pinned_read(self) -> None:
        import evidence_closure_records
        import evidence_implementation
        import evidence_json

        with tempfile.TemporaryDirectory() as raw:
            # Given: a valid manifest replaced immediately after its first no-follow read.
            fixture = ClosureFixture(raw)
            manifest = fixture.evidence / "implementation-manifest.json"
            archive = fixture.evidence / "implementation.tar"
            expected_sha = evidence_implementation.manifest_implementation_sha(manifest)
            replacement = {"schema_version": "replacement-manifest/v1"}
            actual_read = evidence_json.read_bytes_no_follow
            replaced = False

            def replace_after_first_read(path: Path) -> bytes:
                nonlocal replaced
                data = actual_read(path)
                if path == manifest and not replaced:
                    replaced = True
                    write_json(manifest, replacement)
                return data

            # When: snapshot verification continues after the pathname replacement.
            with (
                patch(
                    "evidence_json.read_bytes_no_follow",
                    side_effect=replace_after_first_read,
                ),
                patch(
                    "evidence_closure_records.read_bytes_no_follow",
                    side_effect=replace_after_first_read,
                ),
            ):
                evidence_implementation.verify_implementation_snapshot(
                    manifest,
                    archive,
                    expected_sha,
                )

            # Then: all manifest consumers use the original verified bytes.
            self.assertTrue(replaced)
            self.assertEqual(json.loads(manifest.read_text(encoding="utf-8")), replacement)

    def test_closure_implementation_archive_verification_consumes_one_pinned_read(self) -> None:
        import evidence_closure
        import evidence_closure_records

        with tempfile.TemporaryDirectory() as raw:
            # Given: a valid archive replaced immediately after its first no-follow read.
            fixture = ClosureFixture(raw)
            manifest = fixture.evidence / "implementation-manifest.json"
            archive = fixture.evidence / "implementation.tar"
            manifest_data = manifest.read_bytes()
            archive_data = archive.read_bytes()
            implementation = {
                "archive_path": str(archive),
                "archive_sha256": hashlib.sha256(archive_data).hexdigest(),
                "archive_size": len(archive_data),
                "manifest_path": str(manifest),
                "manifest_sha256": hashlib.sha256(manifest_data).hexdigest(),
                "manifest_size": len(manifest_data),
                "root": str(fixture.impl),
                "sha256": evidence_closure.implementation_sha(fixture.impl),
            }
            actual_read = evidence_closure_records.read_bytes_no_follow
            replaced = False

            def replace_after_first_read(path: Path) -> bytes:
                nonlocal replaced
                data = actual_read(path)
                if path == archive and not replaced:
                    replaced = True
                    archive.write_bytes(b"replacement is not a tar archive\n")
                return data

            # When: closure verification continues after the archive pathname replacement.
            with (
                patch(
                    "evidence_closure.read_bytes_no_follow",
                    side_effect=replace_after_first_read,
                ),
                patch(
                    "evidence_closure_records.read_bytes_no_follow",
                    side_effect=replace_after_first_read,
                ),
            ):
                evidence_closure._verify_implementation(implementation)

            # Then: tar verification consumes the exact original archive bytes.
            self.assertTrue(replaced)
            self.assertEqual(archive.read_bytes(), b"replacement is not a tar archive\n")

    def test_state_sidecar_hash_rejects_symlink_root_and_descendants(self) -> None:
        from evidence_closure_records import directory_sha, state_ref, verify_state_ref
        from evidence_json import ContractError

        with tempfile.TemporaryDirectory() as raw:
            # Given: an empty sidecar root reached through a symlink.
            root = Path(raw)
            state = root / "state.json"
            real_sidecars = root / "real-sidecars"
            linked_sidecars = root / "linked-sidecars"
            real_sidecars.mkdir()
            linked_sidecars.symlink_to(real_sidecars, target_is_directory=True)
            write_json(
                state,
                {"schema_version": "agent-brain-source-state/v1", "sidecars": []},
            )
            record = state_ref(state, real_sidecars)
            record["sidecar_dir"] = str(linked_sidecars)

            # When/Then: verification rejects the root symlink even with no descendants.
            with self.assertRaises(ContractError):
                verify_state_ref(record)

            # Given: a real sidecar root containing a symlinked descendant.
            descendant_root = root / "descendant-sidecars"
            descendant_root.mkdir()
            (descendant_root / "linked.bin").symlink_to(state)

            # When/Then: hashing rejects the descendant instead of recording/following it.
            with self.assertRaises(ContractError):
                directory_sha(descendant_root)

    def test_closure_v2_common_file_reference_rejects_symlinks(self) -> None:
        from evidence_closure_records import file_ref, verify_file_ref
        from evidence_json import ContractError

        with tempfile.TemporaryDirectory() as raw:
            # Given: closure child records whose task and run paths are symlinks.
            root = Path(raw)
            for name in ("task-receipt", "governed-run"):
                with self.subTest(name=name):
                    target = root / f"{name}-target.json"
                    link = root / f"{name}.json"
                    write_json(target, {"schema_version": f"{name}/v1"})
                    record = file_ref(target)
                    link.symlink_to(target)
                    record["path"] = str(link)

                    # When/Then: the common closure reference boundary rejects either symlink.
                    with self.assertRaises(ContractError):
                        verify_file_ref(record)

    def test_closure_v2_rejects_symlinked_task_receipt_reference(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            # Given: a valid closure whose task receipt row names a symlink.
            fixture = ClosureFixture(raw)
            fixture.assert_success(fixture.create_closure())
            receipt = json.loads(fixture.receipt.read_text(encoding="utf-8"))
            target = fixture.evidence / "task-5-receipt.json"
            link = fixture.evidence / "task-5-receipt-link.json"
            link.symlink_to(target)
            receipt["accepted_task_receipts"][0]["path"] = str(link)
            write_json(fixture.receipt, receipt)
            (fixture.evidence / "approval-command.txt").write_text(
                f"APPROVE wave 3 {digest(fixture.receipt)}\n",
                encoding="utf-8",
            )

            # When: the public verifier evaluates the symlinked child reference.
            verified = run_cli("verify-closure-v2", "--receipt", str(fixture.receipt))

            # Then: no-follow enforcement rejects the closure.
            self.assertEqual(verified.returncode, 2, verified.stderr.decode("utf-8", "replace"))

    def test_closure_v2_rejects_symlinked_governed_run_reference(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            # Given: a valid closure whose governed run row names a symlink.
            fixture = ClosureFixture(raw)
            fixture.assert_success(fixture.create_closure())
            receipt = json.loads(fixture.receipt.read_text(encoding="utf-8"))
            target = fixture.evidence / "task-5-runs" / "1.json"
            link = fixture.evidence / "governed-run-link.json"
            link.symlink_to(target)
            receipt["governed_runs"][0]["path"] = str(link)
            write_json(fixture.receipt, receipt)
            (fixture.evidence / "approval-command.txt").write_text(
                f"APPROVE wave 3 {digest(fixture.receipt)}\n",
                encoding="utf-8",
            )

            # When: the public verifier evaluates the symlinked child reference.
            verified = run_cli("verify-closure-v2", "--receipt", str(fixture.receipt))

            # Then: no-follow enforcement rejects the closure.
            self.assertEqual(verified.returncode, 2, verified.stderr.decode("utf-8", "replace"))

    def test_closure_v2_task_and_run_validation_consume_pinned_bytes(self) -> None:
        import evidence_closure
        from evidence_closure_records import verify_file_ref

        with tempfile.TemporaryDirectory() as raw:
            # Given: valid task/run rows and replacement JSON written immediately after reference verification.
            fixture = ClosureFixture(raw)
            fixture.assert_success(fixture.create_closure())
            closure = json.loads(fixture.receipt.read_text(encoding="utf-8"))
            task_row = closure["accepted_task_receipts"][0]
            run_row = closure["governed_runs"][0]
            implementation = closure["implementation"]
            task_path = Path(task_row["path"])
            run_path = Path(run_row["path"])
            task_replacement = {"schema_version": "replacement-task/v1", "todo": 999}
            run_replacement = {"schema_version": "replacement-run/v1", "todo": 999}

            def swap_task(record: JsonValue):
                verified = verify_file_ref(record)
                write_json(task_path, task_replacement)
                return verified

            # When: task verification continues after the pathname is replaced.
            with patch("evidence_closure_records.verify_file_ref", side_effect=swap_task):
                task = evidence_closure._verify_task(task_row, closure["active_plan"]["sha256"], implementation)

            # Then: downstream validation and parsing use the exact bytes that matched the row.
            self.assertEqual(task["todo"], 5)

            def swap_run(record: JsonValue):
                verified = verify_file_ref(record)
                write_json(run_path, run_replacement)
                return verified

            # When: run verification continues after the pathname is replaced.
            with patch("evidence_closure_records.verify_file_ref", side_effect=swap_run):
                evidence_closure._verify_runs(
                    closure,
                    closure["active_plan"]["sha256"],
                    implementation["sha256"],
                    {5: {run_row["sha256"]}},
                )

            # Then: the governed run also consumes the exact validated bytes.
            self.assertEqual(json.loads(run_path.read_text(encoding="utf-8")), run_replacement)

    def test_closure_v2_sidecar_collision_rolls_back_create_only_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            # Given: a valid closure request whose approval sidecar destination already exists.
            fixture = ClosureFixture(raw)
            sidecar = fixture.evidence / "approval-command.txt"
            sidecar.write_text("collision\n", encoding="utf-8")

            # When: closure creation cannot create the approval sidecar.
            created = fixture.create_closure()

            # Then: failure does not strand the create-only closure receipt.
            self.assertEqual(created.returncode, 2, created.stderr.decode("utf-8", "replace"))
            self.assertFalse(fixture.receipt.exists())
            self.assertEqual(sidecar.read_text(encoding="utf-8"), "collision\n")

    def test_verify_wave_rejects_receipt_swapped_after_recursive_validation(self) -> None:
        from tests.test_ledger_product_ownership import ProductFixture

        from evidence_json import ContractError
        from evidence_wave import verify_ledger_checkpoint, verify_wave

        with tempfile.TemporaryDirectory() as raw:
            # Given: an approved closure-v2 receipt and a deterministic swap at the ledger checkpoint.
            fixture = ProductFixture(raw)
            fixture.create_wave4_closure_v2()
            approved = fixture.approve_wave4_closure_v2()
            self.assertEqual(approved.returncode, 0, approved.stderr.decode("utf-8", "replace"))
            receipt = fixture.evidence / "wave-4-closure-v2.json"
            forged = json.loads(receipt.read_text(encoding="utf-8"))
            forged["source_and_brain"] = {
                "brain": {"forged": True},
                "source": {"forged": True},
            }

            def swap_receipt_at_checkpoint(
                checkpoint: Path,
                evidence_root: Path,
                expected_lifecycle: str | None = None,
                value: dict[str, JsonValue] | None = None,
            ) -> None:
                verify_ledger_checkpoint(
                    checkpoint,
                    evidence_root,
                    expected_lifecycle,
                    value=value,
                )
                write_json(receipt, forged)

            # When: wave verification reaches the post-receipt ledger checkpoint.
            with patch(
                "evidence_wave.verify_ledger_checkpoint",
                side_effect=swap_receipt_at_checkpoint,
            ):
                # Then: forged lifecycle state is rejected instead of returned to the CLI.
                with self.assertRaisesRegex(ContractError, "wave approval binding mismatch"):
                    verify_wave(4, fixture.evidence, fixture.impl)

    def test_closure_v2_public_verify_accepts_full_lifecycle_requirements(self) -> None:
        from tests.test_ledger_product_ownership import ProductFixture

        with tempfile.TemporaryDirectory() as raw:
            fixture = ProductFixture(raw)
            plan, draft, seal = fixture.create_wave4_closure_v2()
            approved = fixture.approve_wave4_closure_v2()
            self.assertEqual(approved.returncode, 0, approved.stderr.decode("utf-8", "replace"))
            frozen = run_cli(
                "freeze",
                "--plan",
                str(plan),
                "--draft",
                str(draft),
                "--review-seal",
                str(seal),
                "--impl-root",
                str(fixture.impl),
                "--evidence-root",
                str(fixture.evidence),
                "--prior-ledger-checkpoint",
                str(fixture.evidence / "wave-4-approval.ledger-checkpoint.json"),
                "--output",
                str(fixture.evidence / "freeze.json"),
            )
            self.assertEqual(frozen.returncode, 0, frozen.stderr.decode("utf-8", "replace"))

            verified = run_cli(
                "verify",
                "--freeze",
                str(fixture.evidence / "freeze.json"),
                "--impl-root",
                str(fixture.impl),
                "--evidence-root",
                str(fixture.evidence),
                "--require-source-preflight",
                "--require-brain-equality",
                "--require-wave-approvals",
            )

            self.assertFalse((fixture.evidence / "wave-4-receipt.json").exists())
            self.assertEqual(verified.returncode, 0, verified.stderr.decode("utf-8", "replace"))

    def test_closure_v2_rejects_copied_receipt_mutations(self) -> None:
        mutations: dict[str, Callable[[dict[str, JsonValue], ClosureFixture], None]] = {
            "task-receipt-hash": lambda r, _f: r["accepted_task_receipts"][0].__setitem__("sha256", "0" * 64),
            "current-plan-hash": lambda r, _f: r["active_plan"].__setitem__("sha256", "0" * 64),
            "implementation-manifest-field": lambda r, _f: r["implementation"].__setitem__("manifest_sha256", "0" * 64),
            "governed-run-provenance": self.mutate_governed_run,
        }
        for name, mutation in mutations.items():
            with self.subTest(name=name):
                with tempfile.TemporaryDirectory() as raw:
                    fixture = ClosureFixture(raw)
                    fixture.assert_success(fixture.create_closure())
                    receipt = json.loads(fixture.receipt.read_text())
                    mutation(receipt, fixture)
                    mutated = fixture.evidence / f"{name}.json"
                    write_json(mutated, receipt)

                    verified = run_cli("verify-closure-v2", "--receipt", str(mutated))

                    self.assertEqual(verified.returncode, 2, verified.stderr.decode())

    def test_closure_v2_rejects_old_todo_receipt_without_immutable_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = ClosureFixture(raw)
            fixture.assert_success(fixture.create_closure())
            old_receipt = json.loads((fixture.evidence / "task-5-receipt.json").read_text())
            old_receipt.pop("implementation_manifest")
            old_receipt.pop("implementation_archive")
            old_path = fixture.evidence / "old-task-receipt.json"
            write_json(old_path, old_receipt)
            receipt = json.loads(fixture.receipt.read_text())
            receipt["accepted_task_receipts"][0]["path"] = str(old_path)
            receipt["accepted_task_receipts"][0]["sha256"] = digest(old_path)
            mutated = fixture.evidence / "closure-old-receipt.json"
            write_json(mutated, receipt)

            verified = run_cli("verify-closure-v2", "--receipt", str(mutated))

            self.assertEqual(verified.returncode, 2, verified.stderr.decode())

    def test_closure_v2_verify_does_not_create_pycache_or_change_product_tree(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = ClosureFixture(raw)
            fixture.assert_success(fixture.create_closure())
            before = tree_sha(fixture.impl)

            verified = run_cli("verify-closure-v2", "--receipt", str(fixture.receipt))
            after = tree_sha(fixture.impl)
            receipt = json.loads(fixture.receipt.read_text())

            self.assertEqual(verified.returncode, 0, verified.stderr.decode())
            self.assertEqual(after, before)
            self.assertEqual(list(fixture.impl.rglob("__pycache__")), [])
            self.assertEqual(receipt["schema_version"], "agent-brain-wave-closure-v2")
            self.assertEqual(receipt["active_plan"]["checked_todos"], [5])

    def mutate_governed_run(self, receipt: dict[str, JsonValue], fixture: ClosureFixture) -> None:
        run = json.loads((fixture.evidence / "task-5-runs/1.json").read_text())
        run["implementation_sha256"] = "0" * 64
        mutated = fixture.evidence / "mutated-run.json"
        write_json(mutated, run)
        receipt["governed_runs"][0]["path"] = str(mutated)
        receipt["governed_runs"][0]["sha256"] = digest(mutated)
