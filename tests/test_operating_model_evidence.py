from __future__ import annotations

import base64
import hashlib
import importlib
import io
import json
import os
import re
import shutil
import shlex
import subprocess
import sys
import tarfile
import types
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from tests.support.contract_test_cases import (
    EvidenceAdversarialCases,
    ModelNegativeCases,
    TreeInterruptionCases,
)
from tests.support import evidence_json as evidence_json_module
from tests.support.evidence_json import ContractError, JsonValue, canonical_bytes
from tests.support.evidence_json import create_bytes, create_bytes_pair, create_json
from tests.support.evidence_json import file_record

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tests" / "support" / "evidence_contract.py"
RUNNER = ROOT / "tests" / "support" / "run_baseline_tests.py"
MODEL = ROOT / "model" / "OPERATING-MODEL.json"
QA = ROOT / "tests" / "fixtures" / "operating-model-qa-commands.json"
IDS = ROOT / "tests" / "fixtures" / "baseline-test-ids.txt"
FINAL_LANE_COMMANDS = (
    ROOT / "tests" / "fixtures" / "operating-model-final-lane-commands.json"
)
MODEL_BASELINE, TEST_BASELINE = "993247b2850ac86993c7c6dd18e6c4fd9ec6df7c", "2e420205d3dbc5b91e5188b90950043e44a4a054"
ROOT_AGENTS = ROOT / "AGENTS.md"


def canonical(path: Path) -> dict[str, JsonValue]:
    raw = path.read_bytes()
    parsed = json.loads(raw)
    expected = json.dumps(
        parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode() + b"\n"
    if raw != expected:
        raise AssertionError(f"{path} is not canonical JSON")
    return parsed


def run_cli(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, "-B", str(CLI), *args],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )


def init_git(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=root)
    subprocess.run(["git", "config", "user.name", "test"], cwd=root)
    (root / "tracked").write_bytes(b"original\n")
    subprocess.run(["git", "add", "tracked"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=root, check=True)


def verified_macos_tmp_alias() -> bool:
    if sys.platform != "darwin":
        return False
    path = Path("/tmp")
    try:
        return (
            path.is_symlink()
            and os.readlink(path) == "private/tmp"
            and path.resolve(strict=True) == Path("/private/tmp")
        )
    except OSError:
        return False


def heading_ranges(path: Path) -> dict[str, tuple[int, int]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    headings: list[tuple[str, int]] = [
        (line.removeprefix("## "), index)
        for index, line in enumerate(lines, start=1)
        if line.startswith("## ")
    ]
    ranges: dict[str, tuple[int, int]] = {}
    for index, (heading, start) in enumerate(headings):
        end = headings[index + 1][1] - 1 if index + 1 < len(headings) else len(lines)
        ranges[heading] = (start, end)
    return ranges


class OperatingModelContractTests(ModelNegativeCases, unittest.TestCase):
    def test_governed_inventory_matches_model_markdown(self) -> None:
        model = canonical(MODEL)
        governed = set(model["governed_inventory"])
        discovered = {
            str(path.relative_to(ROOT))
            for parent in (ROOT, ROOT / "model", ROOT / "skills" / "brain")
            for path in parent.rglob("*.md")
            if parent != ROOT or path.name == "AGENTS.md"
        }
        self.assertEqual(governed, discovered)

    def test_future_routes_are_exact_disjoint_and_fully_named(self) -> None:
        routes = canonical(MODEL)["future_routes"]
        self.assertEqual(
            {route["route_id"] for route in routes},
            {
                "skill.session-routing",
                "skill.documentation",
                "skill.tool-catalog",
                "skill.constraints",
            },
        )
        self.assertEqual(len({route["scenario_id"] for route in routes}), 4)
        temporary = {item for route in routes for item in route["temporary_payloads"]}
        final = {item for route in routes for item in route["final_payloads"]}
        self.assertTrue(temporary.isdisjoint(final))

    def test_dependency_and_qa_manifests_cover_all_todos(self) -> None:
        model = canonical(MODEL)
        qa = canonical(QA)
        self.assertEqual([row["todo"] for row in model["dependency_graph"]], list(range(1, 20)))
        self.assertEqual([row["todo"] for row in qa["todos"]], list(range(1, 20)))
        for todo in qa["todos"]:
            self.assertEqual(
                [step["step"] for step in todo["steps"]],
                list(range(1, len(todo["steps"]) + 1)),
            )
            self.assertTrue(all(step["mode"] in {"argv", "shell"} for step in todo["steps"]))

    def test_duplicate_json_keys_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "bad.json"
            path.write_bytes(b'{"a":1,"a":2}\n')
            result = run_cli("verify-json", "--input", str(path))
        self.assertEqual(result.returncode, 2)


class TreeManifestTests(TreeInterruptionCases, unittest.TestCase):
    @unittest.skipUnless(verified_macos_tmp_alias(), "requires verified macOS /tmp alias")
    def test_capture_worktree_accepts_verified_macos_tmp_alias(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as raw:
            root = Path(raw)
            tree = root / "tree"
            tree.mkdir()
            (tree / "tracked").write_text("payload\n")
            archive = root / "tree.tar"
            manifest = root / "tree.json"
            result = run_cli(
                "capture-worktree", "--root", str(tree), "--archive", str(archive),
                "--manifest", str(manifest),
            )
            self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
            self.assertTrue(archive.exists())
            self.assertTrue(manifest.exists())

    def test_binary_no_follow_archive_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            tree = root / "tree"
            tree.mkdir()
            (tree / "binary").write_bytes(b"\x00\xffpayload")
            raw_name = os.fsencode(tree) + b"/raw-name"
            fd = os.open(raw_name, os.O_WRONLY | os.O_CREAT, 0o640)
            os.write(fd, b"\xfe\x00")
            os.close(fd)
            os.symlink(b"target-\xff", os.fsencode(tree) + b"/link")
            archive = root / "tree.tar"
            manifest = root / "tree.json"
            output = root / "output"

            capture = run_cli(
                "capture-worktree", "--root", str(tree), "--archive", str(archive),
                "--manifest", str(manifest),
            )
            materialize = run_cli(
                "materialize", "--manifest", str(manifest), "--archive", str(archive),
                "--output", str(output),
            )
            verify = run_cli(
                "verify-materialized", "--manifest", str(manifest), "--root", str(output),
            )

            self.assertEqual((capture.returncode, materialize.returncode, verify.returncode), (0, 0, 0))
            self.assertEqual(os.readlink(os.fsencode(output) + b"/link"), b"target-\xff")
            self.assertEqual((output / "binary").read_bytes(), b"\x00\xffpayload")

    def test_traversal_and_unknown_root_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "bad.json"
            traversal = base64.b64encode(b"../escape").decode()
            path.write_text(
                json.dumps({"schema_version": "agent-brain-tree/v1", "root": "alien",
                            "entries": [{"path_b64": traversal, "type": "file"}]}) + "\n"
            )
            result = run_cli("verify-json", "--input", str(path))
        self.assertEqual(result.returncode, 2)

    def test_capture_worktree_rejects_arbitrary_symlinked_output_parent(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            tree = root / "tree"
            tree.mkdir()
            (tree / "tracked").write_text("payload\n")
            outside = root / "outside"
            outside.mkdir()
            link = root / "link"
            link.symlink_to(outside, target_is_directory=True)
            archive = link / "tree.tar"
            manifest = root / "tree.json"
            result = run_cli(
                "capture-worktree", "--root", str(tree), "--archive", str(archive),
                "--manifest", str(manifest),
            )
            self.assertEqual(result.returncode, 2)
            self.assertFalse((outside / "tree.tar").exists())
            self.assertFalse(manifest.exists())

            final_link = root / "archive-link.tar"
            final_link.symlink_to(outside / "target.tar")
            second_manifest = root / "second-tree.json"
            second = run_cli(
                "capture-worktree", "--root", str(tree), "--archive", str(final_link),
                "--manifest", str(second_manifest),
            )
            self.assertEqual(second.returncode, 2)
            self.assertFalse((outside / "target.tar").exists())
            self.assertFalse(second_manifest.exists())


class BrainStateSnapshotTests(unittest.TestCase):
    def git(self, root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            check=False,
        )

    def capture(self, kind: str, root: Path, base: Path, prefix: str) -> tuple[Path, Path]:
        state = base / f"{prefix}.json"
        sidecars = base / f"{prefix}-sidecars"
        result = run_cli(
            "capture-state",
            "--kind",
            kind,
            "--root",
            str(root),
            "--output",
            str(state),
            "--sidecar-dir",
            str(sidecars),
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        return state, sidecars

    def compare(self, left: Path, left_sidecars: Path, right: Path, right_sidecars: Path) -> int:
        result = run_cli(
            "compare-state",
            "--left",
            str(left),
            "--left-sidecars",
            str(left_sidecars),
            "--right",
            str(right),
            "--right-sidecars",
            str(right_sidecars),
        )
        return result.returncode

    def support_module(self, name: str):
        support = str(ROOT / "tests" / "support")
        if support not in sys.path:
            sys.path.insert(0, support)
        return importlib.import_module(name)

    def fd_count(self) -> int:
        return len(os.listdir("/dev/fd"))

    def test_state_capture_is_read_only_and_detects_admin_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw) / "repo"
            repo.mkdir()
            init_git(repo)
            left = Path(raw) / "left.json"
            right = Path(raw) / "right.json"
            left_sidecars = Path(raw) / "left-sidecars"
            right_sidecars = Path(raw) / "right-sidecars"
            git_before = hashlib.sha256((repo / ".git" / "index").read_bytes()).hexdigest()
            first = run_cli("capture-state", "--kind", "brain", "--root", str(repo),
                            "--output", str(left), "--sidecar-dir", str(left_sidecars))
            git_after = hashlib.sha256((repo / ".git" / "index").read_bytes()).hexdigest()
            head = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True,
                capture_output=True, check=True,
            ).stdout
            (repo / ".git" / "refs" / "heads" / "side").write_text(head)
            second = run_cli("capture-state", "--kind", "brain", "--root", str(repo),
                             "--output", str(right), "--sidecar-dir", str(right_sidecars))
            compared = run_cli("compare-state", "--left", str(left),
                               "--left-sidecars", str(left_sidecars), "--right", str(right),
                               "--right-sidecars", str(right_sidecars))
        self.assertEqual((first.returncode, second.returncode), (0, 0))
        self.assertEqual(git_before, git_after)
        self.assertEqual(compared.returncode, 1)

    def test_state_capture_uses_semantic_index_and_ignores_cache_only_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            repo = base / "repo"
            repo.mkdir()
            init_git(repo)
            left, left_sidecars = self.capture("brain", repo, base, "left")
            before_index = (repo / ".git" / "index").read_bytes()

            os.utime(repo / "tracked", (2_000_000_000, 2_000_000_000))
            refresh = self.git(repo, "update-index", "--refresh")
            self.assertIn(refresh.returncode, {0, 1})
            after_index = (repo / ".git" / "index").read_bytes()
            right, right_sidecars = self.capture("brain", repo, base, "right")
            semantic_index = (left_sidecars / "4-index.bin").read_bytes()
            compared = self.compare(left, left_sidecars, right, right_sidecars)

        self.assertNotEqual(before_index, after_index)
        self.assertNotIn(b"ctime:", semantic_index)
        self.assertNotIn(b"mtime:", semantic_index)
        self.assertEqual(compared, 0)

    def test_state_capture_blocks_staged_blob_mode_membership_and_conflict_stage_changes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            for name, mutate in (
                ("blob", lambda repo: ((repo / "tracked").write_text("changed\n"), self.git(repo, "add", "tracked"))),
                ("mode", lambda repo: self.git(repo, "update-index", "--chmod=+x", "tracked")),
                ("delete", lambda repo: self.git(repo, "rm", "--cached", "tracked")),
            ):
                repo = base / name
                repo.mkdir()
                init_git(repo)
                left, left_sidecars = self.capture("brain", repo, base, f"{name}-left")
                mutate(repo)
                right, right_sidecars = self.capture("brain", repo, base, f"{name}-right")
                self.assertEqual(self.compare(left, left_sidecars, right, right_sidecars), 1)

            conflict_repo = base / "conflict"
            conflict_repo.mkdir()
            init_git(conflict_repo)
            left, left_sidecars = self.capture("brain", conflict_repo, base, "conflict-left")
            self.git(conflict_repo, "checkout", "-qb", "side")
            (conflict_repo / "tracked").write_text("side\n")
            self.git(conflict_repo, "commit", "-am", "side")
            self.git(conflict_repo, "checkout", "-q", "master")
            (conflict_repo / "tracked").write_text("main\n")
            self.git(conflict_repo, "commit", "-am", "main")
            merge = self.git(conflict_repo, "merge", "side")
            self.assertNotEqual(merge.returncode, 0)
            right, right_sidecars = self.capture("brain", conflict_repo, base, "conflict-right")
            stages = {row["stage"] for row in json.loads((right_sidecars / "4-index.bin").read_text())}
            compared = self.compare(left, left_sidecars, right, right_sidecars)

        self.assertEqual(compared, 1)
        self.assertGreaterEqual(stages, {1, 2, 3})

    def test_semantic_index_parser_preserves_raw_path_bytes_and_ordering(self) -> None:
        state_module = self.support_module("evidence_state")
        blob = b"0123456789abcdef0123456789abcdef01234567"
        raw = (
            b"100755 " + blob + b" 3\tz-\xff\0"
            b"100644 " + blob + b" 0\ta-\x80\0"
        )
        parsed = json.loads(state_module._semantic_index(raw).decode("utf-8"))
        self.assertEqual(
            [(row["path_b64"], row["mode"], row["stage"]) for row in parsed],
            [
                (base64.b64encode(b"a-\x80").decode("ascii"), "100644", 0),
                (base64.b64encode(b"z-\xff").decode("ascii"), "100755", 3),
            ],
        )

    def test_state_capture_rejects_symlink_and_occupied_destinations_without_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            repo = base / "repo"
            repo.mkdir()
            init_git(repo)
            outside = base / "outside"
            outside.mkdir()
            link = base / "link"
            link.symlink_to(outside, target_is_directory=True)
            state = base / "state.json"
            result = run_cli(
                "capture-state",
                "--kind",
                "brain",
                "--root",
                str(repo),
                "--output",
                str(state),
                "--sidecar-dir",
                str(link / "sidecars"),
            )
            self.assertEqual(result.returncode, 2)
            self.assertFalse((outside / "sidecars").exists())
            self.assertFalse(state.exists())

            occupied = base / "occupied.json"
            occupied.write_text("preexisting\n")
            occupied_sidecars = base / "occupied-sidecars"
            result = run_cli(
                "capture-state",
                "--kind",
                "brain",
                "--root",
                str(repo),
                "--output",
                str(occupied),
                "--sidecar-dir",
                str(occupied_sidecars),
            )
            self.assertEqual(result.returncode, 2)
            self.assertEqual(occupied.read_text(), "preexisting\n")
            self.assertFalse(occupied_sidecars.exists())

            retry_state, retry_sidecars = self.capture("brain", repo, base, "retry")
            self.assertTrue(retry_state.exists())
            self.assertTrue((retry_sidecars / "4-index.bin").exists())

    def test_state_capture_publication_faults_roll_back_owned_outputs_and_retry(self) -> None:
        state_module = self.support_module("evidence_state")
        publication_module = self.support_module("evidence_publication")
        evidence_json = self.support_module("evidence_json")

        fault_names = ("mkdir", "directory-open", "directory-fstat", "sidecar-create", "write", "fsync", "manifest")
        for fault_name in fault_names:
            with self.subTest(fault=fault_name), tempfile.TemporaryDirectory() as raw:
                base = Path(raw)
                repo = base / "repo"
                repo.mkdir()
                init_git(repo)
                state = base / "state.json"
                sidecars = base / "sidecars"
                patches = self.publication_fault_patches(publication_module, fault_name, state, sidecars)
                with patches[0], patches[1], self.assertRaises(evidence_json.ContractError):
                    state_module.capture_state("brain", repo, state, sidecars)
                self.assertFalse(state.exists())
                self.assertFalse(sidecars.exists())
                retry_state, retry_sidecars = self.capture("brain", repo, base, f"retry-{fault_name}")
                self.assertTrue(retry_state.exists())
                self.assertTrue((retry_sidecars / "4-index.bin").exists())

    def test_state_capture_leaf_identity_failure_removes_unidentified_leaf_and_quarantine(self) -> None:
        state_module = self.support_module("evidence_state")
        publication_module = self.support_module("evidence_publication")
        evidence_json = self.support_module("evidence_json")
        real_fstat_identity = publication_module._fstat_identity

        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            repo = base / "repo"
            repo.mkdir()
            init_git(repo)
            state = base / "state.json"
            sidecars = base / "sidecars"
            failures = 0
            before = self.fd_count()

            def fstat_identity(descriptor: int, path: Path):
                nonlocal failures
                if path.name == "1-symbolic-head.bin" and failures == 0:
                    failures = 3
                    raise evidence_json.ContractError("injected leaf identity failure")
                return real_fstat_identity(descriptor, path)

            with (
                mock.patch.object(publication_module, "_fstat_identity", side_effect=fstat_identity),
                self.assertRaises(evidence_json.ContractError),
            ):
                state_module.capture_state("brain", repo, state, sidecars)

            after = self.fd_count()
            quarantine = sorted(base.glob(".__agent-brain-quarantine-*"))
            self.assertEqual(failures, 3)
            self.assertFalse(state.exists())
            self.assertFalse(sidecars.exists())
            self.assertEqual(quarantine, [])
            self.assertEqual(after, before)
            retry = run_cli(
                "capture-state",
                "--kind",
                "brain",
                "--root",
                str(repo),
                "--output",
                str(state),
                "--sidecar-dir",
                str(sidecars),
            )
            self.assertEqual(retry.returncode, 0, retry.stderr.decode("utf-8", "replace"))
            self.assertTrue(state.exists())
            self.assertTrue((sidecars / "4-index.bin").exists())

    def publication_fault_patches(
        self, publication_module, fault_name: str, state: Path, sidecars: Path
    ) -> tuple[mock._patch, mock._patch]:
        real_mkdir = publication_module.os.mkdir
        real_open = publication_module.os.open
        real_fstat = publication_module.os.fstat
        real_write = publication_module.os.write
        real_fsync = publication_module.os.fsync
        created_sidecar_dir = False
        directory_fstat_failures = 0

        def mkdir(path: str, mode: int = 0o777, *, dir_fd: int | None = None) -> None:
            nonlocal created_sidecar_dir
            if fault_name == "mkdir" and path == sidecars.name:
                raise PermissionError("injected mkdir failure")
            real_mkdir(path, mode, dir_fd=dir_fd)
            if path == sidecars.name:
                created_sidecar_dir = True

        def open_path(
            path: str, flags: int, mode: int = 0o777, *, dir_fd: int | None = None
        ) -> int:
            if fault_name == "directory-open" and created_sidecar_dir and path == sidecars.name:
                raise PermissionError("injected directory open failure")
            if fault_name == "sidecar-create" and path == "1-symbolic-head.bin":
                raise PermissionError("injected sidecar create failure")
            if fault_name == "manifest" and path == state.name:
                raise PermissionError("injected manifest create failure")
            return real_open(path, flags, mode, dir_fd=dir_fd)

        def fstat(descriptor: int) -> os.stat_result:
            nonlocal directory_fstat_failures
            if (
                fault_name == "directory-fstat"
                and created_sidecar_dir
                and directory_fstat_failures < 3
            ):
                directory_fstat_failures += 1
                raise OSError("injected directory fstat failure")
            return real_fstat(descriptor)

        def write(descriptor: int, data: bytes) -> int:
            if fault_name == "write":
                raise OSError("injected write failure")
            return real_write(descriptor, data)

        def fsync(descriptor: int) -> None:
            if fault_name == "fsync":
                raise OSError("injected fsync failure")
            real_fsync(descriptor)

        first = mock.patch.object(publication_module.os, "mkdir", side_effect=mkdir)
        match fault_name:
            case "mkdir":
                second = mock.patch.object(publication_module.os, "open", side_effect=open_path)
            case "directory-open" | "sidecar-create" | "manifest":
                second = mock.patch.object(publication_module.os, "open", side_effect=open_path)
            case "directory-fstat":
                second = mock.patch.object(publication_module.os, "fstat", side_effect=fstat)
            case "write":
                second = mock.patch.object(publication_module.os, "write", side_effect=write)
            case "fsync":
                second = mock.patch.object(publication_module.os, "fsync", side_effect=fsync)
            case unreachable:
                self.fail(f"unhandled fault {unreachable}")
        return first, second

    def test_state_capture_close_failure_reports_contract_error_without_fd_leak(self) -> None:
        state_module = self.support_module("evidence_state")
        publication_module = self.support_module("evidence_publication")
        evidence_json = self.support_module("evidence_json")
        real_open = publication_module.os.open
        real_close = publication_module.os.close

        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            repo = base / "repo"
            repo.mkdir()
            init_git(repo)
            state = base / "state.json"
            sidecars = base / "sidecars"
            directory_fds: set[int] = set()
            manifest_created = False
            failed = False
            before = self.fd_count()

            def open_path(
                path: str, flags: int, mode: int = 0o777, *, dir_fd: int | None = None
            ) -> int:
                nonlocal manifest_created
                descriptor = real_open(path, flags, mode, dir_fd=dir_fd)
                if flags & getattr(os, "O_DIRECTORY", 0):
                    directory_fds.add(descriptor)
                if path == state.name and flags & os.O_CREAT:
                    manifest_created = True
                return descriptor

            def close(descriptor: int) -> None:
                nonlocal failed
                if manifest_created and descriptor in directory_fds and not failed:
                    failed = True
                    real_close(descriptor)
                    raise OSError("injected close failure")
                real_close(descriptor)

            with (
                mock.patch.object(publication_module.os, "open", side_effect=open_path),
                mock.patch.object(publication_module.os, "close", side_effect=close),
                self.assertRaises(evidence_json.ContractError),
            ):
                state_module.capture_state("brain", repo, state, sidecars)

            after = self.fd_count()
            retry = run_cli(
                "capture-state",
                "--kind",
                "brain",
                "--root",
                str(repo),
                "--output",
                str(state),
                "--sidecar-dir",
                str(sidecars),
            )
            self.assertTrue(failed)
            self.assertEqual(after, before)
            self.assertTrue(state.exists())
            self.assertTrue((sidecars / "4-index.bin").exists())
            self.assertEqual(retry.returncode, 2)


class WorktreeSnapshotTests(unittest.TestCase):
    def test_dirty_worktree_captures_tracked_and_non_utf8_untracked(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw) / "repo"
            repo.mkdir()
            init_git(repo)
            (repo / "tracked").write_bytes(b"dirty\n")
            fd = os.open(os.fsencode(repo) + "/untracked-e\u0301".encode(), os.O_CREAT | os.O_WRONLY, 0o600)
            os.write(fd, b"\x00\xff")
            os.close(fd)
            result = run_cli("capture-worktree", "--root", str(repo),
                             "--archive", str(Path(raw) / "a.tar"),
                             "--manifest", str(Path(raw) / "m.json"))
            manifest = canonical(Path(raw) / "m.json")
        self.assertEqual(result.returncode, 0)
        self.assertIn("git_status_sha256", manifest)


class EvidenceReceiptTests(EvidenceAdversarialCases, unittest.TestCase):
    pass


class BaselineTestIdTests(unittest.TestCase):
    def test_exact_113_ids_are_pinned(self) -> None:
        ids = IDS.read_text().splitlines()
        self.assertEqual(len(ids), 113)
        self.assertEqual(ids, sorted(set(ids)))


class FinalLanePlanContractTests(unittest.TestCase):
    def final_lane_commands(self) -> list[str]:
        payload = json.loads(FINAL_LANE_COMMANDS.read_text(encoding="utf-8"))
        self.assertEqual(
            payload.get("schema_version"),
            "agent-brain-final-lane-commands/v1",
        )
        commands = payload.get("commands")
        self.assertIsInstance(commands, list)
        self.assertTrue(all(isinstance(command, str) for command in commands))
        return commands

    def test_final_lane_unittest_targets_resolve(self) -> None:
        targets = [
            target
            for command in self.final_lane_commands()
            if command.startswith("python3 -m unittest ")
            for target in shlex.split(command)[3:]
            if target != "-v"
        ]

        self.assertTrue(targets)
        for target in targets:
            with self.subTest(target=target):
                module_name, separator, class_name = target.rpartition(".")
                if separator and class_name.endswith("Tests"):
                    module = importlib.import_module(module_name)
                    test_class = getattr(module, class_name)
                    self.assertTrue(issubclass(test_class, unittest.TestCase))
                else:
                    importlib.import_module(target)

    def test_final_lane_only_selectors_are_declared(self) -> None:
        selector_values = [
            tokens[tokens.index("--only") + 1]
            for command in self.final_lane_commands()
            if "model/SCRIPTS/model_check.py" in command and "--only" in command
            for tokens in (shlex.split(command),)
        ]
        scripts = str(ROOT / "model" / "SCRIPTS")
        inserted = scripts not in sys.path
        if inserted:
            sys.path.insert(0, scripts)
        try:
            contract_module = importlib.import_module("model_check_contract")
            contract = contract_module.parse_metadata(canonical(MODEL))
        finally:
            if inserted:
                sys.path.remove(scripts)
        declared = (
            {code.family for code in contract.codes}
            | {code.code for code in contract.codes}
            | set(contract.aliases)
        )

        self.assertTrue(selector_values)
        for value in selector_values:
            for selector in value.split(","):
                with self.subTest(selector=selector):
                    self.assertIn(selector, declared)


class BaselineRunnerContractTests(unittest.TestCase):
    def run_runner(
        self,
        *,
        git_ref: str = TEST_BASELINE,
        expected_ids: Path = IDS,
    ) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            [
                sys.executable,
                "-B",
                str(RUNNER),
                "--root",
                ".",
                "--git-ref",
                git_ref,
                "--expected-ids",
                str(expected_ids),
            ],
            cwd=ROOT,
            capture_output=True,
            check=False,
        )

    def test_current_test_module_drift_does_not_change_pinned_runner_contract(self) -> None:
        result = self.run_runner()
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        payload = json.loads(result.stdout)
        self.assertEqual(payload["count"], 113)
        self.assertEqual(payload["status"], 0)

    def test_expected_ids_reject_duplicates_missing_and_extra_entries(self) -> None:
        ids = IDS.read_text().splitlines()
        cases = {
            "duplicate": sorted(ids[:-2] + [ids[0], ids[0]]),
            "missing": ids[:-1],
            "extra": sorted([*ids, "zz_extra.Module.test_unexpected"]),
        }
        with tempfile.TemporaryDirectory() as raw:
            temp = Path(raw)
            for name, case_ids in cases.items():
                with self.subTest(name=name):
                    path = temp / f"{name}.txt"
                    path.write_text("\n".join(case_ids) + "\n", encoding="utf-8")
                    result = self.run_runner(expected_ids=path)
                    self.assertEqual(result.returncode, 2)
                    self.assertIn(
                        "expected ID file must contain 113 unique sorted IDs",
                        result.stderr.decode("utf-8", "replace"),
                    )

    def test_malicious_expected_ids_are_rejected_before_path_derivation(self) -> None:
        from tests.support.baseline_materializer import BaselineError, module_refs_from_ids

        cases = [
            "/tmp/evil.Case.test_method",
            "C:\\evil.Case.test_method",
            "..Case.test_method",
            ".tests.test_home_setup.HomeSetupTests.test_apply_is_idempotent",
            "tests../evil.Case.test_method",
            "tests.test_home_setup.HomeSetupTests.test_bad/method",
            "tests.test_home_setup.HomeSetupTests.test_bad\\method",
            "tests.test_home_setup.HomeSetupTests.test_bad\u2215method",
            "tests.test_home_setup.HomeSetupTests.test_bad\x00method",
            "tests.test-home-setup.HomeSetupTests.test_apply_is_idempotent",
        ]

        for identifier in cases:
            with self.subTest(identifier=identifier):
                with self.assertRaisesRegex(BaselineError, "invalid baseline test ID"):
                    module_refs_from_ids([identifier])

    def test_materializer_rejects_corrupt_bytes_and_missing_git_objects(self) -> None:
        from tests.support.baseline_materializer import (
            BaselineError,
            module_refs_from_ids,
            read_git_object,
            verify_materialized_bytes,
        )

        ids = IDS.read_text().splitlines()
        home_setup = [
            module
            for module in module_refs_from_ids(ids)
            if module.relative_path == Path("tests/test_home_setup.py")
        ][0]
        with tempfile.TemporaryDirectory() as raw:
            materialized = Path(raw) / "tests" / "test_home_setup.py"
            materialized.parent.mkdir()
            expected = read_git_object(ROOT, TEST_BASELINE, home_setup.relative_path)
            materialized.write_bytes(expected + b"# corrupt\n")
            with self.assertRaisesRegex(BaselineError, "materialized baseline test corrupted"):
                verify_materialized_bytes(home_setup, expected, materialized)

        with self.assertRaisesRegex(BaselineError, "baseline test missing at ref"):
            read_git_object(ROOT, "missing-ref-for-baseline-tests", home_setup.relative_path)
        with self.assertRaisesRegex(BaselineError, "baseline test missing at ref"):
            read_git_object(ROOT, TEST_BASELINE, Path("tests/test_missing_baseline_path.py"))

    def test_current_test_file_can_add_sentinel_without_affecting_materialized_hashes(self) -> None:
        from tests.support.baseline_materializer import (
            materialize_baseline_modules,
            module_refs_from_ids,
            read_git_object,
        )

        ids = IDS.read_text().splitlines()
        refs = module_refs_from_ids(ids)
        with tempfile.TemporaryDirectory() as raw:
            modules = materialize_baseline_modules(ROOT, TEST_BASELINE, refs, Path(raw))

        by_path = {module.relative_path: module for module in modules}
        path = Path("tests/test_home_setup.py")
        pinned = hashlib.sha256(read_git_object(ROOT, TEST_BASELINE, path)).hexdigest()
        current_with_sentinel = hashlib.sha256(
            (ROOT / path).read_bytes() + b"\n    def test_sentinel_current_only(self): pass\n"
        ).hexdigest()
        self.assertEqual(by_path[path].sha256, pinned)
        self.assertNotEqual(by_path[path].sha256, current_with_sentinel)

    def test_current_production_mutation_is_visible_to_materialized_tests(self) -> None:
        from tests.support.baseline_materializer import (
            materialize_baseline_modules,
            module_refs_from_ids,
            run_materialized_ids,
        )

        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw) / "repo"
            (repo / "tests").mkdir(parents=True)
            (repo / "model" / "SCRIPTS").mkdir(parents=True)
            (repo / "tests" / "test_probe.py").write_text(
                "from __future__ import annotations\n"
                "import unittest\n"
                "from pathlib import Path\n\n"
                "ROOT = Path(__file__).resolve().parents[1]\n\n"
                "class ProbeTests(unittest.TestCase):\n"
                "    def test_reads_current_production_file(self) -> None:\n"
                "        self.assertEqual((ROOT / 'model' / 'SCRIPTS' / 'probe.txt').read_text(), 'mutated\\n')\n",
                encoding="utf-8",
            )
            (repo / "model" / "SCRIPTS" / "probe.txt").write_text("baseline\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "test"], cwd=repo, check=True)
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "baseline"], cwd=repo, check=True)
            git_ref = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo,
                text=True,
                capture_output=True,
                check=True,
            ).stdout.strip()
            (repo / "model" / "SCRIPTS" / "probe.txt").write_text("mutated\n", encoding="utf-8")
            ids = ["test_probe.ProbeTests.test_reads_current_production_file"]
            with tempfile.TemporaryDirectory() as temp_root:
                modules = materialize_baseline_modules(
                    repo,
                    git_ref,
                    module_refs_from_ids(ids),
                    Path(temp_root),
                )
                run_result = run_materialized_ids(repo, Path(temp_root), modules, ids)
        self.assertEqual(run_result.status, 0, run_result.transcript)
        self.assertEqual(run_result.loaded_ids, ids)

    def test_child_execution_ignores_parent_test_and_production_import_cache(self) -> None:
        from tests.support.baseline_materializer import (
            materialize_baseline_modules,
            module_refs_from_ids,
            run_materialized_ids,
        )

        poison_test = types.ModuleType("test_probe")
        poison_production = types.ModuleType("probe")
        poison_production.VALUE = "poisoned-parent-cache"
        previous_test = sys.modules.get("test_probe")
        previous_production = sys.modules.get("probe")
        sys.modules["test_probe"] = poison_test
        sys.modules["probe"] = poison_production
        try:
            with tempfile.TemporaryDirectory() as raw:
                repo = Path(raw) / "repo"
                (repo / "tests").mkdir(parents=True)
                (repo / "model" / "SCRIPTS").mkdir(parents=True)
                (repo / "tests" / "test_probe.py").write_text(
                    "from __future__ import annotations\n"
                    "import unittest\n"
                    "from pathlib import Path\n\n"
                    "ROOT = Path(__file__).resolve().parents[1]\n"
                    "import sys\n"
                    "sys.path.insert(0, str(ROOT / 'model' / 'SCRIPTS'))\n"
                    "from probe import VALUE\n\n"
                    "class ProbeTests(unittest.TestCase):\n"
                    "    def test_reads_pinned_test_and_current_production(self) -> None:\n"
                    "        self.assertEqual(VALUE, 'mutated-current-production')\n",
                    encoding="utf-8",
                )
                (repo / "model" / "SCRIPTS" / "probe.py").write_text(
                    "VALUE = 'committed-baseline-production'\n",
                    encoding="utf-8",
                )
                subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
                subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
                subprocess.run(["git", "config", "user.name", "test"], cwd=repo, check=True)
                subprocess.run(["git", "add", "."], cwd=repo, check=True)
                subprocess.run(["git", "commit", "-qm", "baseline"], cwd=repo, check=True)
                git_ref = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    cwd=repo,
                    text=True,
                    capture_output=True,
                    check=True,
                ).stdout.strip()
                (repo / "model" / "SCRIPTS" / "probe.py").write_text(
                    "VALUE = 'mutated-current-production'\n",
                    encoding="utf-8",
                )
                ids = ["test_probe.ProbeTests.test_reads_pinned_test_and_current_production"]
                with tempfile.TemporaryDirectory() as temp_root:
                    modules = materialize_baseline_modules(
                        repo,
                        git_ref,
                        module_refs_from_ids(ids),
                        Path(temp_root),
                    )
                    run_result = run_materialized_ids(repo, Path(temp_root), modules, ids)
        finally:
            if previous_test is None:
                sys.modules.pop("test_probe", None)
            else:
                sys.modules["test_probe"] = previous_test
            if previous_production is None:
                sys.modules.pop("probe", None)
            else:
                sys.modules["probe"] = previous_production

        self.assertEqual(run_result.status, 0, run_result.transcript)
        self.assertEqual(run_result.loaded_ids, ids)
        self.assertNotIn("poisoned-parent-cache", run_result.transcript)


class RunTodoExpansionTests(unittest.TestCase):
    def open_fd_count(self) -> int:
        return len(list(Path("/dev/fd").iterdir()))

    def write_impl_root(self, root: Path, commands: list[str], mode: str = "argv", todo: int = 5) -> None:
        (root / "tests" / "fixtures").mkdir(parents=True)
        (root / "model").mkdir()
        plan = root / ".omo" / "plans" / "agent-brain-operating-model.md"
        plan.parent.mkdir(parents=True)
        plan.write_text("# fixture plan\n", encoding="utf-8")
        (root / "model" / "OPERATING-MODEL.json").write_text(
            json.dumps(
                {
                    "baseline": {
                        "plan_sha256": hashlib.sha256(plan.read_bytes()).hexdigest(),
                    },
                    "schema_version": "agent-brain-operating-model/v1",
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )
        steps = [
            {"command": command, "mode": mode, "step": index}
            for index, command in enumerate(commands, start=1)
        ]
        (root / "tests" / "fixtures" / "operating-model-qa-commands.json").write_text(
            json.dumps(
                {
                    "schema_version": "agent-brain-qa-commands/v1",
                    "todos": [{"steps": steps, "todo": todo}],
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )

    def plan_path(self, root: Path) -> Path:
        return root / ".omo" / "plans" / "agent-brain-operating-model.md"

    def run_todo(
        self,
        *,
        root: Path,
        evidence: Path,
        step: int,
        todo: int = 5,
        argv: list[str] | None = None,
        shell: str | None = None,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        command = [
            "run-todo",
            "--todo",
            str(todo),
            "--step",
            str(step),
            "--cwd",
            str(root.resolve()),
            "--evidence-root",
            str(evidence.resolve()),
        ]
        if shell is not None:
            command.extend(["--shell", shell])
        if argv is not None:
            command.extend(["--", *argv])
        if env is None:
            return run_cli(*command)
        merged_env = {**os.environ, **env}
        return subprocess.run(
            [sys.executable, "-B", str(CLI), *command],
            cwd=ROOT,
            env=merged_env,
            capture_output=True,
            check=False,
        )

    def seal_todo(
        self,
        *,
        root: Path,
        evidence: Path,
        todo: int = 5,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        source = evidence / "source.json"
        brain = evidence / "brain.json"
        log = evidence / "task.log"
        source.write_text("{}\n", encoding="utf-8")
        brain.write_text("{}\n", encoding="utf-8")
        log.write_text("task\n", encoding="utf-8")
        return subprocess.run(
            [
                sys.executable,
                "-B",
                str(CLI),
                "seal-todo",
                "--todo",
                str(todo),
                "--plan",
                str(self.plan_path(root)),
                "--baseline-commit",
                MODEL_BASELINE,
                "--impl-root",
                str(root.resolve()),
                "--source-baseline",
                str(source),
                "--brain-baseline",
                str(brain),
                "--runs",
                str(evidence / f"task-{todo}-runs"),
                "--task-log",
                str(log),
                "--output",
                str(evidence / "receipt.json"),
            ],
            cwd=ROOT,
            env={**os.environ, **(env or {})},
            capture_output=True,
            check=False,
        )

    def write_canonical_json(self, path: Path, value: dict[str, JsonValue]) -> None:
        path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")

    def archive_blobs(self, archive: Path) -> dict[str, bytes]:
        blobs: dict[str, bytes] = {}
        with tarfile.open(archive, mode="r:") as source:
            for member in source.getmembers():
                stream = source.extractfile(member)
                if stream is None:
                    continue
                blobs[member.name.removeprefix("blobs/")] = stream.read()
        return blobs

    def write_archive(self, archive: Path, blobs: dict[str, bytes]) -> None:
        with tarfile.open(archive, mode="w", format=tarfile.USTAR_FORMAT) as target:
            for sha256 in sorted(blobs):
                data = blobs[sha256]
                info = tarfile.TarInfo(f"blobs/{sha256}")
                info.size = len(data)
                info.mode = 0o600
                info.uid = 0
                info.gid = 0
                info.uname = ""
                info.gname = ""
                info.mtime = 0
                target.addfile(info, io.BytesIO(data))

    def write_single_step_receipt(self, root: Path, evidence: Path) -> tuple[dict[str, JsonValue], dict[str, JsonValue]]:
        self.write_impl_root(root, ["python3 -c 'print(1)'"])
        run = self.run_todo(root=root, evidence=evidence, step=1, argv=["python3", "-c", "print(1)"])
        sealed = self.seal_todo(root=root, evidence=evidence)
        self.assertEqual(run.returncode, 0, run.stderr.decode("utf-8", "replace"))
        self.assertEqual(sealed.returncode, 0, sealed.stderr.decode("utf-8", "replace"))
        return canonical(evidence / "receipt.json"), canonical(evidence / "task-5-runs" / "1.json")

    def write_review_fixture(self, root: Path, evidence: Path) -> dict[str, str]:
        plan = self.plan_path(root)
        draft = root / ".omo" / "drafts" / "agent-brain-operating-model.md"
        draft.parent.mkdir(parents=True)
        plan_sha = hashlib.sha256(plan.read_bytes()).hexdigest()
        draft.write_text(
            "```json\n"
            + json.dumps(
                {
                    "plan_sha256": plan_sha,
                    "review": {
                        "independent": {"launch_id": "independent-launch"},
                        "momus": {"launch_id": "momus-launch"},
                    },
                    "review_round_id": "round-1",
                    "round_status": "approved",
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n```\n",
            encoding="utf-8",
        )
        review_root = evidence / "plan-review"
        review_root.mkdir()
        for reviewer, launch in (("momus", "momus-launch"), ("independent", "independent-launch")):
            (review_root / f"{reviewer}.txt").write_text(
                json.dumps(
                    {
                        "launch_id": launch,
                        "plan_sha256": plan_sha,
                        "reviewer": reviewer,
                        "round_id": "round-1",
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\nOKAY\n",
                encoding="utf-8",
            )
        return {
            "BRAIN_ROOT": str(root.resolve()),
            "DRAFT": str(draft.resolve()),
            "IMPL_ROOT": str(root.resolve()),
            "PLAN": str(plan.resolve()),
            "PLAN_REVIEW_ROOT": str(review_root.resolve()),
            "REVIEW_SEAL": str((review_root / "review.json").resolve()),
            "SOURCE_ROOT": str(root.resolve()),
        }

    def write_brain_review_fixture(self, root: Path, evidence: Path, brain: Path) -> dict[str, str]:
        active = self.plan_path(root)
        active.write_text("# active execution plan\n- [x] advanced checkbox\n", encoding="utf-8")
        brain_plan = brain / ".omo" / "plans" / "agent-brain-operating-model.md"
        draft = brain / ".omo" / "drafts" / "agent-brain-operating-model.md"
        brain_plan.parent.mkdir(parents=True)
        draft.parent.mkdir(parents=True)
        brain_plan.write_text("# reviewed brain plan\n- [ ] original checkbox\n", encoding="utf-8")
        plan_sha = hashlib.sha256(brain_plan.read_bytes()).hexdigest()
        draft.write_text(
            "```json\n"
            + json.dumps(
                {
                    "plan_sha256": plan_sha,
                    "review": {
                        "independent": {"launch_id": "independent-launch"},
                        "momus": {"launch_id": "momus-launch"},
                    },
                    "review_round_id": "round-1",
                    "round_status": "approved",
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n```\n",
            encoding="utf-8",
        )
        review_root = evidence / "plan-review"
        review_root.mkdir()
        for reviewer, launch in (("momus", "momus-launch"), ("independent", "independent-launch")):
            (review_root / f"{reviewer}.txt").write_text(
                json.dumps(
                    {
                        "launch_id": launch,
                        "plan_sha256": plan_sha,
                        "reviewer": reviewer,
                        "round_id": "round-1",
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\nOKAY\n",
                encoding="utf-8",
            )
        return {
            "BRAIN_ROOT": str(brain.resolve()),
            "DRAFT": str(draft.resolve()),
            "IMPL_ROOT": str(root.resolve()),
            "PLAN": str(brain_plan.resolve()),
            "PLAN_REVIEW_ROOT": str(review_root.resolve()),
            "REVIEW_SEAL": str((review_root / "review.json").resolve()),
            "SOURCE_ROOT": str(root.resolve()),
        }

    def canonical_plan_review_command(self) -> str:
        return (
            'python3 tests/support/evidence_contract.py plan-review --plan "$PLAN" '
            '--draft "$DRAFT" --momus-receipt "$PLAN_REVIEW_ROOT/momus.txt" '
            '--independent-receipt "$PLAN_REVIEW_ROOT/independent.txt" --output "$REVIEW_SEAL"'
        )

    def canonical_todo1_source_capture_command(self) -> str:
        return (
            'python3 tests/support/evidence_contract.py capture-state --kind source --root "$SOURCE_ROOT" '
            '--output "$EVIDENCE_ROOT/source-preflight.json" '
            '--sidecar-dir "$EVIDENCE_ROOT/source-preflight-sidecars"'
        )

    def canonical_todo4_stale_scan_command(self) -> str:
        return (
            "rg -n --hidden --glob '!.git/**' "
            "'(SKILLS/obsidian|_COMMON/SKILLS/obsidian|brain_setup\\.py|vault_setup\\.py|"
            "skill_setup\\.py|find_brains\\.py|/obsidian|SKILL\\.obsidian\\.common\\.md|"
            "TEMPLATE\\.daily-note\\.md)' . > \"$EVIDENCE_ROOT/task-4-stale-scan.txt\"; "
            "status=$?; test \"$status\" -le 1"
        )

    def canonical_todo5_freeze_context_command(self) -> str:
        return (
            "python3 tests/support/evidence_contract.py freeze-context "
            "--source tests/fixtures/model-context-baseline.json "
            "--digest tests/fixtures/model-context-baseline.sha256 "
            '--output "$EVIDENCE_ROOT/context-baseline.json" '
            '--output-digest "$EVIDENCE_ROOT/context-baseline.sha256"'
        )

    def write_context_fixture(self, root: Path) -> None:
        fixtures = root / "tests" / "fixtures"
        fixtures.mkdir(parents=True, exist_ok=True)
        source = fixtures / "model-context-baseline.json"
        digest_file = fixtures / "model-context-baseline.sha256"
        source.write_bytes((ROOT / "tests" / "fixtures" / "model-context-baseline.json").read_bytes())
        digest_file.write_bytes((ROOT / "tests" / "fixtures" / "model-context-baseline.sha256").read_bytes())

    def test_freeze_context_direct_create_only_and_digest_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            evidence = Path(raw).resolve() / "evidence"
            evidence.mkdir()
            source = ROOT / "tests" / "fixtures" / "model-context-baseline.json"
            source_digest = ROOT / "tests" / "fixtures" / "model-context-baseline.sha256"
            expected_digest = source_digest.read_text("ascii").strip()
            output = evidence / "context-baseline.json"
            output_digest = evidence / "context-baseline.sha256"

            first = run_cli(
                "freeze-context",
                "--source",
                str(source),
                "--digest",
                str(source_digest),
                "--output",
                str(output),
                "--output-digest",
                str(output_digest),
            )
            self.assertEqual(first.returncode, 0, first.stderr.decode("utf-8", "replace"))
            output_bytes = output.read_bytes()
            digest_bytes = output_digest.read_bytes()
            second = run_cli(
                "freeze-context",
                "--source",
                str(source),
                "--digest",
                str(source_digest),
                "--output",
                str(output),
                "--output-digest",
                str(output_digest),
            )
            output_after_duplicate = output.read_bytes()
            digest_after_duplicate = output_digest.read_bytes()
            target = evidence / "target.txt"
            target.write_text("target\n", encoding="utf-8")
            symlink = evidence / "symlink-output.json"
            symlink.symlink_to(target)
            symlink_digest = evidence / "symlink-output.sha256"
            symlink_attempt = run_cli(
                "freeze-context",
                "--source",
                str(source),
                "--digest",
                str(source_digest),
                "--output",
                str(symlink),
                "--output-digest",
                str(symlink_digest),
            )
            target_after_symlink = target.read_text(encoding="utf-8")
            symlink_digest_exists = symlink_digest.exists()
            bad_digest = evidence / "bad.sha256"
            bad_digest.write_text("0" * 64 + "\n", encoding="ascii")
            mismatch_output = evidence / "mismatch.json"
            mismatch = run_cli(
                "freeze-context",
                "--source",
                str(source),
                "--digest",
                str(bad_digest),
                "--output",
                str(mismatch_output),
                "--output-digest",
                str(evidence / "mismatch.sha256"),
            )
            mismatch_output_exists = mismatch_output.exists()

        self.assertEqual(output_bytes, source.read_bytes())
        self.assertEqual(hashlib.sha256(output_bytes).hexdigest(), expected_digest)
        self.assertEqual(digest_bytes, (expected_digest + "\n").encode("ascii"))
        self.assertEqual(second.returncode, 2)
        self.assertEqual(output_after_duplicate, output_bytes)
        self.assertEqual(digest_after_duplicate, digest_bytes)
        self.assertEqual(symlink_attempt.returncode, 2)
        self.assertEqual(target_after_symlink, "target\n")
        self.assertFalse(symlink_digest_exists)
        self.assertEqual(mismatch.returncode, 2)
        self.assertFalse(mismatch_output_exists)

    def test_create_bytes_and_json_reject_symlink_path_components(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            real_parent = root / "real"
            real_parent.mkdir()
            parent_link = root / "parent-link"
            parent_link.symlink_to(real_parent, target_is_directory=True)
            final_target = real_parent / "target.bin"
            final_target.write_bytes(b"target\n")
            final_link = real_parent / "final-link.bin"
            final_link.symlink_to(final_target)

            with self.assertRaises(ContractError):
                create_bytes(parent_link / "out.bin", b"unsafe\n")
            with self.assertRaises(ContractError):
                create_json(parent_link / "out.json", {"unsafe": True})
            with self.assertRaises(ContractError):
                create_bytes(final_link, b"unsafe\n")

            self.assertFalse((real_parent / "out.bin").exists())
            self.assertFalse((real_parent / "out.json").exists())
            self.assertEqual(final_target.read_bytes(), b"target\n")

    def test_create_bytes_parent_swap_race_does_not_write_through_new_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            parent = root / "parent"
            outside = root / "outside"
            parent.mkdir()
            outside.mkdir()
            output = parent / "out.bin"
            outside_output = outside / "out.bin"
            real_open = evidence_json_module.os.open
            swapped = False

            def racing_open(
                path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
                flags: int,
                mode: int = 0o777,
                *,
                dir_fd: int | None = None,
            ) -> int:
                nonlocal swapped
                if flags & os.O_CREAT and not swapped:
                    swapped = True
                    parent.rmdir()
                    parent.symlink_to(outside, target_is_directory=True)
                return real_open(path, flags, mode, dir_fd=dir_fd)

            with mock.patch.object(evidence_json_module.os, "open", side_effect=racing_open):
                try:
                    create_bytes(output, b"pinned\n")
                except ContractError:
                    pass

            self.assertTrue(swapped)
            self.assertFalse(outside_output.exists())

    def test_create_bytes_pin_parent_closes_next_fd_when_prior_close_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            output = root / "parent" / "child" / "out.bin"
            output.parent.mkdir(parents=True)
            real_open = evidence_json_module.os.open
            real_close = evidence_json_module.os.close
            child_fd: int | None = None
            close_events: list[int] = []
            child_fd_prior_close_count = 0
            fail_after_child_open = False
            close_failed = False
            before_fds = self.open_fd_count()

            def tracking_open(
                path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
                flags: int,
                mode: int = 0o777,
                *,
                dir_fd: int | None = None,
            ) -> int:
                nonlocal child_fd, child_fd_prior_close_count, fail_after_child_open
                descriptor = real_open(path, flags, mode, dir_fd=dir_fd)
                if path == "child" and dir_fd is not None:
                    child_fd = descriptor
                    child_fd_prior_close_count = close_events.count(descriptor)
                    fail_after_child_open = True
                return descriptor

            def failing_close(fd: int) -> None:
                nonlocal close_failed
                close_events.append(fd)
                if fail_after_child_open and not close_failed and fd != child_fd:
                    close_failed = True
                    real_close(fd)
                    raise OSError("simulated prior parent close failure")
                real_close(fd)

            with mock.patch.object(evidence_json_module.os, "open", side_effect=tracking_open):
                with mock.patch.object(evidence_json_module.os, "close", side_effect=failing_close):
                    with self.assertRaises(ContractError):
                        create_bytes(output, b"context\n")

            self.assertTrue(close_failed)
            self.assertIsNotNone(child_fd)
            self.assertEqual(close_events.count(child_fd), child_fd_prior_close_count + 1)
            self.assertLessEqual(self.open_fd_count(), before_fds)
            self.assertFalse(output.exists())

    def test_create_bytes_pair_same_parent_namespace_swap_uses_one_pinned_parent(self) -> None:
        """Portable contract: same-parent pairs share one pinned parent fd.

        The supported guarantee is deterministic no-follow path traversal and
        exclusive create/retry behavior; hostile same-user namespace replacement
        beyond pinned-fd operations is residual risk, not a portable promise.
        """
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            parent = root / "parent"
            hidden_parent = root / "hidden-parent"
            parent.mkdir()
            first = parent / "context-baseline.json"
            second = parent / "context-baseline.sha256"
            real_stat = evidence_json_module.os.stat
            swapped = False

            def racing_stat(
                path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
                *,
                dir_fd: int | None = None,
                follow_symlinks: bool = True,
            ) -> os.stat_result:
                nonlocal swapped
                try:
                    return real_stat(path, dir_fd=dir_fd, follow_symlinks=follow_symlinks)
                except FileNotFoundError:
                    if path == first.name and dir_fd is not None and not swapped:
                        swapped = True
                        parent.rename(hidden_parent)
                        parent.mkdir()
                    raise

            with mock.patch.object(evidence_json_module.os, "stat", side_effect=racing_stat):
                create_bytes_pair((first, b"context\n"), (second, b"digest\n"))

            self.assertTrue(swapped)
            self.assertFalse(first.exists())
            self.assertFalse(second.exists())
            self.assertEqual((hidden_parent / first.name).read_bytes(), b"context\n")
            self.assertEqual((hidden_parent / second.name).read_bytes(), b"digest\n")

    def test_create_bytes_pair_does_not_delete_replacement_leaf_after_second_create_failure(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            root.mkdir(exist_ok=True)
            first = root / "context-baseline.json"
            second = root / "context-baseline.sha256"
            real_open = evidence_json_module.os.open
            create_calls = 0

            def racing_open(
                path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
                flags: int,
                mode: int = 0o777,
                *,
                dir_fd: int | None = None,
            ) -> int:
                nonlocal create_calls
                if flags & os.O_CREAT:
                    create_calls += 1
                    if create_calls == 2:
                        first.unlink()
                        first.write_bytes(b"replacement\n")
                        raise PermissionError("simulated second create failure")
                return real_open(path, flags, mode, dir_fd=dir_fd)

            with mock.patch.object(evidence_json_module.os, "open", side_effect=racing_open):
                with self.assertRaises(ContractError):
                    create_bytes_pair((first, b"original\n"), (second, b"digest\n"))

            self.assertEqual(create_calls, 2)
            self.assertEqual(first.read_bytes(), b"replacement\n")
            self.assertFalse(second.exists())

    def test_create_bytes_pair_rollback_preserves_replacement_swapped_after_identity_check(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            first = root / "context-baseline.json"
            second = root / "context-baseline.sha256"
            real_open = evidence_json_module.os.open
            real_rename = evidence_json_module.os.rename
            swapped = False
            create_calls = 0

            def failing_second_open(
                path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
                flags: int,
                mode: int = 0o777,
                *,
                dir_fd: int | None = None,
            ) -> int:
                nonlocal create_calls
                if flags & os.O_CREAT:
                    create_calls += 1
                    if create_calls == 2:
                        raise PermissionError("simulated second create failure")
                return real_open(path, flags, mode, dir_fd=dir_fd)

            def racing_rename(
                src: str | bytes | os.PathLike[str] | os.PathLike[bytes],
                dst: str | bytes | os.PathLike[str] | os.PathLike[bytes],
                *,
                src_dir_fd: int | None = None,
                dst_dir_fd: int | None = None,
            ) -> None:
                nonlocal swapped
                if src == first.name and src_dir_fd is not None and not swapped:
                    swapped = True
                    first.unlink()
                    first.write_bytes(b"replacement\n")
                real_rename(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)

            with mock.patch.object(evidence_json_module.os, "open", side_effect=failing_second_open):
                with mock.patch.object(evidence_json_module.os, "rename", side_effect=racing_rename):
                    with self.assertRaises(ContractError):
                        create_bytes_pair((first, b"original\n"), (second, b"digest\n"))

            self.assertTrue(swapped)
            self.assertEqual(first.read_bytes(), b"replacement\n")
            self.assertFalse(second.exists())

    def test_create_bytes_pair_rollback_never_unlinks_original_leaf_name(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            first = root / "context-baseline.json"
            second = root / "context-baseline.sha256"
            real_open = evidence_json_module.os.open
            real_unlink = evidence_json_module.os.unlink
            create_calls = 0

            def failing_second_open(
                path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
                flags: int,
                mode: int = 0o777,
                *,
                dir_fd: int | None = None,
            ) -> int:
                nonlocal create_calls
                if flags & os.O_CREAT:
                    create_calls += 1
                    if create_calls == 2:
                        raise PermissionError("simulated second create failure")
                return real_open(path, flags, mode, dir_fd=dir_fd)

            def guarded_unlink(
                path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
                *,
                dir_fd: int | None = None,
            ) -> None:
                if path == first.name and dir_fd is not None:
                    raise AssertionError("rollback attempted direct original-name unlink")
                real_unlink(path, dir_fd=dir_fd)

            with mock.patch.object(evidence_json_module.os, "open", side_effect=failing_second_open):
                with mock.patch.object(evidence_json_module.os, "unlink", side_effect=guarded_unlink):
                    with self.assertRaises(ContractError):
                        create_bytes_pair((first, b"original\n"), (second, b"digest\n"))

            self.assertFalse(first.exists())
            self.assertFalse(second.exists())

    def test_create_bytes_pair_removes_original_created_inode_after_second_create_failure_and_retries(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            first = root / "context-baseline.json"
            second = root / "context-baseline.sha256"
            real_open = evidence_json_module.os.open
            create_calls = 0

            def failing_second_open(
                path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
                flags: int,
                mode: int = 0o777,
                *,
                dir_fd: int | None = None,
            ) -> int:
                nonlocal create_calls
                if flags & os.O_CREAT:
                    create_calls += 1
                    if create_calls == 2:
                        raise PermissionError("simulated second create failure")
                return real_open(path, flags, mode, dir_fd=dir_fd)

            with mock.patch.object(evidence_json_module.os, "open", side_effect=failing_second_open):
                with self.assertRaises(ContractError):
                    create_bytes_pair((first, b"original\n"), (second, b"digest\n"))
            retried = create_bytes_pair((first, b"original\n"), (second, b"digest\n"))

            self.assertIsNone(retried)
            self.assertEqual(create_calls, 2)
            self.assertEqual(first.read_bytes(), b"original\n")
            self.assertEqual(second.read_bytes(), b"digest\n")

    def test_create_bytes_transient_fstat_failure_closes_fd_and_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            output = root / "context-baseline.json"
            real_fstat = evidence_json_module.os.fstat
            fstat_calls = 0
            before_fds = self.open_fd_count()

            def transient_fstat(fd: int) -> os.stat_result:
                nonlocal fstat_calls
                fstat_calls += 1
                if fstat_calls == 1:
                    raise OSError("simulated transient fstat failure")
                return real_fstat(fd)

            with mock.patch.object(evidence_json_module.os, "fstat", side_effect=transient_fstat):
                create_bytes(output, b"context\n")

            self.assertGreaterEqual(fstat_calls, 2)
            self.assertEqual(output.read_bytes(), b"context\n")
            self.assertLessEqual(self.open_fd_count(), before_fds)

    def test_create_bytes_write_and_fsync_failures_roll_back_without_fd_leak(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            for failing_call in ("write", "fsync"):
                with self.subTest(failing_call=failing_call):
                    output = root / f"{failing_call}.json"
                    before_fds = self.open_fd_count()
                    original = getattr(evidence_json_module.os, failing_call)

                    def fail_once(*args: int | bytes | memoryview) -> int | None:
                        raise OSError(f"simulated {failing_call} failure")

                    with mock.patch.object(evidence_json_module.os, failing_call, side_effect=fail_once):
                        with self.assertRaises(ContractError):
                            create_bytes(output, b"context\n")

                    setattr(evidence_json_module.os, failing_call, original)
                    self.assertFalse(output.exists())
                    self.assertLessEqual(self.open_fd_count(), before_fds)

    def test_create_bytes_pair_restoration_conflict_preserves_quarantine(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            first = root / "context-baseline.json"
            second = root / "context-baseline.sha256"
            real_open = evidence_json_module.os.open
            real_link = evidence_json_module.os.link
            create_calls = 0

            def failing_second_open(
                path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
                flags: int,
                mode: int = 0o777,
                *,
                dir_fd: int | None = None,
            ) -> int:
                nonlocal create_calls
                if flags & os.O_CREAT:
                    create_calls += 1
                    if create_calls == 2:
                        first.unlink()
                        first.write_bytes(b"replacement\n")
                        raise PermissionError("simulated second create failure")
                return real_open(path, flags, mode, dir_fd=dir_fd)

            def conflicting_link(
                src: str | bytes | os.PathLike[str] | os.PathLike[bytes],
                dst: str | bytes | os.PathLike[str] | os.PathLike[bytes],
                *,
                src_dir_fd: int | None = None,
                dst_dir_fd: int | None = None,
                follow_symlinks: bool = True,
            ) -> None:
                if dst == first.name and dst_dir_fd is not None:
                    first.write_bytes(b"conflict\n")
                real_link(
                    src,
                    dst,
                    src_dir_fd=src_dir_fd,
                    dst_dir_fd=dst_dir_fd,
                    follow_symlinks=follow_symlinks,
                )

            with mock.patch.object(evidence_json_module.os, "open", side_effect=failing_second_open):
                with mock.patch.object(evidence_json_module.os, "link", side_effect=conflicting_link):
                    with self.assertRaisesRegex(ContractError, "quarantine"):
                        create_bytes_pair((first, b"original\n"), (second, b"digest\n"))

            quarantines = sorted(root.glob(".__agent-brain-quarantine-*"))
            self.assertEqual(first.read_bytes(), b"conflict\n")
            self.assertEqual(len(quarantines), 1)
            self.assertEqual(quarantines[0].read_bytes(), b"replacement\n")
            self.assertFalse(second.exists())

    def test_freeze_context_preflights_output_pair_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            evidence = Path(raw).resolve() / "evidence"
            evidence.mkdir()
            source = ROOT / "tests" / "fixtures" / "model-context-baseline.json"
            source_digest = ROOT / "tests" / "fixtures" / "model-context-baseline.sha256"
            occupied_context = evidence / "occupied-context.json"
            occupied_digest = evidence / "occupied-context.sha256"
            occupied_context.write_text("already here\n", encoding="utf-8")
            digest_blocking_context = evidence / "digest-blocked-context.json"
            occupied_digest.write_text("already here\n", encoding="utf-8")
            digest_blocked_digest = evidence / "occupied-context.sha256"
            real_parent = evidence / "real-parent"
            real_parent.mkdir()
            parent_link = evidence / "parent-link"
            parent_link.symlink_to(real_parent, target_is_directory=True)

            occupied_context_attempt = run_cli(
                "freeze-context",
                "--source",
                str(source),
                "--digest",
                str(source_digest),
                "--output",
                str(occupied_context),
                "--output-digest",
                str(evidence / "new-context.sha256"),
            )
            occupied_digest_attempt = run_cli(
                "freeze-context",
                "--source",
                str(source),
                "--digest",
                str(source_digest),
                "--output",
                str(digest_blocking_context),
                "--output-digest",
                str(digest_blocked_digest),
            )
            parent_symlink_attempt = run_cli(
                "freeze-context",
                "--source",
                str(source),
                "--digest",
                str(source_digest),
                "--output",
                str(parent_link / "context-baseline.json"),
                "--output-digest",
                str(evidence / "parent-link.sha256"),
            )
            digest_parent_symlink_attempt = run_cli(
                "freeze-context",
                "--source",
                str(source),
                "--digest",
                str(source_digest),
                "--output",
                str(evidence / "parent-link-context.json"),
                "--output-digest",
                str(parent_link / "context-baseline.sha256"),
            )

            self.assertEqual(occupied_context_attempt.returncode, 2)
            self.assertEqual(occupied_digest_attempt.returncode, 2)
            self.assertEqual(parent_symlink_attempt.returncode, 2)
            self.assertEqual(digest_parent_symlink_attempt.returncode, 2)
            self.assertEqual(occupied_context.read_text(encoding="utf-8"), "already here\n")
            self.assertFalse((evidence / "new-context.sha256").exists())
            self.assertFalse(digest_blocking_context.exists())
            self.assertEqual(occupied_digest.read_text(encoding="utf-8"), "already here\n")
            self.assertFalse((real_parent / "context-baseline.json").exists())
            self.assertFalse((real_parent / "context-baseline.sha256").exists())
            self.assertFalse((evidence / "parent-link.sha256").exists())
            self.assertFalse((evidence / "parent-link-context.json").exists())

    def test_freeze_context_removes_only_created_output_when_digest_create_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            evidence = Path(raw).resolve() / "evidence"
            blocked = Path(raw).resolve() / "blocked"
            evidence.mkdir()
            blocked.mkdir()
            source = ROOT / "tests" / "fixtures" / "model-context-baseline.json"
            source_digest = ROOT / "tests" / "fixtures" / "model-context-baseline.sha256"
            output = evidence / "context-baseline.json"
            output_digest = blocked / "context-baseline.sha256"
            blocked.chmod(0o500)
            try:
                failed = run_cli(
                    "freeze-context",
                    "--source",
                    str(source),
                    "--digest",
                    str(source_digest),
                    "--output",
                    str(output),
                    "--output-digest",
                    str(output_digest),
                )
            finally:
                blocked.chmod(0o700)
            orphan_after_failed_create = output.exists()
            retry = run_cli(
                "freeze-context",
                "--source",
                str(source),
                "--digest",
                str(source_digest),
                "--output",
                str(output),
                "--output-digest",
                str(output_digest),
            )

            self.assertEqual(failed.returncode, 2)
            self.assertFalse(orphan_after_failed_create)
            self.assertEqual(retry.returncode, 0, retry.stderr.decode("utf-8", "replace"))
            self.assertEqual(output.read_bytes(), source.read_bytes())
            self.assertEqual(output_digest.read_text("ascii"), source_digest.read_text("ascii"))

    def test_exact_todo5_freeze_context_run_todo_records_canonical_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve() / "impl"
            evidence = Path(raw).resolve() / "evidence"
            evidence.mkdir()
            command = self.canonical_todo5_freeze_context_command()
            self.write_impl_root(root, ["python3 -c 'print(1)'", command], todo=5)
            self.write_context_fixture(root)
            (root / "tests" / "support").symlink_to(ROOT / "tests" / "support", target_is_directory=True)
            expected_digest = (root / "tests" / "fixtures" / "model-context-baseline.sha256").read_text("ascii").strip()

            first = self.run_todo(root=root, evidence=evidence, todo=5, step=1, argv=["python3", "-c", "print(1)"])
            argv = [
                "python3",
                "tests/support/evidence_contract.py",
                "freeze-context",
                "--source",
                "tests/fixtures/model-context-baseline.json",
                "--digest",
                "tests/fixtures/model-context-baseline.sha256",
                "--output",
                str(evidence / "context-baseline.json"),
                "--output-digest",
                str(evidence / "context-baseline.sha256"),
            ]
            second = self.run_todo(root=root, evidence=evidence, todo=5, step=2, argv=argv)
            self.assertEqual(first.returncode, 0)
            self.assertEqual(second.returncode, 0, second.stderr.decode("utf-8", "replace"))
            duplicate = self.run_todo(root=root, evidence=evidence, todo=5, step=2, argv=argv)
            record = canonical(evidence / "task-5-runs" / "2.json")
            output_bytes = (evidence / "context-baseline.json").read_bytes()
            digest_bytes = (evidence / "context-baseline.sha256").read_bytes()

        self.assertEqual(duplicate.returncode, 2)
        self.assertEqual(output_bytes, (ROOT / "tests" / "fixtures" / "model-context-baseline.json").read_bytes())
        self.assertEqual(hashlib.sha256(output_bytes).hexdigest(), expected_digest)
        self.assertEqual(digest_bytes, (expected_digest + "\n").encode("ascii"))
        self.assertEqual(record["manifest_command"], command)
        self.assertEqual(record["canonical_argv"], argv)
        self.assertEqual(record["exit_status"], 0)

    def test_expanded_evidence_root_argv_matches_manifest_literal_and_records_wrapper_proof(self) -> None:
        with tempfile.TemporaryDirectory(prefix="run todo unicode \u2603 ") as raw:
            base = Path(raw).resolve()
            root = base / "impl"
            evidence = base / "evidence root \u2603"
            evidence.mkdir()
            script = "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text('ok\\n')"
            manifest_command = f"python3 -c {shlex.quote(script)} \"$EVIDENCE_ROOT/out file \u2603.txt\""
            self.write_impl_root(root, [manifest_command])

            result = self.run_todo(
                root=root,
                evidence=evidence,
                step=1,
                argv=["python3", "-c", script, str(evidence.resolve() / "out file \u2603.txt")],
            )
            record = canonical(evidence / "task-5-runs" / "1.json")

        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        self.assertEqual(result.stdout, b"")
        self.assertEqual(record["manifest_command"], manifest_command)
        self.assertEqual(record["canonical_argv"], ["python3", "-c", script, str(evidence.resolve() / "out file \u2603.txt")])
        self.assertEqual(record["canonical_command"], shlex.join(["python3", "-c", script, str(evidence.resolve() / "out file \u2603.txt")]))
        self.assertEqual(record["environment_bindings"], {"EVIDENCE_ROOT": str(evidence.resolve())})
        self.assertEqual(record["ordinal"], 1)
        self.assertEqual(record["run_todo_wrapper"], "agent-brain-run-todo/v1")
        self.assertEqual(record["stdout_sha256"], hashlib.sha256(b"").hexdigest())
        self.assertEqual(record["stderr_sha256"], hashlib.sha256(b"").hexdigest())
        self.assertEqual(record["status_sha256"], hashlib.sha256(b"0\n").hexdigest())

    def test_rejects_unknown_home_command_substitution_backticks_and_wrong_root_before_execution(self) -> None:
        cases = {
            "home": 'python3 -c "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text(\'bad\')" "$HOME/out.txt"',
            "lower_unknown": 'python3 -c "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text(\'bad\')" "$missing/out.txt"',
            "unknown": 'python3 -c "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text(\'bad\')" "$MISSING/out.txt"',
            "substitution": 'python3 -c "print(1)" "$(pwd)/out.txt"',
            "backticks": 'python3 -c "print(1)" "`pwd`/out.txt"',
        }
        for name, manifest_command in cases.items():
            with self.subTest(name=name):
                with tempfile.TemporaryDirectory() as raw:
                    base = Path(raw).resolve()
                    root = base / "impl"
                    evidence = base / "evidence"
                    evidence.mkdir()
                    self.write_impl_root(root, [manifest_command])

                    result = self.run_todo(
                        root=root,
                        evidence=evidence,
                        step=1,
                        argv=["python3", "-c", "print(1)", str(evidence / "out.txt")],
                    )

                    self.assertEqual(result.returncode, 2)
                    self.assertEqual(result.stdout, b"")
                    self.assertFalse((evidence / "out.txt").exists())
                    self.assertFalse((evidence / "task-5-runs").exists())
                    self.assertNotEqual(result.stderr, b"")

        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw).resolve()
            root = base / "impl"
            evidence = base / "evidence"
            wrong = base / "wrong"
            evidence.mkdir()
            wrong.mkdir()
            script = "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text('bad\\n')"
            self.write_impl_root(root, [f"python3 -c {shlex.quote(script)} \"$EVIDENCE_ROOT/out.txt\""])

            result = self.run_todo(
                root=root,
                evidence=evidence,
                step=1,
                argv=["python3", "-c", script, str(wrong / "out.txt")],
            )

            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, b"")
            self.assertFalse((wrong / "out.txt").exists())

    def test_rejects_all_undeclared_dollar_forms_in_manifest_before_shell_execution(self) -> None:
        forms = [
            "$$",
            "$?",
            "$!",
            "$#",
            "$0",
            "$1",
            "$2",
            "$3",
            "$4",
            "$5",
            "$6",
            "$7",
            "$8",
            "$9",
            "$*",
            "$@",
            "$-",
            "${HOME}",
            "${var:-x}",
            "$(python3 -c 'print(1)')",
            "\\$HOME",
            "'$HOME'",
            '"$HOME"',
        ]
        for form in forms:
            with self.subTest(form=form):
                with tempfile.TemporaryDirectory() as raw:
                    base = Path(raw).resolve()
                    root = base / "impl"
                    evidence = base / "evidence"
                    evidence.mkdir()
                    marker = evidence / "marker.txt"
                    pid = evidence / "pid.txt"
                    command = f"python3 -c 'import pathlib,sys; pathlib.Path(sys.argv[1]).write_text(\"bad\")' {shlex.quote(str(marker))}; printf {shlex.quote(form)} > {shlex.quote(str(pid))}"
                    self.write_impl_root(root, [command], mode="shell")

                    result = self.run_todo(root=root, evidence=evidence, step=1, shell=command)

                    self.assertEqual(result.returncode, 2)
                    self.assertEqual(result.stdout, b"")
                    self.assertNotEqual(result.stderr, b"")
                    self.assertFalse(marker.exists())
                    self.assertFalse(pid.exists())
                    self.assertFalse((evidence / "task-5-runs").exists())

    def test_rejects_all_undeclared_dollar_forms_in_supplied_invocation_before_shell_execution(self) -> None:
        forms = [
            "$$",
            "$?",
            "$!",
            "$#",
            "$0",
            "$1",
            "$2",
            "$3",
            "$4",
            "$5",
            "$6",
            "$7",
            "$8",
            "$9",
            "$*",
            "$@",
            "$-",
            "${HOME}",
            "${var:-x}",
            "$(python3 -c 'print(1)')",
            "\\$HOME",
            "'$HOME'",
            '"$HOME"',
        ]
        for form in forms:
            with self.subTest(form=form):
                with tempfile.TemporaryDirectory() as raw:
                    base = Path(raw).resolve()
                    root = base / "impl"
                    evidence = base / "evidence"
                    evidence.mkdir()
                    marker = evidence / "marker.txt"
                    pid = evidence / "pid.txt"
                    clean = "python3 -c 'print(1)'"
                    supplied = f"python3 -c 'import pathlib,sys; pathlib.Path(sys.argv[1]).write_text(\"bad\")' {shlex.quote(str(marker))}; printf {shlex.quote(form)} > {shlex.quote(str(pid))}"
                    self.write_impl_root(root, [clean], mode="shell")

                    result = self.run_todo(root=root, evidence=evidence, step=1, shell=supplied)

                    self.assertEqual(result.returncode, 2)
                    self.assertEqual(result.stdout, b"")
                    self.assertNotEqual(result.stderr, b"")
                    self.assertFalse(marker.exists())
                    self.assertFalse(pid.exists())
                    self.assertFalse((evidence / "task-5-runs").exists())

    def test_braced_evidence_root_shell_step_rejects_extra_metacharacters(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw).resolve()
            root = base / "impl"
            evidence = base / "evidence"
            evidence.mkdir()
            expected = "python3 -c 'import pathlib,sys; pathlib.Path(sys.argv[1]).write_text(\"ok\\\\n\")' \"${EVIDENCE_ROOT}/shell out.txt\""
            self.write_impl_root(root, [expected], mode="shell")
            expanded = expected.replace("${EVIDENCE_ROOT}", str(evidence.resolve()))

            injected = self.run_todo(
                root=root,
                evidence=evidence,
                step=1,
                shell=f"{expanded}; python3 -c 'open(\"{evidence / 'evil'}\", \"w\").write(\"bad\")'",
            )
            accepted = self.run_todo(root=root, evidence=evidence, step=1, shell=expected)
            record = canonical(evidence / "task-5-runs" / "1.json")

        self.assertEqual(injected.returncode, 2)
        self.assertEqual(injected.stdout, b"")
        self.assertEqual(accepted.returncode, 0, accepted.stderr.decode("utf-8", "replace"))
        self.assertEqual(record["canonical_command"], expected)
        self.assertEqual(record["environment_bindings"], {"EVIDENCE_ROOT": str(evidence.resolve())})

    def test_exact_todo1_plan_review_placeholders_bind_execute_record_and_seal(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw).resolve()
            root = base / "impl"
            evidence = base / "evidence"
            evidence.mkdir()
            canonical_plan_review = self.canonical_plan_review_command()
            self.write_impl_root(root, ["python3 -c 'print(1)'", canonical_plan_review], todo=1)
            (root / "tests" / "support").symlink_to(ROOT / "tests" / "support", target_is_directory=True)
            env = self.write_review_fixture(root, evidence)
            first = self.run_todo(root=root, evidence=evidence, todo=1, step=1, argv=["python3", "-c", "print(1)"], env=env)
            plan_review_argv = [
                "python3",
                "tests/support/evidence_contract.py",
                "plan-review",
                "--plan",
                env["PLAN"],
                "--draft",
                env["DRAFT"],
                "--momus-receipt",
                f"{env['PLAN_REVIEW_ROOT']}/momus.txt",
                "--independent-receipt",
                f"{env['PLAN_REVIEW_ROOT']}/independent.txt",
                "--output",
                env["REVIEW_SEAL"],
            ]

            second = self.run_todo(root=root, evidence=evidence, todo=1, step=2, argv=plan_review_argv, env=env)
            source = evidence / "source.json"
            brain = evidence / "brain.json"
            log = evidence / "task.log"
            source.write_text("{}\n", encoding="utf-8")
            brain.write_text("{}\n", encoding="utf-8")
            log.write_text("task\n", encoding="utf-8")
            sealed = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(CLI),
                    "seal-todo",
                    "--todo",
                    "1",
                    "--plan",
                    str(self.plan_path(root)),
                    "--baseline-commit",
                    MODEL_BASELINE,
                    "--impl-root",
                    str(root),
                    "--source-baseline",
                    str(source),
                    "--brain-baseline",
                    str(brain),
                    "--runs",
                    str(evidence / "task-1-runs"),
                    "--task-log",
                    str(log),
                    "--output",
                    str(evidence / "receipt.json"),
                ],
                cwd=ROOT,
                env={**os.environ, **env},
                capture_output=True,
                check=False,
            )
            verified = run_cli("verify-todo", "--receipt", str(evidence / "receipt.json"), "--evidence-root", str(evidence))
            self.assertEqual(first.returncode, 0, first.stderr.decode("utf-8", "replace"))
            self.assertEqual(second.returncode, 0, second.stderr.decode("utf-8", "replace"))
            self.assertEqual(sealed.returncode, 0, sealed.stderr.decode("utf-8", "replace"))
            self.assertEqual(verified.returncode, 0, verified.stderr.decode("utf-8", "replace"))
            seal_exists = Path(env["REVIEW_SEAL"]).is_file()
            record = canonical(evidence / "task-1-runs" / "2.json")

        self.assertTrue(seal_exists)
        self.assertEqual(record["manifest_command"], canonical_plan_review)
        self.assertEqual(set(record["environment_bindings"]), {
            "BRAIN_ROOT",
            "DRAFT",
            "EVIDENCE_ROOT",
            "IMPL_ROOT",
            "PLAN",
            "PLAN_REVIEW_ROOT",
            "REVIEW_SEAL",
        })
        self.assertEqual(record["environment_bindings"]["PLAN"], env["PLAN"])
        self.assertEqual(record["environment_bindings"]["DRAFT"], env["DRAFT"])
        self.assertEqual(record["environment_bindings"]["PLAN_REVIEW_ROOT"], env["PLAN_REVIEW_ROOT"])
        self.assertEqual(record["environment_bindings"]["REVIEW_SEAL"], env["REVIEW_SEAL"])
        self.assertEqual(
            record["environment_binding_records"],
            [
                {
                    "name": name,
                    "path": record["environment_bindings"][name],
                    "role": role,
                    "root": root_name,
                    "sha256": hashlib.sha256(record["environment_bindings"][name].encode("utf-8")).hexdigest(),
                }
                for name, root_name, role in (
                    ("EVIDENCE_ROOT", "evidence", "evidence-root"),
                    ("PLAN", "brain", "reviewed-plan"),
                    ("DRAFT", "brain", "review-draft"),
                    ("PLAN_REVIEW_ROOT", "evidence", "plan-review-root"),
                    ("REVIEW_SEAL", "evidence", "plan-review-seal"),
                    ("BRAIN_ROOT", "brain", "brain-root"),
                    ("IMPL_ROOT", "implementation", "implementation-root"),
                )
            ],
        )
        self.assertEqual(record["canonical_argv"], plan_review_argv)

    def test_todo1_source_capture_step_seals_without_absent_impl_root_binding(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw).resolve()
            root = base / "impl"
            source = base / "source"
            evidence = base / "evidence"
            source.mkdir()
            evidence.mkdir()
            init_git(source)
            command = self.canonical_todo1_source_capture_command()
            self.write_impl_root(root, ["python3 -c 'print(1)'", "python3 -c 'print(2)'", command], todo=1)
            (root / "tests" / "support").symlink_to(ROOT / "tests" / "support", target_is_directory=True)
            (source / "tracked.txt").write_text("source\n", encoding="utf-8")
            env = {"SOURCE_ROOT": str(source.resolve())}
            argv = [
                "python3",
                "tests/support/evidence_contract.py",
                "capture-state",
                "--kind",
                "source",
                "--root",
                str(source.resolve()),
                "--output",
                str(evidence.resolve() / "source-preflight.json"),
                "--sidecar-dir",
                str(evidence.resolve() / "source-preflight-sidecars"),
            ]

            first = self.run_todo(root=root, evidence=evidence, todo=1, step=1, argv=["python3", "-c", "print(1)"], env=env)
            second = self.run_todo(root=root, evidence=evidence, todo=1, step=2, argv=["python3", "-c", "print(2)"], env=env)
            third = self.run_todo(root=root, evidence=evidence, todo=1, step=3, argv=argv, env=env)
            sealed = self.seal_todo(root=root, evidence=evidence, todo=1)
            verified = run_cli("verify-todo", "--receipt", str(evidence / "receipt.json"), "--evidence-root", str(evidence))

            self.assertEqual(first.returncode, 0)
            self.assertEqual(second.returncode, 0)
            self.assertEqual(third.returncode, 0, third.stderr.decode("utf-8", "replace"))
            self.assertEqual(sealed.returncode, 0, sealed.stderr.decode("utf-8", "replace"))
            self.assertEqual(verified.returncode, 0, verified.stderr.decode("utf-8", "replace"))
            record = canonical(evidence / "task-1-runs" / "3.json")
            self.assertEqual(record["manifest_command"], command)
            self.assertEqual(set(record["environment_bindings"]), {"EVIDENCE_ROOT", "SOURCE_ROOT"})
            self.assertNotIn("IMPL_ROOT", record["environment_bindings"])
            self.assertEqual(record["canonical_argv"], argv)

    def test_verify_todo_replay_accepts_subset_bindings_for_argv_and_shell(self) -> None:
        script = (
            "import pathlib,sys; "
            "pathlib.Path(sys.argv[2]).write_text(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8'), "
            "encoding='utf-8')"
        )
        cases = (
            (
                "argv",
                f"python3 -c {shlex.quote(script)} \"$SOURCE_ROOT/input.txt\" \"$EVIDENCE_ROOT/copied.txt\"",
                None,
            ),
            (
                "shell",
                f"python3 -c {shlex.quote(script)} \"$SOURCE_ROOT/input.txt\" \"$EVIDENCE_ROOT/copied.txt\"",
                "shell",
            ),
        )
        for name, command, mode in cases:
            with self.subTest(name=name):
                with tempfile.TemporaryDirectory() as raw:
                    base = Path(raw).resolve()
                    root = base / "impl"
                    source = base / "source"
                    evidence = base / "evidence"
                    source.mkdir()
                    evidence.mkdir()
                    (source / "input.txt").write_text(f"{name}\n", encoding="utf-8")
                    self.write_impl_root(root, [command], mode=mode or "argv")
                    env = {"SOURCE_ROOT": str(source.resolve())}
                    argv = [
                        "python3",
                        "-c",
                        script,
                        str(source.resolve() / "input.txt"),
                        str(evidence.resolve() / "copied.txt"),
                    ]
                    run = self.run_todo(
                        root=root,
                        evidence=evidence,
                        step=1,
                        argv=argv if mode is None else None,
                        shell=command if mode == "shell" else None,
                        env=env,
                    )
                    sealed = self.seal_todo(root=root, evidence=evidence)
                    verified = run_cli("verify-todo", "--receipt", str(evidence / "receipt.json"), "--evidence-root", str(evidence))
                    self.assertEqual(run.returncode, 0, run.stderr.decode("utf-8", "replace"))
                    self.assertEqual(sealed.returncode, 0, sealed.stderr.decode("utf-8", "replace"))
                    self.assertEqual(verified.returncode, 0, verified.stderr.decode("utf-8", "replace"))
                    receipt = canonical(evidence / "receipt.json")
                    run_record = canonical(evidence / "task-5-runs" / "1.json")
                    extra_run = dict(run_record)
                    extra_bindings = dict(run_record["environment_bindings"])
                    extra_bindings["IMPL_ROOT"] = str(root.resolve())
                    extra_run["environment_bindings"] = extra_bindings
                    extra_run["environment_binding_sha256"] = hashlib.sha256(canonical_bytes(extra_bindings)).hexdigest()
                    extra_records = list(run_record["environment_binding_records"])
                    extra_records.append(
                        {
                            "name": "IMPL_ROOT",
                            "path": str(root.resolve()),
                            "role": "implementation-root",
                            "root": "implementation",
                            "sha256": hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest(),
                        }
                    )
                    extra_run["environment_binding_records"] = extra_records
                    extra_run_path = evidence / "task-5-runs" / f"1-{name}-extra.json"
                    self.write_canonical_json(extra_run_path, extra_run)
                    extra_receipt = dict(receipt)
                    extra_receipt["runs"] = [file_record("evidence", evidence, extra_run_path)]
                    extra_receipt_path = evidence / f"{name}-extra-receipt.json"
                    self.write_canonical_json(extra_receipt_path, extra_receipt)
                    extra_verified = run_cli(
                        "verify-todo",
                        "--receipt",
                        str(extra_receipt_path),
                        "--evidence-root",
                        str(evidence),
                    )
                    missing_run = dict(run_record)
                    missing_bindings = dict(run_record["environment_bindings"])
                    missing_bindings.pop("SOURCE_ROOT")
                    missing_run["environment_bindings"] = missing_bindings
                    missing_run["environment_binding_sha256"] = hashlib.sha256(canonical_bytes(missing_bindings)).hexdigest()
                    missing_run["environment_binding_records"] = [
                        item
                        for item in run_record["environment_binding_records"]
                        if isinstance(item, dict) and item.get("name") != "SOURCE_ROOT"
                    ]
                    missing_run_path = evidence / "task-5-runs" / f"1-{name}-missing.json"
                    self.write_canonical_json(missing_run_path, missing_run)
                    missing_receipt = dict(receipt)
                    missing_receipt["runs"] = [file_record("evidence", evidence, missing_run_path)]
                    missing_receipt_path = evidence / f"{name}-missing-receipt.json"
                    self.write_canonical_json(missing_receipt_path, missing_receipt)
                    missing_verified = run_cli(
                        "verify-todo",
                        "--receipt",
                        str(missing_receipt_path),
                        "--evidence-root",
                        str(evidence),
                    )

                    self.assertEqual((evidence / "copied.txt").read_text(encoding="utf-8"), f"{name}\n")
                    self.assertEqual(set(run_record["environment_bindings"]), {"EVIDENCE_ROOT", "SOURCE_ROOT"})
                    self.assertEqual(extra_verified.returncode, 2)
                    self.assertEqual(missing_verified.returncode, 2)

    def test_exact_todo1_plan_review_may_bind_reviewed_brain_plan_with_active_plan_hash(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve() / "impl"
            brain = Path(raw).resolve() / "brain"
            evidence = Path(raw).resolve() / "evidence"
            brain.mkdir()
            evidence.mkdir()
            canonical_plan_review = self.canonical_plan_review_command()
            self.write_impl_root(root, ["python3 -c 'print(1)'", canonical_plan_review], todo=1)
            (root / "tests" / "support").symlink_to(ROOT / "tests" / "support", target_is_directory=True)
            env = self.write_brain_review_fixture(root, evidence, brain)
            active_sha = hashlib.sha256(self.plan_path(root).read_bytes()).hexdigest()
            reviewed_sha = hashlib.sha256(Path(env["PLAN"]).read_bytes()).hexdigest()
            first = self.run_todo(root=root, evidence=evidence, todo=1, step=1, argv=["python3", "-c", "print(1)"], env=env)
            argv = [
                "python3",
                "tests/support/evidence_contract.py",
                "plan-review",
                "--plan",
                env["PLAN"],
                "--draft",
                env["DRAFT"],
                "--momus-receipt",
                f"{env['PLAN_REVIEW_ROOT']}/momus.txt",
                "--independent-receipt",
                f"{env['PLAN_REVIEW_ROOT']}/independent.txt",
                "--output",
                env["REVIEW_SEAL"],
            ]
            second = self.run_todo(root=root, evidence=evidence, todo=1, step=2, argv=argv, env=env)
            sealed = self.seal_todo(root=root, evidence=evidence, todo=1, env=env)
            verified = run_cli("verify-todo", "--receipt", str(evidence / "receipt.json"), "--evidence-root", str(evidence))
            record = canonical(evidence / "task-1-runs" / "2.json")
            seal = canonical(Path(env["REVIEW_SEAL"]))

        self.assertNotEqual(active_sha, reviewed_sha)
        self.assertEqual(first.returncode, 0)
        self.assertEqual(second.returncode, 0, second.stderr.decode("utf-8", "replace"))
        self.assertEqual(sealed.returncode, 0, sealed.stderr.decode("utf-8", "replace"))
        self.assertEqual(verified.returncode, 0, verified.stderr.decode("utf-8", "replace"))
        self.assertEqual(record["plan_sha256"], active_sha)
        self.assertEqual(record["environment_bindings"]["PLAN"], env["PLAN"])
        self.assertEqual(seal["plan_sha256"], reviewed_sha)
        self.assertIn(
            {
                "name": "PLAN",
                "path": env["PLAN"],
                "role": "reviewed-plan",
                "root": "brain",
                "sha256": hashlib.sha256(env["PLAN"].encode("utf-8")).hexdigest(),
            },
            record["environment_binding_records"],
        )

    def test_verify_todo_rejects_reviewed_plan_binding_role_and_seal_tamper(self) -> None:
        for tamper in ("binding_role", "binding_root", "review_seal_plan"):
            with self.subTest(tamper=tamper):
                with tempfile.TemporaryDirectory() as raw:
                    root = Path(raw).resolve() / "impl"
                    brain = Path(raw).resolve() / "brain"
                    evidence = Path(raw).resolve() / "evidence"
                    brain.mkdir()
                    evidence.mkdir()
                    canonical_plan_review = self.canonical_plan_review_command()
                    self.write_impl_root(root, ["python3 -c 'print(1)'", canonical_plan_review], todo=1)
                    (root / "tests" / "support").symlink_to(ROOT / "tests" / "support", target_is_directory=True)
                    env = self.write_brain_review_fixture(root, evidence, brain)
                    active_sha = hashlib.sha256(self.plan_path(root).read_bytes()).hexdigest()
                    first = self.run_todo(root=root, evidence=evidence, todo=1, step=1, argv=["python3", "-c", "print(1)"], env=env)
                    second = self.run_todo(
                        root=root,
                        evidence=evidence,
                        todo=1,
                        step=2,
                        argv=[
                            "python3",
                            "tests/support/evidence_contract.py",
                            "plan-review",
                            "--plan",
                            env["PLAN"],
                            "--draft",
                            env["DRAFT"],
                            "--momus-receipt",
                            f"{env['PLAN_REVIEW_ROOT']}/momus.txt",
                            "--independent-receipt",
                            f"{env['PLAN_REVIEW_ROOT']}/independent.txt",
                            "--output",
                            env["REVIEW_SEAL"],
                        ],
                        env=env,
                    )
                    sealed = self.seal_todo(root=root, evidence=evidence, todo=1, env=env)
                    receipt = canonical(evidence / "receipt.json")
                    tampered_receipt_path = evidence / f"{tamper}-receipt.json"
                    if tamper in {"binding_role", "binding_root"}:
                        tampered_run = canonical(evidence / "task-1-runs" / "2.json")
                        for item in tampered_run["environment_binding_records"]:
                            if item["name"] == "PLAN":
                                item["role"] = "active-plan" if tamper == "binding_role" else item["role"]
                                item["root"] = "implementation" if tamper == "binding_root" else item["root"]
                        tampered_run_path = evidence / "task-1-runs" / f"2-{tamper}.json"
                        tampered_run_path.write_text(
                            json.dumps(tampered_run, sort_keys=True, separators=(",", ":")) + "\n",
                            encoding="utf-8",
                        )
                        runs = list(receipt["runs"])
                        runs[1] = file_record("evidence", evidence, tampered_run_path)
                        receipt["runs"] = runs
                    else:
                        seal = canonical(Path(env["REVIEW_SEAL"]))
                        seal["plan_sha256"] = active_sha
                        Path(env["REVIEW_SEAL"]).write_text(
                            json.dumps(seal, sort_keys=True, separators=(",", ":")) + "\n",
                            encoding="utf-8",
                        )
                    tampered_receipt_path.write_text(
                        json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n",
                        encoding="utf-8",
                    )
                    verified = run_cli("verify-todo", "--receipt", str(tampered_receipt_path), "--evidence-root", str(evidence))

                self.assertEqual(first.returncode, 0)
                self.assertEqual(second.returncode, 0, second.stderr.decode("utf-8", "replace"))
                self.assertEqual(sealed.returncode, 0, sealed.stderr.decode("utf-8", "replace"))
                self.assertEqual(verified.returncode, 2)

    def test_expanded_argv_path_metacharacters_are_opaque_values(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve() / "impl"
            evidence = Path(raw).resolve() / "evidence"
            source = Path(raw).resolve() / "source $(touch should-not-exist) ${NOPE} `tick`; semi \\ slash 'quote"
            evidence.mkdir()
            source.mkdir()
            marker = evidence / "evaluated.txt"
            script = (
                "import pathlib,sys; "
                "pathlib.Path(sys.argv[1], 'ok.txt').write_text('ok\\n'); "
                f"pathlib.Path({str(marker)!r}).write_text('argv-only\\n')"
            )
            command = f"python3 -c {shlex.quote(script)} \"$SOURCE_ROOT\""
            self.write_impl_root(root, [command])

            result = self.run_todo(
                root=root,
                evidence=evidence,
                step=1,
                argv=["python3", "-c", script, str(source)],
                env={"SOURCE_ROOT": str(source)},
            )
            record = canonical(evidence / "task-5-runs" / "1.json")
            source_ok = (source / "ok.txt").read_text(encoding="utf-8")
            marker_text = marker.read_text(encoding="utf-8")
            evaluated_exists = (evidence / "should-not-exist").exists()

        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        self.assertEqual(source_ok, "ok\n")
        self.assertEqual(marker_text, "argv-only\n")
        self.assertFalse(evaluated_exists)
        self.assertEqual(record["canonical_argv"][-1], str(source))

    def test_shell_bindings_with_metacharacters_are_opaque_controlled_env_values(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw).resolve()
            root = base / 'impl $(touch should-not-run) ${NOPE} `touch backtick-ran`; semi \\ slash "double" quote'
            evidence = base / 'evidence $(touch should-not-run) ${NOPE} `touch backtick-ran`; semi \\ slash "double" quote'
            source = base / "source $(touch should-not-run) ${NOPE} `touch backtick-ran`; semi \\ slash 'single' quote"
            brain = base / "brain $(touch should-not-run) ${NOPE} `touch backtick-ran`; semi \\ slash 'single' quote"
            evidence.mkdir()
            source.mkdir()
            brain.mkdir()
            plan_review = evidence / "plan review $(touch should-not-run) ${NOPE}; semi"
            plan_review.mkdir()
            draft = brain / ".omo" / "drafts" / "draft $(touch should-not-run) ${NOPE}.md"
            draft.parent.mkdir(parents=True)
            draft.write_text("draft\n", encoding="utf-8")
            review_seal = plan_review / 'seal $(touch should-not-run) ${NOPE}; "quote".json'
            script = (
                "import json,os,pathlib,sys; "
                "pathlib.Path(sys.argv[1], 'observed.json').write_text("
                "json.dumps({'argv': sys.argv[1:], 'leaked': os.environ.get('UNRELATED_SHOULD_NOT_LEAK', '')}, "
                "sort_keys=True) + '\\n')"
            )
            command = (
                f"python3 -c {shlex.quote(script)} "
                '"$EVIDENCE_ROOT" "$SOURCE_ROOT" "$BRAIN_ROOT" "$PLAN" "$DRAFT" '
                '"$PLAN_REVIEW_ROOT" "$REVIEW_SEAL" "$IMPL_ROOT"'
            )
            self.write_impl_root(root, [command], mode="shell")
            env = {
                "BRAIN_ROOT": str(brain),
                "DRAFT": str(draft),
                "PLAN": str(self.plan_path(root)),
                "PLAN_REVIEW_ROOT": str(plan_review),
                "REVIEW_SEAL": str(review_seal),
                "SOURCE_ROOT": str(source),
                "UNRELATED_SHOULD_NOT_LEAK": "leaked",
            }

            result = self.run_todo(root=root, evidence=evidence, step=1, shell=command, env=env)
            observed = json.loads((evidence / "observed.json").read_text(encoding="utf-8"))
            record = canonical(evidence / "task-5-runs" / "1.json")
            should_not_run_exists = (root / "should-not-run").exists()
            backtick_ran_exists = (root / "backtick-ran").exists()

        expected_values = [
            str(evidence.resolve()),
            str(source.resolve()),
            str(brain.resolve()),
            str(self.plan_path(root).resolve()),
            str(draft.resolve()),
            str(plan_review.resolve()),
            str(review_seal.resolve(strict=False)),
            str(root.resolve()),
        ]
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        self.assertEqual(observed["argv"], expected_values)
        self.assertEqual(observed["leaked"], "")
        self.assertFalse(should_not_run_exists)
        self.assertFalse(backtick_ran_exists)
        self.assertEqual(record["manifest_command"], command)
        self.assertEqual(record["canonical_command"], command)
        self.assertEqual(
            record["environment_bindings"],
            {
                "BRAIN_ROOT": str(brain.resolve()),
                "DRAFT": str(draft.resolve()),
                "EVIDENCE_ROOT": str(evidence.resolve()),
                "IMPL_ROOT": str(root.resolve()),
                "PLAN": str(self.plan_path(root).resolve()),
                "PLAN_REVIEW_ROOT": str(plan_review.resolve()),
                "REVIEW_SEAL": str(review_seal.resolve(strict=False)),
                "SOURCE_ROOT": str(source.resolve()),
            },
        )

    def test_shell_missing_binding_rejects_before_execution_without_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve() / "impl"
            evidence = Path(raw).resolve() / "evidence"
            evidence.mkdir()
            command = "python3 -c 'import pathlib,sys; pathlib.Path(sys.argv[1]).write_text(\"bad\")' \"$SOURCE_ROOT/out.txt\""
            self.write_impl_root(root, [command], mode="shell")

            result = self.run_todo(root=root, evidence=evidence, step=1, shell=command)

            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, b"")
            self.assertFalse((evidence / "task-5-runs").exists())

    def test_exact_todo4_shell_local_status_executes_without_inherited_status(self) -> None:
        command = self.canonical_todo4_stale_scan_command()
        for name, matching_text in (("status_zero", "brain_setup.py\n"), ("status_one", "clean\n")):
            with self.subTest(name=name):
                with tempfile.TemporaryDirectory() as raw:
                    root = Path(raw).resolve() / "impl"
                    evidence = Path(raw).resolve() / (
                        'evidence $(touch should-not-run) ${NOPE}; semi \\ slash "quote"'
                    )
                    evidence.mkdir()
                    self.write_impl_root(root, ["python3 -c 'print(1)'", command], mode="shell", todo=4)
                    (root / "probe.txt").write_text(matching_text, encoding="utf-8")
                    first = self.run_todo(root=root, evidence=evidence, todo=4, step=1, shell="python3 -c 'print(1)'")
                    second = self.run_todo(
                        root=root,
                        evidence=evidence,
                        todo=4,
                        step=2,
                        shell=command,
                        env={"status": "99", "UNRELATED_SHOULD_NOT_LEAK": "leaked"},
                    )
                    record = canonical(evidence / "task-4-runs" / "2.json")
                    output = (evidence / "task-4-stale-scan.txt").read_text(encoding="utf-8")
                    should_not_run_exists = (root / "should-not-run").exists()

                self.assertEqual(first.returncode, 0)
                self.assertEqual(second.returncode, 0, second.stderr.decode("utf-8", "replace"))
                self.assertEqual(record["command"], command)
                self.assertEqual(record["canonical_command"], command)
                self.assertEqual(record["manifest_command"], command)
                self.assertEqual(record["environment_bindings"], {"EVIDENCE_ROOT": str(evidence.resolve())})
                self.assertEqual("brain_setup.py" in output, name == "status_zero")
                self.assertFalse(should_not_run_exists)

    def test_modified_shell_special_and_local_forms_are_rejected_before_execution(self) -> None:
        cases = [
            ("status_at_start", 'test "$?" -le 1'),
            ("status_assignment_at_start", 'status=$?; test "$status" -le 1'),
            ("unassigned_parent_local", 'python3 -c "print(1)"; test "$status" -le 1'),
            ("braced_local", 'python3 -c "print(1)"; status=$?; test "${status}" -le 1'),
            ("noncanonical_local_name", 'python3 -c "print(1)"; other=$?; test "$other" -le 1'),
            ("other_unassigned_local", 'python3 -c "print(1)"; status=$?; test "$other" -le 1'),
        ]
        for name, command in cases:
            with self.subTest(name=name):
                with tempfile.TemporaryDirectory() as raw:
                    root = Path(raw).resolve() / "impl"
                    evidence = Path(raw).resolve() / "evidence"
                    evidence.mkdir()
                    self.write_impl_root(root, [command], mode="shell")

                    result = self.run_todo(
                        root=root,
                        evidence=evidence,
                        step=1,
                        shell=command,
                        env={"status": "0", "other": "0"},
                    )

                    self.assertEqual(result.returncode, 2)
                    self.assertEqual(result.stdout, b"")
                    self.assertFalse((evidence / "task-5-runs").exists())

    def test_declared_placeholder_security_matrix_rejects_before_execution(self) -> None:
        canonical_plan_review = (
            'python3 tests/support/evidence_contract.py plan-review --plan "$PLAN" '
            '--draft "$DRAFT" --momus-receipt "$PLAN_REVIEW_ROOT/momus.txt" '
            '--independent-receipt "$PLAN_REVIEW_ROOT/independent.txt" --output "$REVIEW_SEAL"'
        )
        cases = [
            ("missing_plan", lambda root, evidence, env: env.pop("PLAN")),
            ("impl_mismatch", lambda root, evidence, env: env.update({"IMPL_ROOT": str((root.parent / "other").resolve())})),
            ("plan_traversal", lambda root, evidence, env: env.update({"PLAN": str(root / ".omo" / "plans" / ".." / "escape.md")})),
            ("plan_wrong_root", lambda root, evidence, env: env.update({"PLAN": str((root.parent / "outside-plan.md").resolve())})),
            ("draft_wrong_brain_root", lambda root, evidence, env: env.update({"BRAIN_ROOT": str((root.parent / "other-brain").resolve())})),
            ("plan_review_wrong_root", lambda root, evidence, env: env.update({"PLAN_REVIEW_ROOT": str((root.parent / "outside-review").resolve())})),
            ("review_seal_wrong_root", lambda root, evidence, env: env.update({"REVIEW_SEAL": str((evidence / "review.json").resolve())})),
        ]
        for name, mutate in cases:
            with self.subTest(name=name):
                with tempfile.TemporaryDirectory() as raw:
                    base = Path(raw).resolve()
                    root = base / "impl"
                    evidence = base / "evidence"
                    evidence.mkdir()
                    self.write_impl_root(root, [canonical_plan_review])
                    env = self.write_review_fixture(root, evidence)
                    mutate(root, evidence, env)

                    result = self.run_todo(
                        root=root,
                        evidence=evidence,
                        step=1,
                        argv=["python3", "tests/support/evidence_contract.py", "plan-review"],
                        env=env,
                    )

                    self.assertEqual(result.returncode, 2)
                    self.assertEqual(result.stdout, b"")
                    self.assertNotEqual(result.stderr, b"")
                    self.assertFalse((evidence / "task-5-runs").exists())

        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw).resolve()
            root = base / "impl"
            evidence = base / "evidence"
            evidence.mkdir()
            self.write_impl_root(root, [canonical_plan_review])
            env = self.write_review_fixture(root, evidence)
            outside = base / "outside-plan.md"
            outside.write_text("outside\n", encoding="utf-8")
            Path(env["PLAN"]).unlink()
            Path(env["PLAN"]).symlink_to(outside)

            result = self.run_todo(
                root=root,
                evidence=evidence,
                step=1,
                argv=["python3", "tests/support/evidence_contract.py", "plan-review"],
                env=env,
            )

            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, b"")
            self.assertFalse((evidence / "task-5-runs").exists())

    def test_source_root_and_escaped_allowed_placeholder_are_rejected_before_execution(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw).resolve()
            root = base / "impl"
            evidence = base / "evidence"
            evidence.mkdir()
            marker = evidence / "marker.txt"
            command = f"python3 -c 'import pathlib; pathlib.Path({str(marker)!r}).write_text(\"bad\")' \\$EVIDENCE_ROOT"
            self.write_impl_root(root, [command], mode="shell")

            escaped = self.run_todo(root=root, evidence=evidence, step=1, shell=command)

            self.assertEqual(escaped.returncode, 2)
            self.assertFalse(marker.exists())
            self.assertFalse((evidence / "task-5-runs").exists())

        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw).resolve()
            root = base / "impl"
            evidence = base / "evidence"
            target = base / "source"
            source_link = base / "source-link"
            evidence.mkdir()
            target.mkdir()
            source_link.symlink_to(target, target_is_directory=True)
            command = 'python3 -c "print(1)" "$SOURCE_ROOT"'
            self.write_impl_root(root, [command])
            env = {
                "SOURCE_ROOT": str(source_link),
            }

            source_symlink = self.run_todo(
                root=root,
                evidence=evidence,
                step=1,
                argv=["python3", "-c", "print(1)", str(source_link)],
                env=env,
            )

            self.assertEqual(source_symlink.returncode, 2)
            self.assertFalse((evidence / "task-5-runs").exists())

    def test_declared_binding_intermediate_symlinks_reject_without_side_effects(self) -> None:
        script = "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text('bad\\n')"
        cases = [
            ("PLAN", f"python3 -c {shlex.quote(script)} \"$PLAN\""),
            ("DRAFT", f"python3 -c {shlex.quote(script)} \"$DRAFT\""),
            ("PLAN_REVIEW_ROOT", f"python3 -c {shlex.quote(script)} \"$PLAN_REVIEW_ROOT/out.txt\""),
            ("REVIEW_SEAL", f"python3 -c {shlex.quote(script)} \"$REVIEW_SEAL\""),
            ("SOURCE_ROOT", f"python3 -c {shlex.quote(script)} \"$SOURCE_ROOT/out.txt\""),
            ("BRAIN_ROOT", f"python3 -c {shlex.quote(script)} \"$BRAIN_ROOT/out.txt\""),
        ]
        for name, command in cases:
            with self.subTest(name=name):
                with tempfile.TemporaryDirectory() as raw:
                    base = Path(raw).resolve()
                    root = base / "impl"
                    evidence = base / "evidence"
                    evidence.mkdir()
                    self.write_impl_root(root, [command])
                    env = self.write_review_fixture(root, evidence)
                    outside = base / f"{name.lower()}-outside"
                    outside.mkdir()
                    marker = outside / "out.txt"
                    if name == "PLAN":
                        link = root / ".omo" / "plans-link"
                        link.symlink_to(root / ".omo" / "plans", target_is_directory=True)
                        env["PLAN"] = str(link / "agent-brain-operating-model.md")
                        actual_path = str(Path(env["PLAN"]).resolve(strict=False))
                    elif name == "DRAFT":
                        link = root / ".omo" / "drafts-link"
                        link.symlink_to(root / ".omo" / "drafts", target_is_directory=True)
                        env["DRAFT"] = str(link / "agent-brain-operating-model.md")
                        actual_path = str(Path(env["DRAFT"]).resolve(strict=False))
                    elif name == "PLAN_REVIEW_ROOT":
                        link = evidence / "plan-review-link"
                        link.symlink_to(evidence / "plan-review", target_is_directory=True)
                        env["PLAN_REVIEW_ROOT"] = str(link)
                        marker = evidence / "plan-review" / "out.txt"
                        actual_path = str((Path(env["PLAN_REVIEW_ROOT"]) / "out.txt").resolve(strict=False))
                    elif name == "REVIEW_SEAL":
                        link = evidence / "plan-review-link"
                        link.symlink_to(evidence / "plan-review", target_is_directory=True)
                        env["REVIEW_SEAL"] = str(link / "review.json")
                        marker = evidence / "plan-review" / "review.json"
                        actual_path = str(Path(env["REVIEW_SEAL"]).resolve(strict=False))
                    elif name == "SOURCE_ROOT":
                        child = outside / "child"
                        child.mkdir()
                        link = base / "source-link"
                        link.symlink_to(outside, target_is_directory=True)
                        env["SOURCE_ROOT"] = str(link / "child")
                        marker = child / "out.txt"
                        actual_path = str((Path(env["SOURCE_ROOT"]) / "out.txt").resolve(strict=False))
                    else:
                        child = outside / "child"
                        child.mkdir()
                        link = base / "brain-link"
                        link.symlink_to(outside, target_is_directory=True)
                        env["BRAIN_ROOT"] = str(link / "child")
                        marker = child / "out.txt"
                        actual_path = str((Path(env["BRAIN_ROOT"]) / "out.txt").resolve(strict=False))

                    actual = [
                        "python3",
                        "-c",
                        script,
                        actual_path,
                    ]
                    result = self.run_todo(root=root, evidence=evidence, step=1, argv=actual, env=env)

                    self.assertEqual(result.returncode, 2)
                    self.assertEqual(result.stdout, b"")
                    self.assertFalse(marker.exists())
                    self.assertFalse((evidence / "task-5-runs").exists())

    def test_verify_todo_rejects_regenerated_binding_record_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve() / "impl"
            evidence = Path(raw).resolve() / "evidence"
            evidence.mkdir()
            canonical_plan_review = (
                'python3 tests/support/evidence_contract.py plan-review --plan "$PLAN" '
                '--draft "$DRAFT" --momus-receipt "$PLAN_REVIEW_ROOT/momus.txt" '
                '--independent-receipt "$PLAN_REVIEW_ROOT/independent.txt" --output "$REVIEW_SEAL"'
            )
            self.write_impl_root(root, ["python3 -c 'print(1)'", canonical_plan_review], todo=1)
            (root / "tests" / "support").symlink_to(ROOT / "tests" / "support", target_is_directory=True)
            env = self.write_review_fixture(root, evidence)
            first = self.run_todo(root=root, evidence=evidence, todo=1, step=1, argv=["python3", "-c", "print(1)"], env=env)
            second = self.run_todo(
                root=root,
                evidence=evidence,
                todo=1,
                step=2,
                argv=[
                    "python3",
                    "tests/support/evidence_contract.py",
                    "plan-review",
                    "--plan",
                    env["PLAN"],
                    "--draft",
                    env["DRAFT"],
                    "--momus-receipt",
                    f"{env['PLAN_REVIEW_ROOT']}/momus.txt",
                    "--independent-receipt",
                    f"{env['PLAN_REVIEW_ROOT']}/independent.txt",
                    "--output",
                    env["REVIEW_SEAL"],
                ],
                env=env,
            )
            sealed = self.seal_todo(root=root, evidence=evidence, todo=1, env=env)
            receipt = canonical(evidence / "receipt.json")
            tampered_run = canonical(evidence / "task-1-runs" / "2.json")
            tampered_run["environment_binding_records"][0]["sha256"] = "0" * 64
            tampered_run_path = evidence / "task-1-runs" / "2-tampered.json"
            tampered_run_path.write_text(
                json.dumps(tampered_run, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            tampered_receipt = dict(receipt)
            runs = list(receipt["runs"])
            runs[1] = file_record("evidence", evidence, tampered_run_path)
            tampered_receipt["runs"] = runs
            tampered_receipt_path = evidence / "tampered-rebound-receipt.json"
            tampered_receipt_path.write_text(
                json.dumps(tampered_receipt, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )

            verified = run_cli("verify-todo", "--receipt", str(tampered_receipt_path), "--evidence-root", str(evidence))

        self.assertEqual(first.returncode, 0)
        self.assertEqual(second.returncode, 0, second.stderr.decode("utf-8", "replace"))
        self.assertEqual(sealed.returncode, 0, sealed.stderr.decode("utf-8", "replace"))
        self.assertEqual(verified.returncode, 2)
        self.assertIn(b"wrapper proof", verified.stderr)

    def test_verify_todo_rejects_active_plan_rebinding_against_immutable_snapshot(self) -> None:
        plan_path_b64 = base64.b64encode(b".omo/plans/agent-brain-operating-model.md").decode("ascii")
        cases = ("joint_rebound_plan_hashes", "missing_plan_blob", "duplicate_plan_path", "plan_path_swap", "different_valid_plan")
        for name in cases:
            with self.subTest(name=name):
                with tempfile.TemporaryDirectory() as raw:
                    root = Path(raw).resolve() / "impl"
                    evidence = Path(raw).resolve() / "evidence"
                    evidence.mkdir()
                    receipt, run_record = self.write_single_step_receipt(root, evidence)
                    manifest_path = evidence / "receipt.implementation-manifest.json"
                    archive_path = evidence / "receipt.implementation.tar"
                    manifest = canonical(manifest_path)
                    entries = list(manifest["entries"])
                    plan_entries = [
                        entry for entry in entries
                        if isinstance(entry, dict) and entry.get("path_b64") == plan_path_b64
                    ]
                    self.assertEqual(len(plan_entries), 1)
                    plan_entry = dict(plan_entries[0])
                    run_path = evidence / "task-5-runs" / f"1-{name}.json"
                    receipt_path = evidence / f"{name}-receipt.json"

                    if name == "joint_rebound_plan_hashes":
                        fake_plan_sha = hashlib.sha256(b"jointly rebound reviewed plan\n").hexdigest()
                        receipt["plan_sha256"] = fake_plan_sha
                        run_record["plan_sha256"] = fake_plan_sha
                    elif name == "missing_plan_blob":
                        blobs = self.archive_blobs(archive_path)
                        blobs.pop(str(plan_entry["sha256"]))
                        archive_path = evidence / "missing-plan.implementation.tar"
                        self.write_archive(archive_path, blobs)
                        receipt["implementation_archive"] = file_record("evidence", evidence, archive_path)
                    elif name == "duplicate_plan_path":
                        entries.append(dict(plan_entry))
                        manifest["entries"] = entries
                        manifest_path = evidence / "duplicate-plan.implementation-manifest.json"
                        self.write_canonical_json(manifest_path, manifest)
                        receipt["implementation_manifest"] = file_record("evidence", evidence, manifest_path)
                    elif name == "plan_path_swap":
                        for entry in entries:
                            if isinstance(entry, dict) and entry.get("path_b64") == plan_path_b64:
                                entry["path_b64"] = base64.b64encode(b".omo/plans/swapped-plan.md").decode("ascii")
                        manifest["entries"] = sorted(entries, key=lambda item: base64.b64decode(str(item["path_b64"])))
                        new_impl_sha = hashlib.sha256(canonical_bytes(manifest["entries"])).hexdigest()
                        manifest_path = evidence / "swapped-plan.implementation-manifest.json"
                        self.write_canonical_json(manifest_path, manifest)
                        receipt["implementation_manifest"] = file_record("evidence", evidence, manifest_path)
                        receipt["implementation_sha256"] = new_impl_sha
                        run_record["implementation_sha256"] = new_impl_sha
                    else:
                        replacement = b"# different valid active plan\n- [x] rebound\n"
                        replacement_sha = hashlib.sha256(replacement).hexdigest()
                        blobs = self.archive_blobs(archive_path)
                        blobs[replacement_sha] = replacement
                        for entry in entries:
                            if isinstance(entry, dict) and entry.get("path_b64") == plan_path_b64:
                                entry["sha256"] = replacement_sha
                                entry["size"] = len(replacement)
                        manifest["entries"] = entries
                        new_impl_sha = hashlib.sha256(canonical_bytes(manifest["entries"])).hexdigest()
                        manifest_path = evidence / "different-plan.implementation-manifest.json"
                        archive_path = evidence / "different-plan.implementation.tar"
                        self.write_canonical_json(manifest_path, manifest)
                        self.write_archive(archive_path, blobs)
                        receipt["implementation_manifest"] = file_record("evidence", evidence, manifest_path)
                        receipt["implementation_archive"] = file_record("evidence", evidence, archive_path)
                        receipt["implementation_sha256"] = new_impl_sha
                        run_record["implementation_sha256"] = new_impl_sha

                    self.write_canonical_json(run_path, run_record)
                    receipt["runs"] = [file_record("evidence", evidence, run_path)]
                    self.write_canonical_json(receipt_path, receipt)

                    verified = run_cli("verify-todo", "--receipt", str(receipt_path), "--evidence-root", str(evidence))

                self.assertEqual(verified.returncode, 2)

    def test_order_duplicate_and_lower_level_records_are_not_sealable(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw).resolve()
            root = base / "impl"
            evidence = base / "evidence"
            evidence.mkdir()
            command = "python3 -c 'print(1)'"
            self.write_impl_root(root, [command, command])

            skipped = self.run_todo(root=root, evidence=evidence, step=2, argv=["python3", "-c", "print(1)"])
            first = self.run_todo(root=root, evidence=evidence, step=1, argv=["python3", "-c", "print(1)"])
            duplicate = self.run_todo(root=root, evidence=evidence, step=1, argv=["python3", "-c", "print(1)"])
            second = self.run_todo(root=root, evidence=evidence, step=2, argv=["python3", "-c", "print(1)"])
            first_record = canonical(evidence / "task-5-runs" / "1.json")
            second_record = canonical(evidence / "task-5-runs" / "2.json")

            source = evidence / "source.json"
            brain = evidence / "brain.json"
            log = evidence / "task.log"
            source.write_text("{}\n", encoding="utf-8")
            brain.write_text("{}\n", encoding="utf-8")
            log.write_text("task\n", encoding="utf-8")
            sealed = run_cli(
                "seal-todo",
                "--todo",
                "5",
                "--plan",
                str(self.plan_path(root)),
                "--baseline-commit",
                MODEL_BASELINE,
                "--impl-root",
                str(root),
                "--source-baseline",
                str(source),
                "--brain-baseline",
                str(brain),
                "--runs",
                str(evidence / "task-5-runs"),
                "--task-log",
                str(log),
                "--output",
                str(evidence / "receipt.json"),
            )
            receipt_verify = run_cli("verify-todo", "--receipt", str(evidence / "receipt.json"), "--evidence-root", str(evidence))

        self.assertEqual(skipped.returncode, 2)
        self.assertEqual(first.returncode, 0)
        self.assertEqual(duplicate.returncode, 2)
        self.assertEqual(second.returncode, 0)
        self.assertEqual(first_record["canonical_command"], second_record["canonical_command"])
        self.assertEqual(first_record["environment_binding_sha256"], second_record["environment_binding_sha256"])
        self.assertEqual(sealed.returncode, 0, sealed.stderr.decode("utf-8", "replace"))
        self.assertEqual(receipt_verify.returncode, 0, receipt_verify.stderr.decode("utf-8", "replace"))

    def test_seal_rejects_tampered_wrapper_proof(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw).resolve()
            root = base / "impl"
            evidence = base / "evidence"
            evidence.mkdir()
            self.write_impl_root(root, ["python3 -c 'print(1)'"])
            run = self.run_todo(root=root, evidence=evidence, step=1, argv=["python3", "-c", "print(1)"])
            record = canonical(evidence / "task-5-runs" / "1.json")
            record.pop("run_todo_wrapper")
            (evidence / "task-5-runs" / "1.json").write_text(
                json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            source = evidence / "source.json"
            brain = evidence / "brain.json"
            log = evidence / "task.log"
            source.write_text("{}\n", encoding="utf-8")
            brain.write_text("{}\n", encoding="utf-8")
            log.write_text("task\n", encoding="utf-8")

            sealed = run_cli(
                "seal-todo",
                "--todo",
                "5",
                "--plan",
                str(self.plan_path(root)),
                "--baseline-commit",
                MODEL_BASELINE,
                "--impl-root",
                str(root),
                "--source-baseline",
                str(source),
                "--brain-baseline",
                str(brain),
                "--runs",
                str(evidence / "task-5-runs"),
                "--task-log",
                str(log),
                "--output",
                str(evidence / "receipt.json"),
            )

        self.assertEqual(run.returncode, 0, run.stderr.decode("utf-8", "replace"))
        self.assertEqual(sealed.returncode, 2)
        self.assertEqual(sealed.stdout, b"")
        self.assertFalse((evidence / "receipt.json").exists())

    def test_seal_rejects_run_plan_or_implementation_that_differs_from_final_state(self) -> None:
        cases = ("plan", "implementation")
        for case in cases:
            with self.subTest(case=case):
                with tempfile.TemporaryDirectory() as raw:
                    base = Path(raw).resolve()
                    root = base / "impl"
                    evidence = base / "evidence"
                    evidence.mkdir()
                    self.write_impl_root(root, ["python3 -c 'print(1)'"])
                    run = self.run_todo(root=root, evidence=evidence, step=1, argv=["python3", "-c", "print(1)"])
                    if case == "plan":
                        self.plan_path(root).write_text("# changed plan\n", encoding="utf-8")
                    else:
                        (root / "model" / "product.txt").write_text("changed\n", encoding="utf-8")
                    source = evidence / "source.json"
                    brain = evidence / "brain.json"
                    log = evidence / "task.log"
                    source.write_text("{}\n", encoding="utf-8")
                    brain.write_text("{}\n", encoding="utf-8")
                    log.write_text("task\n", encoding="utf-8")

                    sealed = run_cli(
                        "seal-todo",
                        "--todo",
                        "5",
                        "--plan",
                        str(self.plan_path(root)),
                        "--baseline-commit",
                        MODEL_BASELINE,
                        "--impl-root",
                        str(root),
                        "--source-baseline",
                        str(source),
                        "--brain-baseline",
                        str(brain),
                        "--runs",
                        str(evidence / "task-5-runs"),
                        "--task-log",
                        str(log),
                        "--output",
                        str(evidence / "receipt.json"),
                    )

                self.assertEqual(run.returncode, 0)
                self.assertEqual(sealed.returncode, 2)
                self.assertIn(b"run", sealed.stderr)

    def test_verify_rejects_swapped_run_state_hashes_and_missing_implementation_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw).resolve()
            root = base / "impl"
            evidence = base / "evidence"
            evidence.mkdir()
            self.write_impl_root(root, ["python3 -c 'print(1)'"])
            run = self.run_todo(root=root, evidence=evidence, step=1, argv=["python3", "-c", "print(1)"])
            source = evidence / "source.json"
            brain = evidence / "brain.json"
            log = evidence / "task.log"
            source.write_text("{}\n", encoding="utf-8")
            brain.write_text("{}\n", encoding="utf-8")
            log.write_text("task\n", encoding="utf-8")
            sealed = run_cli(
                "seal-todo",
                "--todo",
                "5",
                "--plan",
                str(self.plan_path(root)),
                "--baseline-commit",
                MODEL_BASELINE,
                "--impl-root",
                str(root),
                "--source-baseline",
                str(source),
                "--brain-baseline",
                str(brain),
                "--runs",
                str(evidence / "task-5-runs"),
                "--task-log",
                str(log),
                "--output",
                str(evidence / "receipt.json"),
            )
            receipt = canonical(evidence / "receipt.json")
            run_record = canonical(evidence / "task-5-runs" / "1.json")
            run_record["plan_sha256"], run_record["implementation_sha256"] = (
                run_record["implementation_sha256"],
                run_record["plan_sha256"],
            )
            swapped_run = evidence / "task-5-runs" / "swapped.json"
            swapped_run.write_text(
                json.dumps(run_record, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            swapped_receipt = dict(receipt)
            swapped_receipt["runs"] = [file_record("evidence", evidence, swapped_run)]
            swapped_receipt_path = evidence / "swapped-receipt.json"
            swapped_receipt_path.write_text(
                json.dumps(swapped_receipt, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            missing_manifest = dict(receipt)
            missing_manifest.pop("implementation_manifest", None)
            missing_manifest.pop("implementation_archive", None)
            missing_manifest_path = evidence / "missing-manifest-receipt.json"
            missing_manifest_path.write_text(
                json.dumps(missing_manifest, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )

            swapped_verify = run_cli("verify-todo", "--receipt", str(swapped_receipt_path), "--evidence-root", str(evidence))
            missing_verify = run_cli("verify-todo", "--receipt", str(missing_manifest_path), "--evidence-root", str(evidence))

        self.assertEqual(run.returncode, 0)
        self.assertEqual(sealed.returncode, 0, sealed.stderr.decode("utf-8", "replace"))
        self.assertEqual(swapped_verify.returncode, 2)
        self.assertEqual(missing_verify.returncode, 2)


if __name__ == "__main__":
    unittest.main()
