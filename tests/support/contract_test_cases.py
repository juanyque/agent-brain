from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

from .evidence_json import JsonValue

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "tests/support/evidence_contract.py"
sys.path.insert(0, str(ROOT / "tests" / "support"))

from evidence_implementation import implementation_git_state_sha, implementation_sha  # noqa: E402


def cli(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["python3", "-B", str(CLI), *args],
        cwd=ROOT,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        check=False,
    )


def cli_with_env(environment: dict[str, str], *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["python3", "-B", str(CLI), *args],
        cwd=ROOT,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", **environment},
        capture_output=True,
        check=False,
    )


def write_json(path: Path, value: JsonValue) -> None:
    path.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def write_minimal_lane_freeze(path: Path) -> None:
    write_json(
        path,
        {
            "implementation_git_state_sha256": implementation_git_state_sha(ROOT),
            "implementation_sha256": implementation_sha(ROOT),
            "plan_sha256": "0" * 64,
        },
    )


class ModelNegativeCases:
    def test_dependency_graph_failures_are_rejected(self) -> None:
        fixtures = ({
            "schema_version": "agent-brain-operating-model/v1",
            "dependency_graph": [{"depends_on": [1], "todo": 1}],
            "future_routes": [],
        },)
        with tempfile.TemporaryDirectory() as raw:
            for index, fixture in enumerate(fixtures):
                path = Path(raw) / f"{index}.json"
                write_json(path, fixture)
                with self.subTest(index=index):
                    self.assertEqual(cli("verify-json", "--input", str(path)).returncode, 2)

    def test_invalid_base64_and_out_of_order_paths_are_rejected(self) -> None:
        fixtures = (
            {"entries": [{"path_b64": "***"}], "root": "qa"},
            {
                "entries": [
                    {"path_b64": "Yg==", "type": "file"},
                    {"path_b64": "YQ==", "type": "file"},
                ],
                "root": "qa",
            },
        )
        with tempfile.TemporaryDirectory() as raw:
            for index, fixture in enumerate(fixtures):
                path = Path(raw) / f"{index}.json"
                write_json(path, fixture)
                with self.subTest(index=index):
                    self.assertEqual(cli("verify-json", "--input", str(path)).returncode, 2)


class TreeInterruptionCases:
    def test_ustar_members_are_deterministic_regular_blobs(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            tree = root / "tree"
            tree.mkdir()
            (tree / "a").write_bytes(b"a")
            archive = root / "a.tar"
            result = cli("capture-worktree", "--root", str(tree), "--archive",
                         str(archive), "--manifest", str(root / "m.json"))
            self.assertEqual(result.returncode, 0, result.stderr)
            with tarfile.open(archive, "r:") as stream:
                members = stream.getmembers()
            self.assertEqual(len(archive.read_bytes()), 2048)
            self.assertEqual(archive.read_bytes()[-1024:], b"\0" * 1024)
            self.assertEqual(len(members), 1)
            member = members[0]
            self.assertTrue(member.isfile())
            self.assertEqual((member.mode, member.uid, member.gid, member.mtime), (0o600, 0, 0, 0))
            self.assertEqual((member.uname, member.gname), ("", ""))

    def test_partial_and_symlink_destinations_fail_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            tree = root / "tree"
            tree.mkdir()
            (tree / "a").write_bytes(b"a")
            archive = root / "a.tar"
            archive.write_bytes(b"partial")
            manifest = root / "m.json"
            result = cli("capture-worktree", "--root", str(tree), "--archive",
                         str(archive), "--manifest", str(manifest))
            self.assertEqual(result.returncode, 2)
            self.assertEqual(archive.read_bytes(), b"partial")
            outside = root / "outside"
            outside.mkdir()
            output = root / "output"
            output.symlink_to(outside, target_is_directory=True)
            fake = root / "fake.json"
            write_json(fake, {"entries": [], "root": "implementation"})
            materialize = cli("materialize", "--manifest", str(fake),
                              "--archive", str(archive), "--output", str(output))
            self.assertEqual(materialize.returncode, 2)
            self.assertEqual(list(outside.iterdir()), [])

    def test_non_utf8_git_status_bytes_are_captured_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            tree = root / "tree"
            binary = root / "bin"
            tree.mkdir()
            binary.mkdir()
            (tree / "tracked").write_bytes(b"dirty\n")
            fake_git = binary / "git"
            fake_git.write_bytes(
                b"#!/bin/sh\nprintf ' M tracked\\000?? untracked-\\377\\000'\n"
            )
            fake_git.chmod(0o700)
            status = b" M tracked\0?? untracked-\xff\0"
            result = cli_with_env(
                {"PATH": f"{binary}:{os.environ['PATH']}"},
                "capture-worktree", "--root", str(tree), "--archive",
                str(root / "a.tar"), "--manifest", str(root / "m.json"),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads((root / "m.json").read_text())
            self.assertEqual(
                manifest["git_status_sha256"], hashlib.sha256(status).hexdigest()
            )


class EvidenceAdversarialCases:
    def test_temp_plan_review_create_repeat_and_receipt_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            brain = base / "brain"
            plan_dir = brain / ".omo/plans"
            draft_dir = brain / ".omo/drafts"
            evidence = base / "evidence"
            review_dir = evidence / "plan-review"
            plan_dir.mkdir(parents=True)
            draft_dir.mkdir(parents=True)
            review_dir.mkdir(parents=True)
            plan = plan_dir / "plan.md"
            plan.write_bytes(b"plan\n")
            sha = hashlib.sha256(plan.read_bytes()).hexdigest()
            review = {
                "independent": {"launch_id": "i"}, "momus": {"launch_id": "m"}
            }
            round_data = {
                "plan_sha256": sha, "review": review, "review_round_id": "r",
                "round_status": "approved",
            }
            draft = draft_dir / "draft.md"
            draft.write_text(f"```json\n{json.dumps(round_data)}\n```\n")
            receipts = {}
            for name, launch in (("momus", "m"), ("independent", "i")):
                path = review_dir / f"{name}.txt"
                path.write_text(
                    json.dumps({"launch_id": launch, "plan_sha256": sha,
                                "reviewer": name, "round_id": "r"}) + "\nOKAY\n"
                )
                receipts[name] = path
            seal = review_dir / "review.json"
            args = ("plan-review", "--plan", str(plan), "--draft", str(draft),
                    "--momus-receipt", str(receipts["momus"]),
                    "--independent-receipt", str(receipts["independent"]),
                    "--output", str(seal))
            self.assertEqual(cli(*args).returncode, 0)
            sealed = seal.read_bytes()
            self.assertEqual(cli(*args).returncode, 2)
            self.assertEqual(seal.read_bytes(), sealed)
            receipts["momus"].write_text(receipts["momus"].read_text() + "changed\n")
            verify = cli("verify-plan-review", "--seal", str(seal),
                         "--evidence-root", str(evidence))
            self.assertEqual(verify.returncode, 2)

    def test_success_stdout_with_nonzero_status_remains_failure(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            freeze = base / "freeze.json"
            write_minimal_lane_freeze(freeze)
            result = cli(
                "run-lane", "--lane", "F1", "--step", "1", "--cwd", str(ROOT),
                "--freeze", str(freeze), "--evidence-root", str(base), "--",
                "/bin/sh", "-c", "printf PASS; exit 7",
            )
            self.assertEqual(result.returncode, 7)
            self.assertEqual((base / "F1-runs/1.stdout").read_bytes(), b"PASS")
            record = json.loads((base / "F1-runs/1.json").read_text())
            self.assertEqual(record["exit_status"], 7)

    def test_hung_command_is_recorded_as_timeout_failure(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            freeze = base / "freeze.json"
            write_minimal_lane_freeze(freeze)
            result = cli_with_env(
                {"AGENT_BRAIN_COMMAND_TIMEOUT_SECONDS": "0.05"},
                "run-lane", "--lane", "F2", "--step", "1", "--cwd", str(ROOT),
                "--freeze", str(freeze), "--evidence-root", str(base), "--",
                "/bin/sleep", "5",
            )
            self.assertEqual(result.returncode, 124)
            record = json.loads((base / "F2-runs/1.json").read_text())
            self.assertEqual(record["exit_status"], 124)
            self.assertIn(b"timed out", (base / "F2-runs/1.stderr").read_bytes())
