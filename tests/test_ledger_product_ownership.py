from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
import time
from pathlib import Path


JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tests" / "support" / "evidence_contract.py"
BASELINE = "993247b2850ac86993c7c6dd18e6c4fd9ec6df7c"
LEDGER = ".omo/start-work/ledger.jsonl"
sys.path.insert(0, str(ROOT / "tests" / "support"))

from evidence_ledger import PRODUCT_EXCLUDED_PATHS, PRODUCT_SCOPE  # noqa: E402
from evidence_implementation import manifest_implementation_git_sha, manifest_implementation_sha  # noqa: E402
from evidence_tree import _blobs, create_archive, scan_tree  # noqa: E402


def run_cli(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, "-B", str(CLI), *args],
        cwd=ROOT,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        check=False,
    )


def canonical_bytes(value: JsonValue) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
    ).encode("utf-8")


def write_json(path: Path, value: JsonValue) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value))


def read_json(path: Path) -> dict[str, JsonValue]:
    return json.loads(path.read_text(encoding="utf-8"))


def path_b64(path: str) -> str:
    return base64.b64encode(path.encode("utf-8")).decode("ascii")


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def file_ref(path: Path) -> dict[str, JsonValue]:
    return {"path": str(path), "sha256": file_sha(path), "size": path.stat().st_size}


class ProductFixture:
    def __init__(self, raw: str) -> None:
        self.base = Path(raw).resolve()
        self.impl = self.base / "impl"
        self.evidence = self.base / "evidence"
        self.evidence.mkdir(parents=True)
        self.write_impl()

    @property
    def plan(self) -> Path:
        return self.impl / ".omo" / "plans" / "agent-brain-operating-model.md"

    @property
    def ledger(self) -> Path:
        return self.impl / LEDGER

    def write_impl(self) -> None:
        (self.impl / ".omo" / "plans").mkdir(parents=True)
        (self.impl / ".omo" / "start-work").mkdir(parents=True)
        (self.impl / "model").mkdir()
        (self.impl / "tests" / "fixtures").mkdir(parents=True)
        (self.impl / ".gitignore").write_text(f"/{LEDGER}\n", encoding="utf-8")
        self.plan.write_text("# fixture plan\n- [x] 5 product fixture\n", encoding="utf-8")
        self.ledger.write_text('{"event":"start"}\n', encoding="utf-8")
        write_json(
            self.impl / "model" / "OPERATING-MODEL.json",
            {
                "baseline": {"plan_sha256": file_sha(self.plan)},
                "schema_version": "agent-brain-operating-model/v1",
            },
        )
        write_json(
            self.impl / "tests" / "fixtures" / "operating-model-qa-commands.json",
            {
                "schema_version": "agent-brain-qa-commands/v1",
                "todos": [
                    {
                        "steps": [{"command": "python3 -B -c 'print(1)'", "mode": "argv", "step": 1}],
                        "todo": todo,
                    }
                    for todo in range(1, 20)
                ],
            },
        )
        subprocess.run(["git", "init"], cwd=self.impl, check=True, stdout=subprocess.DEVNULL)
        subprocess.run(["git", "add", "."], cwd=self.impl, check=True)
        subprocess.run(
            ["git", "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid",
             "commit", "-m", "fixture"],
            cwd=self.impl,
            check=True,
            stdout=subprocess.DEVNULL,
        )

    def add_manual_qa_files(self) -> None:
        scripts = self.impl / "model" / "SCRIPTS"
        scripts.mkdir()
        (scripts / "home_setup.py").write_text(
            "from __future__ import annotations\n"
            "import argparse\n"
            "from pathlib import Path\n"
            "parser = argparse.ArgumentParser()\n"
            "parser.add_argument('--brain', type=Path, required=True)\n"
            "args = parser.parse_args()\n"
            "args.brain.mkdir(parents=True, exist_ok=True)\n"
            "(args.brain / 'setup.txt').write_text('ok\\n', encoding='utf-8')\n"
            "print('setup ok')\n",
            encoding="utf-8",
        )
        (scripts / "model_check.py").write_text(
            "from __future__ import annotations\n"
            "import argparse\n"
            "import json\n"
            "parser = argparse.ArgumentParser()\n"
            "parser.add_argument('--brain', required=True)\n"
            "parser.add_argument('--format', default='json')\n"
            "args = parser.parse_args()\n"
            "print(json.dumps({'brain': args.brain, 'findings': []}, sort_keys=True))\n",
            encoding="utf-8",
        )
        (self.impl / "tests" / "test_smoke.py").write_text(
            "from __future__ import annotations\n"
            "import unittest\n\n"
            "class SmokeTests(unittest.TestCase):\n"
            "    def test_smoke(self) -> None:\n"
            "        self.assertEqual(1, 1)\n",
            encoding="utf-8",
        )

    def connected_brain(self) -> Path:
        brain = self.base / "connected-brain"
        brain.mkdir()
        (brain / "README.md").write_text("brain\n", encoding="utf-8")
        subprocess.run(["git", "init"], cwd=brain, check=True, stdout=subprocess.DEVNULL)
        subprocess.run(["git", "add", "."], cwd=brain, check=True)
        subprocess.run(
            ["git", "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid",
             "commit", "-m", "brain"],
            cwd=brain,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        return brain

    def capture(self, name: str) -> tuple[Path, Path, subprocess.CompletedProcess[bytes]]:
        manifest = self.evidence / f"{name}.json"
        archive = self.evidence / f"{name}.tar"
        result = run_cli(
            "capture-worktree",
            "--root",
            str(self.impl),
            "--archive",
            str(archive),
            "--manifest",
            str(manifest),
        )
        return manifest, archive, result

    def run_todo(self) -> subprocess.CompletedProcess[bytes]:
        return run_cli(
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

    def seal_todo(self) -> subprocess.CompletedProcess[bytes]:
        return self.seal_one_todo(5)

    def seal_one_todo(self, todo: int) -> subprocess.CompletedProcess[bytes]:
        for name in ("source.json", "brain.json", "task.log"):
            (self.evidence / name).write_text("{}\n", encoding="utf-8")
        return run_cli(
            "seal-todo",
            "--todo",
            str(todo),
            "--plan",
            str(self.plan),
            "--baseline-commit",
            BASELINE,
            "--impl-root",
            str(self.impl),
            "--source-baseline",
            str(self.evidence / "source.json"),
            "--brain-baseline",
            str(self.evidence / "brain.json"),
            "--runs",
            str(self.evidence / f"task-{todo}-runs"),
            "--task-log",
            str(self.evidence / "task.log"),
            "--implementation-manifest",
            str(self.evidence / "implementation.json"),
            "--implementation-archive",
            str(self.evidence / "implementation.tar"),
            "--output",
            str(self.evidence / f"task-{todo}-receipt.json"),
        )

    def run_one_todo(self, todo: int) -> subprocess.CompletedProcess[bytes]:
        return run_cli(
            "run-todo",
            "--todo",
            str(todo),
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

    def create_plan_review(self) -> tuple[Path, Path, Path]:
        brain = self.base / "brain"
        plan = brain / ".omo" / "plans" / "agent-brain-operating-model.md"
        draft = brain / ".omo" / "drafts" / "draft.md"
        review_root = self.evidence / "plan-review"
        plan.parent.mkdir(parents=True)
        draft.parent.mkdir(parents=True)
        review_root.mkdir()
        plan.write_bytes(self.plan.read_bytes())
        plan_sha = file_sha(plan)
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
                }
            )
            + "\n```\n",
            encoding="utf-8",
        )
        for reviewer, launch in (
            ("momus", "momus-launch"),
            ("independent", "independent-launch"),
        ):
            (review_root / f"{reviewer}.txt").write_text(
                json.dumps(
                    {
                        "launch_id": launch,
                        "plan_sha256": plan_sha,
                        "reviewer": reviewer,
                        "round_id": "round-1",
                    }
                )
                + "\nOKAY\n",
                encoding="utf-8",
            )
        seal = review_root / "review-seal.json"
        result = run_cli(
            "plan-review",
            "--plan",
            str(plan),
            "--draft",
            str(draft),
            "--momus-receipt",
            str(review_root / "momus.txt"),
            "--independent-receipt",
            str(review_root / "independent.txt"),
            "--output",
            str(seal),
        )
        if result.returncode != 0:
            raise AssertionError(result.stderr.decode("utf-8", "replace"))
        return plan, draft, seal

    def create_successor_plan_review(self) -> tuple[Path, Path, Path, Path]:
        prior_plan, draft, prior_seal = self.create_plan_review()
        self.plan.write_text(
            self.plan.read_text(encoding="utf-8") + "- [x] successor lifecycle documentation\n",
            encoding="utf-8",
        )
        seal = self.write_successor_plan_review(draft, prior_seal)
        return prior_plan, draft, prior_seal, seal

    def write_successor_plan_review(self, draft: Path, prior_seal: Path) -> Path:
        review_root = self.evidence / "successor-plan-review"
        review_root.mkdir()
        plan_sha = file_sha(self.plan)
        for reviewer, launch in (
            ("momus", "successor-momus-launch"),
            ("independent", "successor-independent-launch"),
        ):
            (review_root / f"{reviewer}.txt").write_text(
                json.dumps(
                    {
                        "launch_id": launch,
                        "plan_sha256": plan_sha,
                        "reviewer": reviewer,
                        "round_id": "successor-round-1",
                    }
                )
                + "\nOKAY\n",
                encoding="utf-8",
            )
        seal = review_root / "review-seal.json"
        result = run_cli(
            "successor-plan-review",
            "--plan",
            str(self.plan),
            "--impl-root",
            str(self.impl),
            "--draft",
            str(draft),
            "--brain-root",
            str(draft.parents[2]),
            "--prior-seal",
            str(prior_seal),
            "--evidence-root",
            str(self.evidence),
            "--momus-receipt",
            str(review_root / "momus.txt"),
            "--independent-receipt",
            str(review_root / "independent.txt"),
            "--output",
            str(seal),
        )
        if result.returncode != 0:
            raise AssertionError(result.stderr.decode("utf-8", "replace"))
        return seal

    def prepare_all_todos_plan(self) -> None:
        lines = [f"- [x] {todo}. closure todo {todo}" for todo in range(1, 20)]
        self.plan.write_text("\n".join(lines) + "\n", encoding="utf-8")
        write_json(
            self.impl / "model" / "OPERATING-MODEL.json",
            {
                "baseline": {"plan_sha256": file_sha(self.plan)},
                "schema_version": "agent-brain-operating-model/v1",
            },
        )

    def init_state_repo(self, name: str) -> Path:
        root = self.base / name
        root.mkdir()
        (root / "tracked.md").write_text(f"{name}\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.email", "fixture@example.invalid"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.name", "fixture"], cwd=root, check=True)
        subprocess.run(["git", "add", "."], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", name], cwd=root, check=True)
        return root

    def capture_state_pair(self, kind: str, root: Path) -> None:
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
            if result.returncode != 0:
                raise AssertionError(result.stderr.decode("utf-8", "replace"))

    def closure_rows_sha(self, pattern: str) -> str:
        rows: list[dict[str, JsonValue]] = []
        for todo in range(1, 20):
            path = self.evidence / pattern.format(todo=todo)
            rows.append(
                {
                    "evidence_root": str(self.evidence),
                    "path": str(path),
                    "sha256": file_sha(path),
                    "size": path.stat().st_size,
                    "todo": todo,
                }
            )
        return hashlib.sha256(canonical_bytes(rows)).hexdigest()

    def create_wave4_closure_v2(
        self,
        wave: int = 4,
        *,
        approval_required: bool = True,
        successor_review: bool = False,
    ) -> tuple[Path, Path, Path]:
        if successor_review:
            _prior_plan, draft, prior_seal = self.create_plan_review()
            self.prepare_all_todos_plan()
            plan = self.plan
            seal = self.write_successor_plan_review(draft, prior_seal)
        else:
            self.prepare_all_todos_plan()
            plan, draft, seal = self.create_plan_review()
        source = self.init_state_repo("source")
        brain_root = draft.parents[2]
        subprocess.run(["git", "init", "-q"], cwd=brain_root, check=True)
        subprocess.run(["git", "config", "user.email", "fixture@example.invalid"], cwd=brain_root, check=True)
        subprocess.run(["git", "config", "user.name", "fixture"], cwd=brain_root, check=True)
        subprocess.run(["git", "add", "."], cwd=brain_root, check=True)
        subprocess.run(["git", "commit", "-qm", "brain"], cwd=brain_root, check=True)
        self.capture_state_pair("source", source)
        self.capture_state_pair("brain", brain_root)
        for todo in range(1, 20):
            run = self.run_one_todo(todo)
            if run.returncode != 0:
                raise AssertionError(run.stderr.decode("utf-8", "replace"))
            receipt = self.seal_one_todo(todo)
            if receipt.returncode != 0:
                raise AssertionError(receipt.stderr.decode("utf-8", "replace"))
        report = self.evidence / "closure-gate-report.json"
        write_json(report, {"schema_version": "closure-gate/v1", "verdict": "READY"})
        plan_sha = file_sha(plan)
        product_sha = manifest_implementation_sha(self.evidence / "implementation.json")
        git_sha = manifest_implementation_git_sha(self.evidence / "implementation.json")
        if git_sha is None:
            raise AssertionError("fixture implementation manifest lacks Git state")
        task_receipts_sha = self.closure_rows_sha("task-{todo}-receipt.json")
        governed_runs_sha = self.closure_rows_sha("task-{todo}-runs/1.json")
        tooling_review = self.evidence / "tooling-review.json"
        write_json(
            tooling_review,
            {
                "blockers": [],
                "executor_id": "executor-1",
                "findings": [],
                "git_state_sha256": git_sha,
                "governed_runs_sha256": governed_runs_sha,
                "plan_sha256": plan_sha,
                "product_sha256": product_sha,
                "reviewer_id": "tooling-reviewer-1",
                "role": "tooling-review",
                "schema_version": "agent-brain-tooling-review-report/v1",
                "task_receipts_sha256": task_receipts_sha,
                "verdict": "APPROVE",
            },
        )
        independent_gate = self.evidence / "independent-gate-report.json"
        write_json(
            independent_gate,
            {
                "blockers": [],
                "executor_id": "executor-1",
                "findings": [],
                "git_state_sha256": git_sha,
                "governed_runs_sha256": governed_runs_sha,
                "plan_sha256": plan_sha,
                "product_sha256": product_sha,
                "reviewer_id": "independent-gate-reviewer-1",
                "role": "independent-gate-report",
                "schema_version": "agent-brain-independent-gate-report/v1",
                "task_receipts_sha256": task_receipts_sha,
                "verdict": "CONFIRMED",
            },
        )
        command: list[str] = [
            "create-closure-v2",
            "--wave",
            str(wave),
            "--plan",
            str(plan),
            "--impl-root",
            str(self.impl),
            "--implementation-manifest",
            str(self.evidence / "implementation.json"),
            "--implementation-archive",
            str(self.evidence / "implementation.tar"),
        ]
        if approval_required:
            command.extend([
                "--draft",
                str(draft),
                "--review-seal",
                str(seal),
                "--tooling-review",
                str(tooling_review),
                "--independent-gate",
                str(independent_gate),
            ])
        for todo in range(1, 20):
            command.extend([
                "--task-receipt",
                str(todo),
                str(self.evidence / f"task-{todo}-receipt.json"),
                str(self.evidence),
                "--governed-run",
                str(todo),
                str(self.evidence / f"task-{todo}-runs/1.json"),
                str(self.evidence),
            ])
        command.extend([
            "--source-before", str(self.evidence / "source-before.json"), str(self.evidence / "source-before-sidecars"),
            "--source-after", str(self.evidence / "source-after.json"), str(self.evidence / "source-after-sidecars"),
            "--brain-before", str(self.evidence / "brain-before.json"), str(self.evidence / "brain-before-sidecars"),
            "--brain-after", str(self.evidence / "brain-after.json"), str(self.evidence / "brain-after-sidecars"),
            "--report", str(report),
            "--output", str(self.evidence / "wave-4-closure-v2.json"),
        ])
        result = run_cli(*command)
        if result.returncode != 0:
            raise AssertionError(result.stderr.decode("utf-8", "replace"))
        return plan, draft, seal

    def approve_wave4_closure_v2(self) -> subprocess.CompletedProcess[bytes]:
        receipt = self.evidence / "wave-4-closure-v2.json"
        message = self.evidence / "wave-4-closure-v2-approval-message.txt"
        message.write_text(f"APPROVE wave 4 {file_sha(receipt)}\n", encoding="utf-8")
        return run_cli(
            "approve-wave",
            "--wave",
            "4",
            "--receipt",
            str(receipt),
            "--message",
            str(message),
            "--output",
            str(self.evidence / "wave-4-approval.json"),
            "--impl-root",
            str(self.impl),
            "--evidence-root",
            str(self.evidence),
        )

    def create_wave4_receipt(self) -> tuple[Path, Path, Path]:
        plan, draft, seal = self.create_plan_review()
        for todo in range(1, 20):
            run = self.run_one_todo(todo)
            if run.returncode != 0:
                raise AssertionError(run.stderr.decode("utf-8", "replace"))
            receipt = self.seal_one_todo(todo)
            if receipt.returncode != 0:
                raise AssertionError(receipt.stderr.decode("utf-8", "replace"))
        result = run_cli(
            "wave",
            "--wave",
            "4",
            "--plan",
            str(plan),
            "--draft",
            str(draft),
            "--review-seal",
            str(seal),
            "--source-baseline",
            str(self.evidence / "source.json"),
            "--brain-baseline",
            str(self.evidence / "brain.json"),
            "--impl-root",
            str(self.impl),
            "--evidence-root",
            str(self.evidence),
            "--output",
            str(self.evidence / "wave-4-receipt.json"),
        )
        if result.returncode != 0:
            raise AssertionError(result.stderr.decode("utf-8", "replace"))
        return plan, draft, seal

    def approve_wave4(self) -> subprocess.CompletedProcess[bytes]:
        self.create_wave4_receipt()
        receipt = self.evidence / "wave-4-receipt.json"
        message = self.evidence / "wave-4-approval-message.txt"
        message.write_text(f"APPROVE wave 4 {file_sha(receipt)}\n", encoding="utf-8")
        return run_cli(
            "approve-wave",
            "--wave",
            "4",
            "--receipt",
            str(receipt),
            "--message",
            str(message),
            "--output",
            str(self.evidence / "wave-4-approval.json"),
            "--impl-root",
            str(self.impl),
            "--evidence-root",
            str(self.evidence),
        )

    def freeze_with_wave_checkpoint(self) -> subprocess.CompletedProcess[bytes]:
        wave = read_json(self.evidence / "wave-4-receipt.json")
        review_record = wave.get("review_seal")
        if not isinstance(review_record, dict):
            raise AssertionError("wave lacks review seal")
        plan = self.base / "brain" / ".omo" / "plans" / "agent-brain-operating-model.md"
        draft = self.base / "brain" / ".omo" / "drafts" / "draft.md"
        review = self.evidence / base64.b64decode(str(review_record["path_b64"])).decode("utf-8")
        return run_cli(
            "freeze",
            "--plan",
            str(plan),
            "--draft",
            str(draft),
            "--review-seal",
            str(review),
            "--impl-root",
            str(self.impl),
            "--evidence-root",
            str(self.evidence),
            "--prior-ledger-checkpoint",
            str(self.evidence / "wave-4-approval.ledger-checkpoint.json"),
            "--output",
            str(self.evidence / "freeze.json"),
        )

    def write_minimal_freeze(self) -> Path:
        manifest, _archive, captured = self.capture("minimal-freeze")
        if captured.returncode != 0:
            raise AssertionError(captured.stderr.decode("utf-8", "replace"))
        manifest_value = read_json(manifest)
        git = manifest_value.get("git_administration")
        if not isinstance(git, dict):
            raise AssertionError("implementation manifest lacks Git state")
        freeze = self.evidence / "freeze.json"
        write_json(
            freeze,
            {
                "implementation_git_state_sha256": git["state_sha256"],
                "implementation_sha256": hashlib.sha256(
                    canonical_bytes(manifest_value["entries"])
                ).hexdigest(),
                "plan_sha256": file_sha(self.plan),
            },
        )
        return freeze

    def create_lane(self, lane: str, output_name: str) -> subprocess.CompletedProcess[bytes]:
        lower = lane.lower()
        before = run_cli(
            "verify-freeze",
            "--freeze",
            str(self.evidence / "freeze.json"),
            "--impl-root",
            str(self.impl),
            "--evidence-root",
            str(self.evidence),
            "--recompute",
            str(self.evidence / f"{lower}-freeze-before.json"),
        )
        if before.returncode != 0:
            raise AssertionError(before.stderr.decode("utf-8", "replace"))
        run = run_cli(
            "run-lane",
            "--lane",
            lane,
            "--step",
            "1",
            "--cwd",
            str(self.impl),
            "--freeze",
            str(self.evidence / "freeze.json"),
            "--evidence-root",
            str(self.evidence),
            "--",
            sys.executable,
            "-B",
            "-c",
            "print('ok')",
        )
        if run.returncode != 0:
            raise AssertionError(run.stderr.decode("utf-8", "replace"))
        after = run_cli(
            "verify-freeze",
            "--freeze",
            str(self.evidence / "freeze.json"),
            "--impl-root",
            str(self.impl),
            "--evidence-root",
            str(self.evidence),
            "--recompute",
            str(self.evidence / f"{lower}-freeze-after.json"),
        )
        if after.returncode != 0:
            raise AssertionError(after.stderr.decode("utf-8", "replace"))
        return run_cli(
            "lane",
            "--lane",
            lane,
            "--freeze",
            str(self.evidence / "freeze.json"),
            "--runs",
            str(self.evidence / f"{lane}-runs"),
            "--before",
            str(self.evidence / f"{lower}-freeze-before.json"),
            "--after",
            str(self.evidence / f"{lower}-freeze-after.json"),
            "--output",
            str(self.evidence / output_name),
        )

    def create_manual_qa_f3_lane(self, connected_brain: Path) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            [
                sys.executable,
                "-B",
                str(ROOT / "tests" / "support" / "run_manual_qa.py"),
                "--frozen-manifest",
                str(self.evidence / "freeze.json"),
                "--freeze-before",
                str(self.evidence / "f3-freeze-before.json"),
                "--freeze-after",
                str(self.evidence / "f3-freeze-after.json"),
                "--runs",
                str(self.evidence / "F3-runs"),
                "--qa-root",
                str(self.base / "qa-root"),
                "--connected-brain",
                str(connected_brain),
                "--artifact",
                str(self.evidence / "f3-artifacts.tar"),
                "--artifact-manifest",
                str(self.evidence / "f3-artifacts.manifest.json"),
                "--lane-output",
                str(self.evidence / "f3-manual-qa.json"),
            ],
            cwd=self.impl,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            capture_output=True,
            check=False,
        )


class LedgerProductOwnershipTests(unittest.TestCase):
    def test_implementation_product_manifest_excludes_only_start_work_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = ProductFixture(raw)
            first_manifest, first_archive, first = fixture.capture("first")
            git_index = path_b64(".git/index")
            fixture.ledger.write_text(
                fixture.ledger.read_text(encoding="utf-8") + '{"event":"approved"}\n',
                encoding="utf-8",
            )
            second_manifest, second_archive, second = fixture.capture("second")

            self.assertEqual(first.returncode, 0, first.stderr.decode("utf-8", "replace"))
            self.assertEqual(second.returncode, 0, second.stderr.decode("utf-8", "replace"))
            first_value = read_json(first_manifest)
            second_value = read_json(second_manifest)
            self.assertEqual(first_value["schema_version"], "agent-brain-implementation/v3")
            self.assertEqual(first_value["scope"], "product")
            self.assertEqual(first_value["excluded_orchestration_paths"], [LEDGER])
            self.assertEqual(first_value["entries"], second_value["entries"])
            self.assertNotIn(path_b64(LEDGER), {str(row["path_b64"]) for row in first_value["entries"] if isinstance(row, dict)})
            self.assertNotIn(git_index, {str(row["path_b64"]) for row in first_value["entries"] if isinstance(row, dict)})
            self.assertIsInstance(first_value.get("git_administration"), dict)
            with tarfile.open(first_archive, mode="r:") as archive:
                blob_names = {member.name for member in archive.getmembers()}
            with tarfile.open(second_archive, mode="r:") as archive:
                self.assertEqual(blob_names, {member.name for member in archive.getmembers()})

    def test_git_state_is_separate_from_product_and_rejects_staged_blob_change(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = ProductFixture(raw)
            manifest, _archive, captured = fixture.capture("frozen")
            first = read_json(manifest)
            (fixture.impl / "model" / "staged.txt").write_text("staged\n", encoding="utf-8")
            subprocess.run(["git", "add", "model/staged.txt"], cwd=fixture.impl, check=True)
            changed_manifest, _changed_archive, changed = fixture.capture("changed")
            second = read_json(changed_manifest)

            self.assertEqual(captured.returncode, 0, captured.stderr.decode("utf-8", "replace"))
            self.assertEqual(changed.returncode, 0, changed.stderr.decode("utf-8", "replace"))
            self.assertNotEqual(
                first["git_administration"]["state_sha256"],
                second["git_administration"]["state_sha256"],
            )

    def test_controlled_runner_environment_is_recorded_and_visible_to_child(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = ProductFixture(raw)
            fixture.write_minimal_freeze()
            probe = "import os;print(os.environ.get('GIT_OPTIONAL_LOCKS'));print(os.environ.get('LC_ALL'))"
            result = run_cli(
                "run-lane",
                "--lane",
                "F1",
                "--step",
                "1",
                "--cwd",
                str(fixture.impl),
                "--freeze",
                str(fixture.evidence / "freeze.json"),
                "--evidence-root",
                str(fixture.evidence),
                "--",
                sys.executable,
                "-B",
                "-c",
                probe,
            )
            record = read_json(fixture.evidence / "F1-runs" / "1.json")

            self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
            self.assertEqual((fixture.evidence / "F1-runs" / "1.stdout").read_text(), "0\nC\n")
            self.assertEqual(record["environment_contract"]["GIT_OPTIONAL_LOCKS"], "0")

    def test_product_manifest_rejects_additional_exclusion_and_v1_still_verifies(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = ProductFixture(raw)
            manifest, archive, captured = fixture.capture("product")
            self.assertEqual(captured.returncode, 0, captured.stderr.decode("utf-8", "replace"))
            output = fixture.base / "materialized"
            materialized = run_cli("materialize", "--manifest", str(manifest), "--archive", str(archive), "--output", str(output))
            verified = run_cli("verify-materialized", "--manifest", str(manifest), "--root", str(output))
            mutated = read_json(manifest)
            mutated["excluded_orchestration_paths"] = [LEDGER, "model/OPERATING-MODEL.json"]
            bad_manifest = fixture.evidence / "bad-exclusion.json"
            write_json(bad_manifest, mutated)
            rejected = run_cli("verify-materialized", "--manifest", str(bad_manifest), "--root", str(output))

            v1_manifest = fixture.evidence / "legacy-v1.json"
            v1_archive = fixture.evidence / "legacy-v1.tar"
            v1 = run_cli(
                "capture-worktree",
                "--root",
                str(fixture.impl),
                "--archive",
                str(v1_archive),
                "--manifest",
                str(v1_manifest),
                "--root-name",
                "qa",
            )
            v1_output = fixture.base / "legacy-v1-output"
            v1_materialized = run_cli("materialize", "--manifest", str(v1_manifest), "--archive", str(v1_archive), "--output", str(v1_output))
            v1_verified = run_cli("verify-materialized", "--manifest", str(v1_manifest), "--root", str(v1_output))

            self.assertEqual(materialized.returncode, 0, materialized.stderr.decode("utf-8", "replace"))
            self.assertEqual(verified.returncode, 0, verified.stderr.decode("utf-8", "replace"))
            self.assertEqual(rejected.returncode, 2)
            self.assertEqual(v1.returncode, 0, v1.stderr.decode("utf-8", "replace"))
            self.assertEqual(read_json(v1_manifest)["schema_version"], "agent-brain-tree/v1")
            self.assertEqual(v1_materialized.returncode, 0, v1_materialized.stderr.decode("utf-8", "replace"))
            self.assertEqual(v1_verified.returncode, 0, v1_verified.stderr.decode("utf-8", "replace"))

    def test_ledger_append_keeps_product_hash_stable_but_product_change_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = ProductFixture(raw)
            run = fixture.run_todo()
            run_record = read_json(fixture.evidence / "task-5-runs" / "1.json")
            fixture.ledger.write_text(
                fixture.ledger.read_text(encoding="utf-8") + '{"event":"after-run"}\n',
                encoding="utf-8",
            )
            sealed_after_ledger = fixture.seal_todo()
            receipt = read_json(fixture.evidence / "task-5-receipt.json")

            second = ProductFixture(str(fixture.base / "second"))
            second_run = second.run_todo()
            (second.impl / "model" / "product.txt").write_text("changed\n", encoding="utf-8")
            second_seal = second.seal_todo()

            self.assertEqual(run.returncode, 0, run.stderr.decode("utf-8", "replace"))
            self.assertEqual(sealed_after_ledger.returncode, 0, sealed_after_ledger.stderr.decode("utf-8", "replace"))
            self.assertEqual(run_record["implementation_sha256"], receipt["implementation_sha256"])
            self.assertEqual(run_record["implementation_product_sha256"], receipt["implementation_sha256"])
            self.assertEqual(second_run.returncode, 0, second_run.stderr.decode("utf-8", "replace"))
            self.assertEqual(second_seal.returncode, 2)

    def test_ledger_checkpoints_prove_append_only_suffix_and_reject_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = ProductFixture(raw)
            first = run_cli(
                "ledger-checkpoint",
                "--impl-root",
                str(fixture.impl),
                "--evidence-root",
                str(fixture.evidence),
                "--output",
                str(fixture.evidence / "ledger-1.json"),
                "--bytes-output",
                str(fixture.evidence / "ledger-1.jsonl"),
            )
            fixture.ledger.write_text(
                fixture.ledger.read_text(encoding="utf-8") + '{"event":"freeze"}\n',
                encoding="utf-8",
            )
            second = run_cli(
                "ledger-checkpoint",
                "--impl-root",
                str(fixture.impl),
                "--evidence-root",
                str(fixture.evidence),
                "--prior-checkpoint",
                str(fixture.evidence / "ledger-1.json"),
                "--output",
                str(fixture.evidence / "ledger-2.json"),
                "--bytes-output",
                str(fixture.evidence / "ledger-2.jsonl"),
            )
            verified = run_cli(
                "verify-ledger-checkpoint",
                "--checkpoint",
                str(fixture.evidence / "ledger-2.json"),
                "--evidence-root",
                str(fixture.evidence),
            )
            tampered_bytes = fixture.evidence / "ledger-2-tampered.jsonl"
            tampered_bytes.write_text('{"event":"replaced"}\n{"event":"freeze"}\n', encoding="utf-8")
            tampered = read_json(fixture.evidence / "ledger-2.json")
            tampered["ledger_bytes"] = {
                "root": "evidence",
                "path_b64": path_b64("ledger-2-tampered.jsonl"),
                "sha256": file_sha(tampered_bytes),
                "size": tampered_bytes.stat().st_size,
            }
            tampered["ledger_sha256"] = file_sha(tampered_bytes)
            tampered["ledger_size"] = tampered_bytes.stat().st_size
            tampered_path = fixture.evidence / "ledger-2-tampered.json"
            write_json(tampered_path, tampered)
            rejected = run_cli("verify-ledger-checkpoint", "--checkpoint", str(tampered_path), "--evidence-root", str(fixture.evidence))

            self.assertEqual(first.returncode, 0, first.stderr.decode("utf-8", "replace"))
            self.assertEqual(second.returncode, 0, second.stderr.decode("utf-8", "replace"))
            self.assertEqual(verified.returncode, 0, verified.stderr.decode("utf-8", "replace"))
            self.assertEqual(rejected.returncode, 2)

    def test_ledger_checkpoint_rejects_symlink_and_malformed_suffix_without_output(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = ProductFixture(raw)
            target = fixture.base / "outside-ledger.jsonl"
            target.write_text('{"event":"outside"}\n', encoding="utf-8")
            fixture.ledger.unlink()
            fixture.ledger.symlink_to(target)
            symlink_attempt = run_cli(
                "ledger-checkpoint",
                "--impl-root",
                str(fixture.impl),
                "--evidence-root",
                str(fixture.evidence),
                "--output",
                str(fixture.evidence / "symlink.json"),
                "--bytes-output",
                str(fixture.evidence / "symlink.jsonl"),
            )

            second = ProductFixture(str(fixture.base / "malformed"))
            first = run_cli(
                "ledger-checkpoint",
                "--impl-root",
                str(second.impl),
                "--evidence-root",
                str(second.evidence),
                "--output",
                str(second.evidence / "ledger-1.json"),
                "--bytes-output",
                str(second.evidence / "ledger-1.jsonl"),
            )
            second.ledger.write_bytes(second.ledger.read_bytes() + b'{"event":"unterminated"}')
            malformed = run_cli(
                "ledger-checkpoint",
                "--impl-root",
                str(second.impl),
                "--evidence-root",
                str(second.evidence),
                "--prior-checkpoint",
                str(second.evidence / "ledger-1.json"),
                "--output",
                str(second.evidence / "ledger-2.json"),
                "--bytes-output",
                str(second.evidence / "ledger-2.jsonl"),
            )

            self.assertEqual(symlink_attempt.returncode, 2)
            self.assertFalse((fixture.evidence / "symlink.json").exists())
            self.assertFalse((fixture.evidence / "symlink.jsonl").exists())
            self.assertEqual(target.read_text(encoding="utf-8"), '{"event":"outside"}\n')
            self.assertEqual(first.returncode, 0, first.stderr.decode("utf-8", "replace"))
            self.assertEqual(malformed.returncode, 2)
            self.assertFalse((second.evidence / "ledger-2.json").exists())
            self.assertFalse((second.evidence / "ledger-2.jsonl").exists())

    def test_ledger_checkpoint_verify_rejects_sidecar_symlink_checkpoint_symlink_and_escape_record(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = ProductFixture(raw)
            created = run_cli(
                "ledger-checkpoint",
                "--impl-root",
                str(fixture.impl),
                "--evidence-root",
                str(fixture.evidence),
                "--output",
                str(fixture.evidence / "ledger.json"),
                "--bytes-output",
                str(fixture.evidence / "ledger.jsonl"),
            )
            external = fixture.base / "external.jsonl"
            external.write_bytes((fixture.evidence / "ledger.jsonl").read_bytes())
            (fixture.evidence / "ledger.jsonl").unlink()
            os.symlink(external, fixture.evidence / "ledger.jsonl")
            sidecar_symlink = run_cli(
                "verify-ledger-checkpoint",
                "--checkpoint",
                str(fixture.evidence / "ledger.json"),
                "--evidence-root",
                str(fixture.evidence),
            )
            checkpoint_target = fixture.base / "checkpoint-target.json"
            checkpoint_target.write_bytes((fixture.evidence / "ledger.json").read_bytes())
            (fixture.evidence / "ledger.json").unlink()
            os.symlink(checkpoint_target, fixture.evidence / "ledger.json")
            checkpoint_symlink = run_cli(
                "verify-ledger-checkpoint",
                "--checkpoint",
                str(fixture.evidence / "ledger.json"),
                "--evidence-root",
                str(fixture.evidence),
            )

            fixture2 = ProductFixture(str(fixture.base / "second"))
            second = run_cli(
                "ledger-checkpoint",
                "--impl-root",
                str(fixture2.impl),
                "--evidence-root",
                str(fixture2.evidence),
                "--output",
                str(fixture2.evidence / "ledger.json"),
                "--bytes-output",
                str(fixture2.evidence / "ledger.jsonl"),
            )
            escaped = read_json(fixture2.evidence / "ledger.json")
            escaped["ledger_bytes"]["path_b64"] = path_b64("../outside.jsonl")
            write_json(fixture2.evidence / "escaped.json", escaped)
            escape_record = run_cli(
                "verify-ledger-checkpoint",
                "--checkpoint",
                str(fixture2.evidence / "escaped.json"),
                "--evidence-root",
                str(fixture2.evidence),
            )

            self.assertEqual(created.returncode, 0, created.stderr.decode("utf-8", "replace"))
            self.assertEqual(second.returncode, 0, second.stderr.decode("utf-8", "replace"))
            self.assertEqual(sidecar_symlink.returncode, 2)
            self.assertEqual(checkpoint_symlink.returncode, 2)
            self.assertEqual(escape_record.returncode, 2)

    def test_run_lane_rejects_unfrozen_product_cwd_before_execution(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = ProductFixture(raw)
            fixture.capture("implementation")
            fixture.write_minimal_freeze()
            other = ProductFixture(str(fixture.base / "other"))
            (other.impl / "model" / "product.txt").write_text("different\n", encoding="utf-8")
            rejected = run_cli(
                "run-lane",
                "--lane",
                "F1",
                "--step",
                "1",
                "--cwd",
                str(other.impl),
                "--freeze",
                str(fixture.evidence / "freeze.json"),
                "--evidence-root",
                str(fixture.evidence),
                "--",
                "python3",
                "-B",
                "-c",
                f"open({str(fixture.evidence / 'should-not-run')!r}, 'w').write('bad')",
            )

            self.assertEqual(rejected.returncode, 2)
            self.assertFalse((fixture.evidence / "F1-runs").exists())
            self.assertFalse((fixture.evidence / "should-not-run").exists())

    def test_verify_freeze_rejects_unsealed_evidence_extra_and_freeze_materializes_product(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = ProductFixture(raw)
            approved = fixture.approve_wave4()
            frozen = fixture.freeze_with_wave_checkpoint()
            value = read_json(fixture.evidence / "freeze.json")
            implementation = value.get("implementation")
            if not isinstance(implementation, dict):
                raise AssertionError("freeze lacks implementation object")
            materialized = run_cli(
                "materialize",
                "--manifest",
                str(fixture.evidence / str(implementation["manifest"])),
                "--archive",
                str(fixture.evidence / str(implementation["archive"])),
                "--output",
                str(fixture.base / "materialized"),
            )
            (fixture.evidence / "unsealed-extra.txt").write_text("extra\n", encoding="utf-8")
            rejected = run_cli(
                "verify-freeze",
                "--freeze",
                str(fixture.evidence / "freeze.json"),
                "--impl-root",
                str(fixture.impl),
                "--evidence-root",
                str(fixture.evidence),
                "--recompute",
                str(fixture.evidence / "recompute.json"),
            )

            self.assertEqual(approved.returncode, 0, approved.stderr.decode("utf-8", "replace"))
            self.assertEqual(frozen.returncode, 0, frozen.stderr.decode("utf-8", "replace"))
            self.assertEqual(materialized.returncode, 0, materialized.stderr.decode("utf-8", "replace"))
            self.assertEqual(rejected.returncode, 2)

    def test_run_lane_reserves_step_before_child_execution(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = ProductFixture(raw)
            fixture.write_minimal_freeze()
            side_effect = fixture.evidence / "lane-side-effect.txt"
            code = (
                "import pathlib,sys,time;"
                f"p=pathlib.Path({str(side_effect)!r});"
                "time.sleep(0.2);"
                "p.write_text(p.read_text()+'x' if p.exists() else 'x')"
            )
            command = [
                sys.executable,
                "-B",
                str(CLI),
                "run-lane",
                "--lane",
                "F1",
                "--step",
                "1",
                "--cwd",
                str(fixture.impl),
                "--freeze",
                str(fixture.evidence / "freeze.json"),
                "--evidence-root",
                str(fixture.evidence),
                "--",
                sys.executable,
                "-B",
                "-c",
                code,
            ]

            first = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            time.sleep(0.05)
            second = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            first_out, first_err = first.communicate(timeout=10)
            second_out, second_err = second.communicate(timeout=10)
            statuses = sorted((first.returncode, second.returncode))

            self.assertEqual(statuses, [0, 2], (first_out, first_err, second_out, second_err))
            self.assertEqual(side_effect.read_text(encoding="utf-8"), "x")

    def test_finalize_binds_terminal_ledger_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = ProductFixture(raw)
            fixture.add_manual_qa_files()
            connected_brain = fixture.connected_brain()
            approved_wave = fixture.approve_wave4()
            frozen = fixture.freeze_with_wave_checkpoint()
            lane_results = [
                fixture.create_lane("F1", "f1-plan-compliance.json"),
                fixture.create_lane("F2", "f2-code-quality.json"),
                fixture.create_manual_qa_f3_lane(connected_brain),
                fixture.create_lane("F4", "f4-scope-fidelity.json"),
            ]
            review = fixture.evidence / "final-review.json"
            approval = fixture.evidence / "final-approval.json"
            message = fixture.evidence / "approval-message.txt"
            missing_prior = run_cli(
                "final-review",
                "--freeze",
                str(fixture.evidence / "freeze.json"),
                "--lanes",
                str(fixture.evidence / "f1-plan-compliance.json"),
                str(fixture.evidence / "f2-code-quality.json"),
                str(fixture.evidence / "f3-manual-qa.json"),
                str(fixture.evidence / "f4-scope-fidelity.json"),
                "--output",
                str(review),
                "--impl-root",
                str(fixture.impl),
                "--evidence-root",
                str(fixture.evidence),
            )
            reviewed = run_cli(
                "final-review",
                "--freeze",
                str(fixture.evidence / "freeze.json"),
                "--lanes",
                str(fixture.evidence / "f1-plan-compliance.json"),
                str(fixture.evidence / "f2-code-quality.json"),
                str(fixture.evidence / "f3-manual-qa.json"),
                str(fixture.evidence / "f4-scope-fidelity.json"),
                "--output",
                str(review),
                "--impl-root",
                str(fixture.impl),
                "--evidence-root",
                str(fixture.evidence),
                "--prior-ledger-checkpoint",
                str(fixture.evidence / "freeze.ledger-checkpoint.json"),
            )
            message.write_text(f"APPROVE final {file_sha(review)}\n", encoding="utf-8")
            approved = run_cli("final-approve", "--review", str(review), "--message", str(message), "--output", str(approval))
            fixture.ledger.write_text(
                fixture.ledger.read_text(encoding="utf-8") + '{"event":"completion-pending"}\n',
                encoding="utf-8",
            )
            completed = run_cli(
                "finalize",
                "--review",
                str(review),
                "--approval",
                str(approval),
                "--evidence-root",
                str(fixture.evidence),
                "--impl-root",
                str(fixture.impl),
                "--prior-ledger-checkpoint",
                str(fixture.evidence / "final-review.ledger-checkpoint.json"),
                "--output",
                str(fixture.evidence / "completion.json"),
            )
            verified = run_cli(
                "verify",
                "--completion",
                str(fixture.evidence / "completion.json"),
                "--evidence-root",
                str(fixture.evidence),
            )
            completion = read_json(fixture.evidence / "completion.json")

            self.assertEqual(approved_wave.returncode, 0, approved_wave.stderr.decode("utf-8", "replace"))
            self.assertEqual(frozen.returncode, 0, frozen.stderr.decode("utf-8", "replace"))
            for lane_result in lane_results:
                self.assertEqual(lane_result.returncode, 0, lane_result.stderr.decode("utf-8", "replace"))
            self.assertEqual(missing_prior.returncode, 2)
            self.assertEqual(reviewed.returncode, 0, reviewed.stderr.decode("utf-8", "replace"))
            self.assertEqual(approved.returncode, 0, approved.stderr.decode("utf-8", "replace"))
            self.assertEqual(completed.returncode, 0, completed.stderr.decode("utf-8", "replace"))
            self.assertEqual(verified.returncode, 0, verified.stderr.decode("utf-8", "replace"))
            self.assertIsInstance(completion["ledger_checkpoint"], dict)

    def test_literal_f3_manual_qa_lane_reaches_final_review_and_binds_runs(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = ProductFixture(raw)
            fixture.add_manual_qa_files()
            connected_brain = fixture.connected_brain()
            approved_wave = fixture.approve_wave4()
            frozen = fixture.freeze_with_wave_checkpoint()
            f1 = fixture.create_lane("F1", "f1-plan-compliance.json")
            f2 = fixture.create_lane("F2", "f2-code-quality.json")
            f3 = fixture.create_manual_qa_f3_lane(connected_brain)
            f4 = fixture.create_lane("F4", "f4-scope-fidelity.json")
            reviewed = run_cli(
                "final-review",
                "--freeze",
                str(fixture.evidence / "freeze.json"),
                "--lanes",
                str(fixture.evidence / "f1-plan-compliance.json"),
                str(fixture.evidence / "f2-code-quality.json"),
                str(fixture.evidence / "f3-manual-qa.json"),
                str(fixture.evidence / "f4-scope-fidelity.json"),
                "--output",
                str(fixture.evidence / "final-review.json"),
                "--impl-root",
                str(fixture.impl),
                "--evidence-root",
                str(fixture.evidence),
                "--prior-ledger-checkpoint",
                str(fixture.evidence / "freeze.ledger-checkpoint.json"),
            )
            lane = read_json(fixture.evidence / "f3-manual-qa.json")
            runs = sorted((fixture.evidence / "F3-runs").glob("*.json"), key=lambda path: int(path.stem))
            rerun = fixture.create_manual_qa_f3_lane(connected_brain)
            rerun_runs = sorted((fixture.evidence / "F3-runs").glob("*.json"), key=lambda path: int(path.stem))

            self.assertEqual(approved_wave.returncode, 0, approved_wave.stderr.decode("utf-8", "replace"))
            self.assertEqual(frozen.returncode, 0, frozen.stderr.decode("utf-8", "replace"))
            self.assertEqual(f1.returncode, 0, f1.stderr.decode("utf-8", "replace"))
            self.assertEqual(f2.returncode, 0, f2.stderr.decode("utf-8", "replace"))
            self.assertEqual(f3.returncode, 0, f3.stderr.decode("utf-8", "replace"))
            self.assertEqual(f4.returncode, 0, f4.stderr.decode("utf-8", "replace"))
            self.assertEqual(reviewed.returncode, 0, reviewed.stderr.decode("utf-8", "replace"))
            self.assertEqual(lane["schema_version"], "agent-brain-final-lane/v1")
            self.assertEqual(lane["lane"], "F3")
            self.assertEqual(lane["run_count"], len(runs))
            self.assertGreaterEqual(len(runs), 6)
            self.assertEqual([read_json(path)["exit_status"] for path in runs], [0] * len(runs))
            self.assertEqual(rerun.returncode, 2)
            self.assertEqual([path.name for path in rerun_runs], [path.name for path in runs])
            self.assertTrue(all((fixture.evidence / "F3-runs" / f"{index}.owner").exists() for index in range(1, len(runs) + 1)))
            self.assertIsInstance(lane.get("artifact"), dict)
            self.assertIsInstance(lane.get("artifact_manifest"), dict)
            self.assertEqual(lane.get("parity"), {
                "connected_brain_equal": True,
                "frozen_equal": True,
                "source_equal": True,
                "temp_brain_equal": True,
            })

    def test_final_review_rejects_removed_or_tampered_f3_run_records(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = ProductFixture(raw)
            fixture.add_manual_qa_files()
            connected_brain = fixture.connected_brain()
            approved_wave = fixture.approve_wave4()
            frozen = fixture.freeze_with_wave_checkpoint()
            f1 = fixture.create_lane("F1", "f1-plan-compliance.json")
            f2 = fixture.create_lane("F2", "f2-code-quality.json")
            f3 = fixture.create_manual_qa_f3_lane(connected_brain)
            f4 = fixture.create_lane("F4", "f4-scope-fidelity.json")
            run_paths = sorted((fixture.evidence / "F3-runs").glob("*.json"), key=lambda path: int(path.stem))

            self.assertEqual(approved_wave.returncode, 0, approved_wave.stderr.decode("utf-8", "replace"))
            self.assertEqual(frozen.returncode, 0, frozen.stderr.decode("utf-8", "replace"))
            for result in (f1, f2, f3, f4):
                self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))

            for index, path in enumerate(run_paths, start=1):
                original = path.read_bytes()
                path.unlink()
                removed = run_cli(
                    "final-review",
                    "--freeze",
                    str(fixture.evidence / "freeze.json"),
                    "--lanes",
                    str(fixture.evidence / "f1-plan-compliance.json"),
                    str(fixture.evidence / "f2-code-quality.json"),
                    str(fixture.evidence / "f3-manual-qa.json"),
                    str(fixture.evidence / "f4-scope-fidelity.json"),
                    "--output",
                    str(fixture.evidence / f"final-review-removed-{index}.json"),
                    "--impl-root",
                    str(fixture.impl),
                    "--evidence-root",
                    str(fixture.evidence),
                    "--prior-ledger-checkpoint",
                    str(fixture.evidence / "freeze.ledger-checkpoint.json"),
                )
                path.write_bytes(original)
                tampered_value = read_json(path)
                tampered_value["exit_status"] = 1
                write_json(path, tampered_value)
                tampered = run_cli(
                    "final-review",
                    "--freeze",
                    str(fixture.evidence / "freeze.json"),
                    "--lanes",
                    str(fixture.evidence / "f1-plan-compliance.json"),
                    str(fixture.evidence / "f2-code-quality.json"),
                    str(fixture.evidence / "f3-manual-qa.json"),
                    str(fixture.evidence / "f4-scope-fidelity.json"),
                    "--output",
                    str(fixture.evidence / f"final-review-tampered-{index}.json"),
                    "--impl-root",
                    str(fixture.impl),
                    "--evidence-root",
                    str(fixture.evidence),
                    "--prior-ledger-checkpoint",
                    str(fixture.evidence / "freeze.ledger-checkpoint.json"),
                )
                path.write_bytes(original)

                self.assertEqual(removed.returncode, 2, removed.stderr.decode("utf-8", "replace"))
                self.assertEqual(tampered.returncode, 2, tampered.stderr.decode("utf-8", "replace"))

    def test_checkpoint_verifier_rejects_lifecycle_phase_without_required_prior(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = ProductFixture(raw)
            created = run_cli(
                "ledger-checkpoint",
                "--impl-root",
                str(fixture.impl),
                "--evidence-root",
                str(fixture.evidence),
                "--output",
                str(fixture.evidence / "root.json"),
                "--bytes-output",
                str(fixture.evidence / "root.jsonl"),
            )
            root = read_json(fixture.evidence / "root.json")
            root["phase"] = "final-freeze"
            forged = fixture.evidence / "forged-final-freeze.json"
            write_json(forged, root)
            rejected = run_cli(
                "verify-ledger-checkpoint",
                "--checkpoint",
                str(forged),
                "--evidence-root",
                str(fixture.evidence),
            )

            self.assertEqual(created.returncode, 0, created.stderr.decode("utf-8", "replace"))
            self.assertEqual(rejected.returncode, 2)

    def test_public_lifecycle_rejects_fabricated_wave_and_null_completion_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = ProductFixture(raw)
            receipt = fixture.evidence / "wave-4-receipt.json"
            message = fixture.evidence / "wave-4-approval-message.txt"
            write_json(receipt, {"schema_version": "agent-brain-wave-receipt/v1", "wave": 4})
            message.write_text(f"APPROVE wave 4 {file_sha(receipt)}\n", encoding="utf-8")
            approve = run_cli(
                "approve-wave",
                "--wave",
                "4",
                "--receipt",
                str(receipt),
                "--message",
                str(message),
                "--output",
                str(fixture.evidence / "wave-4-approval.json"),
                "--impl-root",
                str(fixture.impl),
                "--evidence-root",
                str(fixture.evidence),
            )
            review = fixture.evidence / "review.json"
            approval = fixture.evidence / "approval.json"
            completion = fixture.evidence / "completion.json"
            write_json(review, {"schema_version": "agent-brain-final-review/v1"})
            write_json(approval, {"review_sha256": file_sha(review), "schema_version": "agent-brain-final-approval/v1"})
            finalize = run_cli(
                "finalize",
                "--review",
                str(review),
                "--approval",
                str(approval),
                "--evidence-root",
                str(fixture.evidence),
                "--output",
                str(completion),
            )

            self.assertEqual(approve.returncode, 2)
            self.assertEqual(finalize.returncode, 2)

    def test_closure_v2_approve_wave_and_freeze_complete_public_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = ProductFixture(raw)
            plan, draft, seal = fixture.create_wave4_closure_v2()
            approved = fixture.approve_wave4_closure_v2()
            self.assertEqual(approved.returncode, 0, approved.stderr.decode("utf-8", "replace"))
            closure = read_json(fixture.evidence / "wave-4-closure-v2.json")
            approval = read_json(fixture.evidence / "wave-4-approval.json")
            verified = run_cli("verify-wave", "--wave", "4", "--evidence-root", str(fixture.evidence))
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

            provenance = closure.get("approval_required")
            self.assertIsInstance(provenance, dict)
            self.assertEqual(
                set(provenance),
                {"draft", "independent_gate", "review_seal", "tooling_review"},
            )
            self.assertEqual(provenance["draft"]["role"], "reviewed-draft")
            self.assertEqual(provenance["review_seal"]["role"], "review-seal")
            self.assertEqual(provenance["tooling_review"]["role"], "tooling-review")
            self.assertEqual(provenance["independent_gate"]["role"], "independent-gate-report")
            self.assertEqual(provenance["tooling_review"]["schema"], "agent-brain-tooling-review-summary/v1")
            self.assertEqual(provenance["independent_gate"]["schema"], "agent-brain-independent-gate-summary/v1")
            tooling_summary = read_json(Path(str(provenance["tooling_review"]["path"])))
            gate_summary = read_json(Path(str(provenance["independent_gate"]["path"])))
            self.assertEqual(tooling_summary["verdict"], "APPROVE")
            self.assertEqual(tooling_summary["findings"], [])
            self.assertEqual(tooling_summary["blockers"], [])
            self.assertEqual(gate_summary["verdict"], "CONFIRMED")
            self.assertEqual(gate_summary["findings"], [])
            self.assertEqual(gate_summary["blockers"], [])
            self.assertEqual(tooling_summary["report"], file_ref(fixture.evidence / "tooling-review.json"))
            self.assertEqual(gate_summary["report"], file_ref(fixture.evidence / "independent-gate-report.json"))
            self.assertEqual(approval["receipt_schema"], "agent-brain-wave-closure-v2")
            self.assertEqual(approval["receipt_sha256"], file_sha(fixture.evidence / "wave-4-closure-v2.json"))
            self.assertEqual(approval["message_path"], str((fixture.evidence / "wave-4-closure-v2-approval-message.txt").resolve()))
            self.assertEqual(approval["message_sha256"], file_sha(fixture.evidence / "wave-4-closure-v2-approval-message.txt"))
            self.assertEqual(
                base64.b64decode(str(approval["message_bytes_b64"])),
                (fixture.evidence / "wave-4-closure-v2-approval-message.txt").read_bytes(),
            )
            self.assertIs(approval["message_lf"], True)
            self.assertIsInstance(approval["ledger_checkpoint"], dict)
            self.assertEqual(verified.returncode, 0, verified.stderr.decode("utf-8", "replace"))
            self.assertEqual(frozen.returncode, 0, frozen.stderr.decode("utf-8", "replace"))

    def test_successor_plan_review_binds_current_plan_draft_prior_and_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = ProductFixture(raw)
            prior_plan, draft, prior_seal, seal = fixture.create_successor_plan_review()
            verified = run_cli(
                "verify-plan-review",
                "--seal",
                str(seal),
                "--evidence-root",
                str(fixture.evidence),
                "--brain-root",
                str(draft.parents[2]),
                "--implementation-root",
                str(fixture.impl),
            )
            v1_regression = run_cli(
                "verify-plan-review",
                "--seal",
                str(prior_seal),
                "--evidence-root",
                str(fixture.evidence),
                "--brain-root",
                str(draft.parents[2]),
                "--implementation-root",
                str(fixture.impl),
            )
            value = read_json(seal)

            self.assertEqual(verified.returncode, 0, verified.stderr.decode("utf-8", "replace"))
            self.assertEqual(v1_regression.returncode, 0, v1_regression.stderr.decode("utf-8", "replace"))
            self.assertEqual(value["schema_version"], "agent-brain-successor-plan-review/v1")
            self.assertEqual(value["plan_sha256"], file_sha(fixture.plan))
            self.assertEqual(value["draft_sha256"], file_sha(draft))
            self.assertEqual(value["prior_plan_sha256"], file_sha(prior_plan))
            self.assertEqual(value["prior_draft_sha256"], file_sha(draft))
            self.assertNotEqual(value["plan_sha256"], value["prior_plan_sha256"])
            self.assertEqual(value["plan"]["root"], "implementation")
            self.assertEqual(value["draft"]["root"], "brain")
            self.assertEqual(value["prior_seal"]["root"], "evidence")
            self.assertEqual(value["reviewers"]["momus"]["verdict"], "OKAY")
            self.assertEqual(value["reviewers"]["independent"]["verdict"], "OKAY")

    def test_successor_plan_review_rejects_rebound_prior_v1_records(self) -> None:
        for name in ("parent-traversal", "intermediate-symlink", "record-hash-substitution"):
            with self.subTest(name=name):
                with tempfile.TemporaryDirectory() as raw:
                    fixture = ProductFixture(raw)
                    prior_plan, draft, prior_seal, seal = fixture.create_successor_plan_review()
                    prior = read_json(prior_seal)
                    if name == "parent-traversal":
                        external_plan = fixture.base / "external-plan.md"
                        external_draft = fixture.base / "external-draft.md"
                        external_plan.write_bytes(prior_plan.read_bytes())
                        external_draft.write_bytes(draft.read_bytes())
                        paths = {
                            "plan": ("../external-plan.md", external_plan),
                            "draft": ("../external-draft.md", external_draft),
                        }
                    elif name == "intermediate-symlink":
                        external = fixture.base / "external"
                        external.mkdir()
                        external_plan = external / "plan.md"
                        external_plan.write_bytes(prior_plan.read_bytes())
                        (draft.parents[2] / "linked").symlink_to(external, target_is_directory=True)
                        paths = {
                            "plan": ("linked/plan.md", external_plan),
                            "draft": (".omo/drafts/draft.md", draft),
                        }
                    else:
                        substituted_plan = draft.parents[2] / "substituted-plan.md"
                        substituted_plan.write_text("not the reviewed plan\n", encoding="utf-8")
                        paths = {
                            "plan": ("substituted-plan.md", substituted_plan),
                            "draft": (".omo/drafts/draft.md", draft),
                        }
                    for role, (relative, path) in paths.items():
                        prior[role] = {
                            "path_b64": path_b64(relative),
                            "root": "brain",
                            "sha256": file_sha(path),
                            "size": path.stat().st_size,
                        }
                    write_json(prior_seal, prior)
                    successor = read_json(seal)
                    successor["prior_seal_sha256"] = file_sha(prior_seal)
                    successor["prior_seal"] = {
                        "path_b64": path_b64("plan-review/review-seal.json"),
                        "root": "evidence",
                        "sha256": file_sha(prior_seal),
                        "size": prior_seal.stat().st_size,
                    }
                    write_json(seal, successor)

                    result = run_cli(
                        "verify-plan-review",
                        "--seal",
                        str(seal),
                        "--evidence-root",
                        str(fixture.evidence),
                        "--brain-root",
                        str(draft.parents[2]),
                        "--implementation-root",
                        str(fixture.impl),
                    )

                    self.assertEqual(result.returncode, 2, result.stderr.decode("utf-8", "replace"))

    def test_successor_plan_review_creation_rejects_rebound_prior_v1_records(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = ProductFixture(raw)
            prior_plan, draft, prior_seal = fixture.create_plan_review()
            external_plan = fixture.base / "external-plan.md"
            external_draft = fixture.base / "external-draft.md"
            external_plan.write_bytes(prior_plan.read_bytes())
            external_draft.write_bytes(draft.read_bytes())
            prior = read_json(prior_seal)
            for role, path in (("plan", external_plan), ("draft", external_draft)):
                prior[role] = {
                    "path_b64": path_b64(f"../{path.name}"),
                    "root": "brain",
                    "sha256": file_sha(path),
                    "size": path.stat().st_size,
                }
            write_json(prior_seal, prior)
            fixture.plan.write_text(
                fixture.plan.read_text(encoding="utf-8") + "- [x] successor change\n",
                encoding="utf-8",
            )
            review_root = fixture.evidence / "successor-plan-review"
            review_root.mkdir()
            plan_sha = file_sha(fixture.plan)
            for reviewer, launch in (
                ("momus", "successor-momus-launch"),
                ("independent", "successor-independent-launch"),
            ):
                (review_root / f"{reviewer}.txt").write_text(
                    json.dumps(
                        {
                            "launch_id": launch,
                            "plan_sha256": plan_sha,
                            "reviewer": reviewer,
                            "round_id": "successor-round-1",
                        }
                    )
                    + "\nOKAY\n",
                    encoding="utf-8",
                )

            result = run_cli(
                "successor-plan-review",
                "--plan",
                str(fixture.plan),
                "--impl-root",
                str(fixture.impl),
                "--draft",
                str(draft),
                "--brain-root",
                str(draft.parents[2]),
                "--prior-seal",
                str(prior_seal),
                "--evidence-root",
                str(fixture.evidence),
                "--momus-receipt",
                str(review_root / "momus.txt"),
                "--independent-receipt",
                str(review_root / "independent.txt"),
                "--output",
                str(review_root / "review-seal.json"),
            )

            self.assertEqual(result.returncode, 2, result.stderr.decode("utf-8", "replace"))

    def test_successor_plan_review_rejects_noncanonical_prior_v1_schema(self) -> None:
        for name, mutation in (
            ("created-at-integer", lambda value: value.__setitem__("created_at", 0)),
            ("plan-size-bool", lambda value: value["plan"].__setitem__("size", True)),
            ("plan-root-rebind", lambda value: value["plan"].__setitem__(
                "root", "evidence"
            )),
            ("reviewer-extra-key", lambda value: value["reviewers"]["momus"].__setitem__(
                "role", "momus"
            )),
            ("reviewer-launch-integer", lambda value: value["reviewers"]["momus"].__setitem__(
                "launch_id", 0
            )),
            ("receipt-root-rebind", lambda value: value["reviewers"]["momus"]["receipt"].__setitem__(
                "root", "brain"
            )),
        ):
            with self.subTest(name=name):
                with tempfile.TemporaryDirectory() as raw:
                    fixture = ProductFixture(raw)
                    _prior_plan, draft, prior_seal, seal = fixture.create_successor_plan_review()
                    prior = read_json(prior_seal)
                    mutation(prior)
                    write_json(prior_seal, prior)
                    successor = read_json(seal)
                    successor["prior_seal_sha256"] = file_sha(prior_seal)
                    successor["prior_seal"] = {
                        "path_b64": path_b64("plan-review/review-seal.json"),
                        "root": "evidence",
                        "sha256": file_sha(prior_seal),
                        "size": prior_seal.stat().st_size,
                    }
                    write_json(seal, successor)

                    result = run_cli(
                        "verify-plan-review",
                        "--seal",
                        str(seal),
                        "--evidence-root",
                        str(fixture.evidence),
                        "--brain-root",
                        str(draft.parents[2]),
                        "--implementation-root",
                        str(fixture.impl),
                    )

                    self.assertEqual(result.returncode, 2, result.stderr.decode("utf-8", "replace"))

    def test_successor_plan_review_rejects_noncanonical_field_types(self) -> None:
        for name, mutation in (
            ("created-at-integer", lambda value: value.__setitem__("created_at", 0)),
            ("round-id-integer", lambda value: value.__setitem__("round_id", 0)),
            ("record-size-bool", lambda value: value["plan"].__setitem__("size", True)),
            ("record-hash-uppercase", lambda value: value["draft"].__setitem__(
                "sha256", str(value["draft"]["sha256"]).upper()
            )),
            ("record-root-integer", lambda value: value["draft"].__setitem__("root", 0)),
            ("record-path-integer", lambda value: value["prior_seal"].__setitem__(
                "path_b64", 0
            )),
            ("record-extra-key", lambda value: value["prior_seal"].__setitem__("extra", "value")),
            ("launch-id-integer", lambda value: value["reviewers"]["momus"].__setitem__(
                "launch_id", 0
            )),
        ):
            with self.subTest(name=name):
                with tempfile.TemporaryDirectory() as raw:
                    fixture = ProductFixture(raw)
                    _prior_plan, draft, _prior_seal, seal = fixture.create_successor_plan_review()
                    value = read_json(seal)
                    mutation(value)
                    tampered = fixture.evidence / f"{name}.json"
                    write_json(tampered, value)

                    result = run_cli(
                        "verify-plan-review",
                        "--seal",
                        str(tampered),
                        "--evidence-root",
                        str(fixture.evidence),
                        "--brain-root",
                        str(draft.parents[2]),
                        "--implementation-root",
                        str(fixture.impl),
                    )

                    self.assertEqual(result.returncode, 2, result.stderr.decode("utf-8", "replace"))

    def test_successor_plan_review_rejects_semantic_substitutions(self) -> None:
        for name in (
            "same-launch",
            "receipt-plan",
            "receipt-round",
            "non-okay",
            "prior-draft",
            "wrong-root",
            "same-plan",
        ):
            with self.subTest(name=name):
                with tempfile.TemporaryDirectory() as raw:
                    fixture = ProductFixture(raw)
                    prior_plan, draft, prior_seal, seal = fixture.create_successor_plan_review()
                    if name in {"same-launch", "receipt-plan", "receipt-round", "non-okay"}:
                        receipt = fixture.evidence / "successor-plan-review" / "independent.txt"
                        lines = receipt.read_text(encoding="utf-8").splitlines()
                        header = json.loads(lines[0])
                        if name == "same-launch":
                            header["launch_id"] = "successor-momus-launch"
                        elif name == "receipt-plan":
                            header["plan_sha256"] = "0" * 64
                        elif name == "receipt-round":
                            header["round_id"] = "other-round"
                        else:
                            lines[-1] = "APPROVE"
                        lines[0] = json.dumps(header)
                        receipt.write_text("\n".join(lines) + "\n", encoding="utf-8")
                        result = run_cli(
                            "verify-plan-review",
                            "--seal",
                            str(seal),
                            "--evidence-root",
                            str(fixture.evidence),
                            "--brain-root",
                            str(draft.parents[2]),
                            "--implementation-root",
                            str(fixture.impl),
                        )
                    elif name == "prior-draft":
                        draft.write_text(draft.read_text(encoding="utf-8") + "changed\n", encoding="utf-8")
                        result = run_cli(
                            "verify-plan-review",
                            "--seal",
                            str(seal),
                            "--evidence-root",
                            str(fixture.evidence),
                            "--brain-root",
                            str(draft.parents[2]),
                            "--implementation-root",
                            str(fixture.impl),
                        )
                    elif name == "same-plan":
                        review_root = fixture.evidence / "same-plan-successor"
                        review_root.mkdir()
                        plan_sha = file_sha(prior_plan)
                        for reviewer, launch in (("momus", "m2"), ("independent", "i2")):
                            (review_root / f"{reviewer}.txt").write_text(
                                json.dumps(
                                    {
                                        "launch_id": launch,
                                        "plan_sha256": plan_sha,
                                        "reviewer": reviewer,
                                        "round_id": "successor-round-2",
                                    }
                                )
                                + "\nOKAY\n",
                                encoding="utf-8",
                            )
                        result = run_cli(
                            "successor-plan-review",
                            "--plan",
                            str(prior_plan),
                            "--impl-root",
                            str(prior_plan.parents[2]),
                            "--draft",
                            str(draft),
                            "--brain-root",
                            str(draft.parents[2]),
                            "--prior-seal",
                            str(prior_seal),
                            "--evidence-root",
                            str(fixture.evidence),
                            "--momus-receipt",
                            str(review_root / "momus.txt"),
                            "--independent-receipt",
                            str(review_root / "independent.txt"),
                            "--output",
                            str(review_root / "review-seal.json"),
                        )
                    else:
                        value = read_json(seal)
                        value["plan"]["root"] = "brain"
                        tampered = fixture.evidence / "wrong-root-successor.json"
                        write_json(tampered, value)
                        result = run_cli(
                            "verify-plan-review",
                            "--seal",
                            str(tampered),
                            "--evidence-root",
                            str(fixture.evidence),
                            "--brain-root",
                            str(draft.parents[2]),
                            "--implementation-root",
                            str(fixture.impl),
                        )

                    self.assertEqual(result.returncode, 2, result.stderr.decode("utf-8", "replace"))

    def test_closure_v2_and_freeze_accept_successor_plan_review_for_active_plan(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = ProductFixture(raw)
            plan, draft, seal = fixture.create_wave4_closure_v2(successor_review=True)
            approved = fixture.approve_wave4_closure_v2()
            closure = read_json(fixture.evidence / "wave-4-closure-v2.json")
            review = read_json(seal)
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

            self.assertEqual(review["schema_version"], "agent-brain-successor-plan-review/v1")
            self.assertEqual(closure["active_plan"]["path"], str(plan))
            self.assertEqual(closure["active_plan"]["sha256"], review["plan_sha256"])
            self.assertEqual(closure["approval_required"]["review_seal"]["hash"], file_sha(seal))
            self.assertEqual(approved.returncode, 0, approved.stderr.decode("utf-8", "replace"))
            self.assertEqual(frozen.returncode, 0, frozen.stderr.decode("utf-8", "replace"))

    def test_closure_v2_approval_rejects_wrong_wave_duplicate_legacy_and_tamper_matrix(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = ProductFixture(raw)
            fixture.create_wave4_closure_v2()
            receipt = fixture.evidence / "wave-4-closure-v2.json"
            wrong_message = fixture.evidence / "wrong-wave-message.txt"
            wrong_message.write_text(f"APPROVE wave 3 {file_sha(receipt)}\n", encoding="utf-8")
            wrong_wave = run_cli(
                "approve-wave",
                "--wave",
                "3",
                "--receipt",
                str(receipt),
                "--message",
                str(wrong_message),
                "--output",
                str(fixture.evidence / "wave-3-approval.json"),
                "--impl-root",
                str(fixture.impl),
                "--evidence-root",
                str(fixture.evidence),
            )
            closure = read_json(receipt)
            receipts = closure.get("accepted_task_receipts")
            if not isinstance(receipts, list):
                raise AssertionError("closure lacks receipts")
            receipts[1] = receipts[0]
            duplicate = fixture.evidence / "wave-4-closure-v2-duplicate.json"
            write_json(duplicate, closure)
            duplicate_message = fixture.evidence / "duplicate-message.txt"
            duplicate_message.write_text(f"APPROVE wave 4 {file_sha(duplicate)}\n", encoding="utf-8")
            duplicate_approval = run_cli(
                "approve-wave",
                "--wave",
                "4",
                "--receipt",
                str(duplicate),
                "--message",
                str(duplicate_message),
                "--output",
                str(fixture.evidence / "duplicate-approval.json"),
                "--impl-root",
                str(fixture.impl),
                "--evidence-root",
                str(fixture.evidence),
            )
            legacy = ProductFixture(str(Path(raw) / "legacy"))
            legacy.create_wave4_closure_v2(approval_required=False)
            legacy_approval = legacy.approve_wave4_closure_v2()

            self.assertEqual(wrong_wave.returncode, 2)
            self.assertEqual(duplicate_approval.returncode, 2)
            self.assertEqual(legacy_approval.returncode, 2)

    def test_verify_wave_rejects_closure_v2_approval_swaps_and_forged_validation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = ProductFixture(raw)
            fixture.create_wave4_closure_v2()
            approved = fixture.approve_wave4_closure_v2()
            self.assertEqual(approved.returncode, 0, approved.stderr.decode("utf-8", "replace"))
            original_approval = read_json(fixture.evidence / "wave-4-approval.json")
            original_closure = read_json(fixture.evidence / "wave-4-closure-v2.json")
            cases: dict[str, dict[str, JsonValue]] = {
                "hash": {**original_approval, "receipt_sha256": "0" * 64},
                "schema": {**original_approval, "receipt_schema": "agent-brain-wave-receipt/v1"},
                "path": {**original_approval, "receipt_path": str((fixture.evidence / "missing.json").resolve())},
            }
            for name, value in cases.items():
                with self.subTest(name=name):
                    write_json(fixture.evidence / "wave-4-approval.json", value)
                    verified = run_cli("verify-wave", "--wave", "4", "--evidence-root", str(fixture.evidence))
                    self.assertEqual(verified.returncode, 2)
            forged_closure = original_closure
            receipts = forged_closure.get("accepted_task_receipts")
            if not isinstance(receipts, list):
                raise AssertionError("closure lacks receipts")
            receipts[1] = receipts[0]
            write_json(fixture.evidence / "wave-4-closure-v2.json", forged_closure)
            forged_message = fixture.evidence / "wave-4-approval-forged-message.txt"
            forged_message.write_text(
                f"APPROVE wave 4 {file_sha(fixture.evidence / 'wave-4-closure-v2.json')}\n",
                encoding="utf-8",
            )
            forged = {
                **original_approval,
                "message_bytes_b64": base64.b64encode(forged_message.read_bytes()).decode("ascii"),
                "message_path": str(forged_message.resolve()),
                "message_sha256": file_sha(forged_message),
                "message_size": forged_message.stat().st_size,
                "receipt_sha256": file_sha(fixture.evidence / "wave-4-closure-v2.json"),
                "receipt_size": (fixture.evidence / "wave-4-closure-v2.json").stat().st_size,
            }
            write_json(fixture.evidence / "wave-4-approval.json", forged)
            forged_validation = run_cli("verify-wave", "--wave", "4", "--evidence-root", str(fixture.evidence))

            self.assertEqual(forged_validation.returncode, 2)

    def test_closure_v2_approval_required_provenance_tamper_matrix(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = ProductFixture(raw)
            fixture.create_wave4_closure_v2()
            approved = fixture.approve_wave4_closure_v2()
            self.assertEqual(approved.returncode, 0, approved.stderr.decode("utf-8", "replace"))
            original_approval = read_json(fixture.evidence / "wave-4-approval.json")
            original_closure = read_json(fixture.evidence / "wave-4-closure-v2.json")
            cases: dict[str, dict[str, JsonValue]] = {}
            for name, key in (
                ("draft-alone", "draft"),
                ("review-alone", "review_seal"),
                ("both-draft-review", "draft"),
            ):
                value = json.loads(json.dumps(original_closure))
                required = value["approval_required"]
                if not isinstance(required, dict):
                    raise AssertionError("closure lacks approval_required")
                target = required[key]
                if not isinstance(target, dict):
                    raise AssertionError("invalid approval_required item")
                target["hash"] = "0" * 64
                if name == "both-draft-review":
                    review_target = required["review_seal"]
                    if not isinstance(review_target, dict):
                        raise AssertionError("invalid review seal item")
                    review_target["hash"] = "1" * 64
                cases[name] = value
            swapped = json.loads(json.dumps(original_closure))
            required = swapped["approval_required"]
            if not isinstance(required, dict):
                raise AssertionError("closure lacks approval_required")
            required["tooling_review"], required["independent_gate"] = (
                required["independent_gate"],
                required["tooling_review"],
            )
            cases["tooling-gate-swap"] = swapped
            for name, closure in cases.items():
                with self.subTest(name=name):
                    write_json(fixture.evidence / "wave-4-closure-v2.json", closure)
                    tamper_message = fixture.evidence / f"{name}-message.txt"
                    tamper_message.write_text(
                        f"APPROVE wave 4 {file_sha(fixture.evidence / 'wave-4-closure-v2.json')}\n",
                        encoding="utf-8",
                    )
                    approval = {
                        **original_approval,
                        "message_bytes_b64": base64.b64encode(tamper_message.read_bytes()).decode("ascii"),
                        "message_path": str(tamper_message.resolve()),
                        "message_sha256": file_sha(tamper_message),
                        "message_size": tamper_message.stat().st_size,
                        "receipt_sha256": file_sha(fixture.evidence / "wave-4-closure-v2.json"),
                        "receipt_size": (fixture.evidence / "wave-4-closure-v2.json").stat().st_size,
                    }
                    write_json(fixture.evidence / "wave-4-approval.json", approval)
                    verified = run_cli("verify-wave", "--wave", "4", "--evidence-root", str(fixture.evidence))
                    self.assertEqual(verified.returncode, 2, verified.stderr.decode("utf-8", "replace"))
            write_json(fixture.evidence / "wave-4-closure-v2.json", original_closure)
            write_json(fixture.evidence / "wave-4-approval.json", original_approval)

    def test_verify_wave_rejects_closure_v2_approval_message_path_bytes_and_hash_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = ProductFixture(raw)
            fixture.create_wave4_closure_v2()
            approved = fixture.approve_wave4_closure_v2()
            self.assertEqual(approved.returncode, 0, approved.stderr.decode("utf-8", "replace"))
            original = read_json(fixture.evidence / "wave-4-approval.json")
            cases: dict[str, dict[str, JsonValue]] = {
                "message-path": {**original, "message_path": str((fixture.evidence / "missing-message.txt").resolve())},
                "message-bytes": {**original, "message_bytes_b64": base64.b64encode(b"APPROVE wave 4 forged\n").decode("ascii")},
                "message-hash": {**original, "message_sha256": "0" * 64},
                "message-lf": {**original, "message_lf": False},
            }
            for name, value in cases.items():
                with self.subTest(name=name):
                    write_json(fixture.evidence / "wave-4-approval.json", value)
                    verified = run_cli("verify-wave", "--wave", "4", "--evidence-root", str(fixture.evidence))
                    self.assertEqual(verified.returncode, 2, verified.stderr.decode("utf-8", "replace"))

    def test_closure_v2_rejects_machine_report_semantic_substitutions(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = ProductFixture(raw)
            fixture.create_wave4_closure_v2()
            approved = fixture.approve_wave4_closure_v2()
            self.assertEqual(approved.returncode, 0, approved.stderr.decode("utf-8", "replace"))
            original_approval = read_json(fixture.evidence / "wave-4-approval.json")
            original_closure = read_json(fixture.evidence / "wave-4-closure-v2.json")

            cases: dict[str, tuple[str, str, dict[str, JsonValue]]] = {
                "tooling-failed-verdict": ("tooling_review", "tooling-review-substituted.json", {"verdict": "FAILED"}),
                "gate-watch-verdict": ("independent_gate", "independent-gate-substituted.json", {"verdict": "WATCH"}),
                "tooling-unknown-schema": (
                    "tooling_review",
                    "tooling-unknown-schema.json",
                    {"schema_version": "unknown-tooling/v1"},
                ),
                "gate-missing-binding": (
                    "independent_gate",
                    "gate-missing-binding.json",
                    {"product_sha256": None},
                ),
                "tooling-rehashed-product-substitution": (
                    "tooling_review",
                    "tooling-product-substituted.json",
                    {"product_sha256": "0" * 64},
                ),
            }
            for name, (provenance_key, report_name, updates) in cases.items():
                with self.subTest(name=name):
                    closure = json.loads(json.dumps(original_closure))
                    provenance = closure["approval_required"]
                    if not isinstance(provenance, dict):
                        raise AssertionError("closure lacks approval provenance")
                    record = provenance[provenance_key]
                    if not isinstance(record, dict):
                        raise AssertionError("invalid provenance record")
                    summary_path = Path(str(record["path"]))
                    summary = read_json(summary_path)
                    original_summary = json.loads(json.dumps(summary))
                    if "report" not in summary:
                        self.fail("closure did not bind machine summary sidecar")
                    report_record = summary["report"]
                    if not isinstance(report_record, dict):
                        raise AssertionError("summary lacks report record")
                    original_report = read_json(Path(str(report_record["path"])))
                    substituted = {**original_report}
                    for key, value in updates.items():
                        if value is None:
                            substituted.pop(key)
                        else:
                            substituted[key] = value
                    substituted_report = fixture.evidence / report_name
                    write_json(substituted_report, substituted)
                    for key, value in updates.items():
                        if key == "schema_version":
                            continue
                        if value is None:
                            summary.pop(key)
                        else:
                            summary[key] = value
                    summary["report"] = file_ref(substituted_report)
                    write_json(summary_path, summary)
                    record["hash"] = file_sha(summary_path)
                    record["size"] = summary_path.stat().st_size
                    write_json(fixture.evidence / "wave-4-closure-v2.json", closure)
                    tamper_message = fixture.evidence / f"{name}-message.txt"
                    tamper_message.write_text(
                        f"APPROVE wave 4 {file_sha(fixture.evidence / 'wave-4-closure-v2.json')}\n",
                        encoding="utf-8",
                    )
                    approval = {
                        **original_approval,
                        "message_bytes_b64": base64.b64encode(tamper_message.read_bytes()).decode("ascii"),
                        "message_path": str(tamper_message.resolve()),
                        "message_sha256": file_sha(tamper_message),
                        "message_size": tamper_message.stat().st_size,
                        "receipt_sha256": file_sha(fixture.evidence / "wave-4-closure-v2.json"),
                        "receipt_size": (fixture.evidence / "wave-4-closure-v2.json").stat().st_size,
                    }
                    write_json(fixture.evidence / "wave-4-approval.json", approval)
                    verified = run_cli("verify-wave", "--wave", "4", "--evidence-root", str(fixture.evidence))
                    self.assertEqual(verified.returncode, 2, verified.stderr.decode("utf-8", "replace"))
                    write_json(summary_path, original_summary)
                    write_json(fixture.evidence / "wave-4-closure-v2.json", original_closure)
                    write_json(fixture.evidence / "wave-4-approval.json", original_approval)

    def test_wave4_approval_rejects_mutated_bound_identity_fields(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = ProductFixture(raw)
            fixture.create_wave4_receipt()
            receipt = fixture.evidence / "wave-4-receipt.json"
            value = read_json(receipt)
            value["implementation_sha256"] = "0" * 64
            tampered = fixture.evidence / "wave-4-receipt-tampered.json"
            message = fixture.evidence / "wave-4-approval-message-tampered.txt"
            write_json(tampered, value)
            message.write_text(f"APPROVE wave 4 {file_sha(tampered)}\n", encoding="utf-8")

            rejected = run_cli(
                "approve-wave",
                "--wave",
                "4",
                "--receipt",
                str(tampered),
                "--message",
                str(message),
                "--output",
                str(fixture.evidence / "wave-4-approval-tampered.json"),
                "--impl-root",
                str(fixture.impl),
                "--evidence-root",
                str(fixture.evidence),
            )

            self.assertEqual(rejected.returncode, 2)
            self.assertFalse((fixture.evidence / "wave-4-approval-tampered.json").exists())

    def test_freeze_rejects_existing_snapshot_with_stale_git_admin_state(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = ProductFixture(raw)
            approved = fixture.approve_wave4()
            manifest = fixture.evidence / "freeze.implementation-manifest.json"
            archive = fixture.evidence / "freeze.implementation.tar"
            captured = run_cli(
                "capture-worktree",
                "--root",
                str(fixture.impl),
                "--archive",
                str(archive),
                "--manifest",
                str(manifest),
            )
            subprocess.run(["git", "config", "remediation4.probe", "changed"], cwd=fixture.impl, check=True)
            frozen = fixture.freeze_with_wave_checkpoint()

            self.assertEqual(approved.returncode, 0, approved.stderr.decode("utf-8", "replace"))
            self.assertEqual(captured.returncode, 0, captured.stderr.decode("utf-8", "replace"))
            self.assertEqual(frozen.returncode, 2)
            self.assertFalse((fixture.evidence / "freeze.json").exists())

    def test_historical_v2_product_artifact_materializes_and_verifies_with_git_entries(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = ProductFixture(raw)
            excluded = {
                os.fsencode((fixture.impl / path).resolve())
                for path in PRODUCT_EXCLUDED_PATHS
            }
            entries = scan_tree(fixture.impl, excluded)
            manifest = fixture.evidence / "legacy-v2.json"
            archive = fixture.evidence / "legacy-v2.tar"
            write_json(
                manifest,
                {
                    "entries": entries,
                    "excluded_orchestration_paths": list(PRODUCT_EXCLUDED_PATHS),
                    "git_status_sha256": "0" * 64,
                    "root": "implementation",
                    "schema_version": "agent-brain-implementation/v2",
                    "scope": PRODUCT_SCOPE,
                },
            )
            create_archive(archive, _blobs(fixture.impl, entries))
            output = fixture.base / "legacy-v2-output"

            materialized = run_cli(
                "materialize",
                "--manifest",
                str(manifest),
                "--archive",
                str(archive),
                "--output",
                str(output),
            )
            verified = run_cli("verify-materialized", "--manifest", str(manifest), "--root", str(output))

            self.assertEqual(materialized.returncode, 0, materialized.stderr.decode("utf-8", "replace"))
            self.assertEqual(verified.returncode, 0, verified.stderr.decode("utf-8", "replace"))

    def test_final_review_rejects_forged_lane_summaries_without_run_bindings(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = ProductFixture(raw)
            approved = fixture.approve_wave4()
            frozen = fixture.freeze_with_wave_checkpoint()
            lanes: list[Path] = []
            for lane in ("f1-plan-compliance", "f2-code-quality", "f3-manual-qa", "f4-scope-fidelity"):
                path = fixture.evidence / f"{lane}.json"
                write_json(
                    path,
                    {
                        "findings": [],
                        "freeze_sha256": file_sha(fixture.evidence / "freeze.json"),
                        "lane": lane.split("-", 1)[0].upper(),
                        "schema_version": "agent-brain-final-lane/v1",
                        "verdict": "APPROVE",
                    },
                )
                lanes.append(path)

            reviewed = run_cli(
                "final-review",
                "--freeze",
                str(fixture.evidence / "freeze.json"),
                "--lanes",
                *(str(path) for path in lanes),
                "--output",
                str(fixture.evidence / "final-review.json"),
                "--impl-root",
                str(fixture.impl),
                "--evidence-root",
                str(fixture.evidence),
                "--prior-ledger-checkpoint",
                str(fixture.evidence / "freeze.ledger-checkpoint.json"),
            )

            self.assertEqual(approved.returncode, 0, approved.stderr.decode("utf-8", "replace"))
            self.assertEqual(frozen.returncode, 0, frozen.stderr.decode("utf-8", "replace"))
            self.assertEqual(reviewed.returncode, 2)
            self.assertFalse((fixture.evidence / "final-review.json").exists())

    def test_verify_freeze_honors_status_flag_as_a_bound_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = ProductFixture(raw)
            approved = fixture.approve_wave4()
            frozen = fixture.freeze_with_wave_checkpoint()

            verified = run_cli(
                "verify",
                "--freeze",
                str(fixture.evidence / "freeze.json"),
                "--impl-root",
                str(fixture.impl),
                "--evidence-root",
                str(fixture.evidence),
                "--status",
                str(fixture.evidence / "missing-status.txt"),
            )

            self.assertEqual(approved.returncode, 0, approved.stderr.decode("utf-8", "replace"))
            self.assertEqual(frozen.returncode, 0, frozen.stderr.decode("utf-8", "replace"))
            self.assertEqual(verified.returncode, 2)

    def test_lane_success_rejects_product_or_git_drift_after_command(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = ProductFixture(raw)
            fixture.write_minimal_freeze()
            result = run_cli(
                "run-lane",
                "--lane",
                "F1",
                "--step",
                "1",
                "--cwd",
                str(fixture.impl),
                "--freeze",
                str(fixture.evidence / "freeze.json"),
                "--evidence-root",
                str(fixture.evidence),
                "--",
                sys.executable,
                "-B",
                "-c",
                "from pathlib import Path; Path('model/drift.txt').write_text('drift\\n')",
            )

            self.assertEqual(result.returncode, 2)
            self.assertTrue((fixture.evidence / "F1-runs" / "1.json").exists())
