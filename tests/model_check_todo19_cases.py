from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "model" / "SCRIPTS" / "model_check.py"
MODEL = ROOT / "model" / "OPERATING-MODEL.json"
WORKFLOW = ROOT / ".github" / "workflows" / "tests.yml"
QA_COMMANDS = ROOT / "tests" / "fixtures" / "operating-model-qa-commands.json"


def run_cli(*args: str, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(CLI), *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )


def parsed_json(result: subprocess.CompletedProcess[str]) -> dict[str, object]:
    value = json.loads(result.stdout)
    if not isinstance(value, dict):
        raise AssertionError("expected JSON object")
    return value


def copy_repo_fixture(root: Path) -> None:
    shutil.copytree(
        ROOT,
        root,
        ignore=shutil.ignore_patterns(".git", "__pycache__"),
        dirs_exist_ok=True,
    )


def init_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "model/OPERATING-MODEL.json"], cwd=root, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Todo19",
            "-c",
            "user.email=todo19@example.invalid",
            "commit",
            "-qm",
            "baseline",
        ],
        cwd=root,
        check=True,
    )


def workflow_lines() -> list[str]:
    return WORKFLOW.read_text(encoding="utf-8").splitlines()


@dataclass(frozen=True, slots=True)
class WorkflowJob:
    os: tuple[str, ...]
    steps: tuple[tuple[str, str], ...]

    def step_named(self, name: str) -> str:
        for step_name, body in self.steps:
            if step_name == name:
                return body
        raise AssertionError(f"missing workflow step: {name}")


def stdlib_contracts_job() -> WorkflowJob:
    lines = workflow_lines()
    start = lines.index("  stdlib-contracts:")
    end = next(
        (
            index
            for index in range(start + 1, len(lines))
            if lines[index].startswith("  ") and not lines[index].startswith("    ")
        ),
        len(lines),
    )
    block = lines[start:end]
    os_line = next(line for line in block if line.strip().startswith("os: ["))
    matrix = os_line.split("[", 1)[1].split("]", 1)[0]
    steps: list[tuple[str, str]] = []
    for index, line in enumerate(block):
        if not line.startswith("      - name: "):
            continue
        name = line.removeprefix("      - name: ")
        step_end = next(
            (
                next_index
                for next_index in range(index + 1, len(block))
                if block[next_index].startswith("      - name: ")
            ),
            len(block),
        )
        steps.append((name, "\n".join(block[index:step_end])))
    return WorkflowJob(
        os=tuple(item.strip() for item in matrix.split(",")),
        steps=tuple(steps),
    )


class StrictGateTests(unittest.TestCase):
    def test_orphan_common_rule_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            copy_repo_fixture(root)
            (root / "model" / "RULES-ORPHAN.common.md").write_text(
                "# Orphan\n",
                encoding="utf-8",
            )

            result = run_cli(
                "--root",
                str(root),
                "--model",
                str(root / "model" / "OPERATING-MODEL.json"),
                "--strict",
                "--only",
                "orphan-model-artifact",
                "--format",
                "json",
            )
            findings = parsed_json(result)["findings"]

        self.assertEqual(result.returncode, 1)
        self.assertEqual(findings[0]["code"], "orphan-model-artifact")
        self.assertEqual(findings[0]["path"], "model/RULES-ORPHAN.common.md")
        self.assertNotIn("unmapped-cluster", {finding["code"] for finding in findings})

    def test_missing_attachment_rule_still_fails_as_unmapped_cluster(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            copy_repo_fixture(root)
            (root / "model" / "RULES-ATTACHMENTS.common.md").unlink()

            result = run_cli(
                "--root",
                str(root),
                "--model",
                str(root / "model" / "OPERATING-MODEL.json"),
                "--strict",
                "--only",
                "unmapped-cluster",
                "--format",
                "json",
            )
            findings = parsed_json(result)["findings"]

        self.assertEqual(result.returncode, 1)
        self.assertEqual(findings[0]["code"], "unmapped-cluster")
        self.assertEqual(findings[0]["path"], "model/RULES-ATTACHMENTS.common.md")

    def test_startup_budget_overflow_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            copy_repo_fixture(root)
            baseline = root / "tests" / "fixtures" / "model-context-baseline.json"
            body = json.loads(baseline.read_text(encoding="utf-8"))
            body["budgets"]["startup"]["cap_bytes"] = 1
            baseline.write_text(
                json.dumps(body, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )

            result = run_cli(
                "--root",
                str(root),
                "--model",
                str(root / "model" / "OPERATING-MODEL.json"),
                "--strict",
                "--only",
                "context-budget-exceeded",
                "--format",
                "json",
            )
            findings = parsed_json(result)["findings"]

        self.assertEqual(result.returncode, 1)
        self.assertEqual(findings[0]["code"], "context-budget-exceeded")

    def test_untracked_out_of_scope_file_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "model").mkdir()
            shutil.copy(MODEL, root / "model" / "OPERATING-MODEL.json")
            init_repo(root)
            (root / "private.txt").write_text("out of scope\n", encoding="utf-8")

            result = run_cli(
                "--root",
                str(root),
                "--model",
                str(root / "model" / "OPERATING-MODEL.json"),
                "--strict",
                "--only",
                "worktree-scope",
                "--format",
                "json",
            )
            findings = parsed_json(result)["findings"]

        self.assertEqual(result.returncode, 1)
        self.assertIn("out-of-scope-path", {finding["code"] for finding in findings})

    def test_untracked_whitespace_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "model").mkdir()
            shutil.copy(MODEL, root / "model" / "OPERATING-MODEL.json")
            init_repo(root)
            (root / "README.md").write_text("trailing space \n", encoding="utf-8")

            result = run_cli(
                "--root",
                str(root),
                "--model",
                str(root / "model" / "OPERATING-MODEL.json"),
                "--strict",
                "--only",
                "whitespace",
                "--format",
                "json",
            )
            findings = parsed_json(result)["findings"]

        self.assertEqual(result.returncode, 1)
        self.assertEqual(findings[0]["code"], "whitespace-error")
        self.assertIn("README.md", findings[0]["message"])


class WorkflowContractTests(unittest.TestCase):
    def test_fetches_and_verifies_pinned_history(self) -> None:
        job = stdlib_contracts_job()
        checkout = job.step_named("Check out repository")
        resolve = job.step_named("Resolve comparison base")

        self.assertIn("fetch-depth: 0", checkout)
        self.assertIn("MODEL_BASE: 993247b2850ac86993c7c6dd18e6c4fd9ec6df7c", resolve)
        self.assertIn('git cat-file -e "${MODEL_BASE}^{commit}"', resolve)
        self.assertIn("github.event.pull_request.base.sha", resolve)
        self.assertIn("github.event.before", resolve)
        self.assertIn("git rev-list --max-parents=0 HEAD", resolve)

    def test_macos_and_linux_run_committed_and_worktree_gates(self) -> None:
        job = stdlib_contracts_job()
        self.assertEqual(job.os, ("ubuntu-latest", "macos-latest"))
        committed = job.step_named("Run committed-range gates")
        worktree = job.step_named("Run worktree gates")

        self.assertIn('git diff "${MODEL_BASE}...HEAD" --check', committed)
        self.assertIn(
            ":(exclude)skills/manage-document-projects/assets/project-types/"
            "residential-lease/jurisdictions/**/legal-sources/snapshots/**/raw/**",
            committed,
        )
        self.assertIn(
            ":(exclude)skills/manage-document-projects/assets/project-types/"
            "residential-lease/templates/*.md.j2",
            committed,
        )
        self.assertIn("--git-base", committed)
        self.assertIn("committed-scope", committed)
        self.assertIn("git diff HEAD --check", worktree)
        self.assertIn("worktree-scope,whitespace", worktree)

    def test_macos_and_linux_run_current_and_immutable_baseline_tests(self) -> None:
        job = stdlib_contracts_job()
        names = tuple(name for name, _ in job.steps)
        current_index = names.index("Run contract and integration tests")
        baseline_index = names.index("Run immutable baseline tests")
        baseline = job.step_named("Run immutable baseline tests")

        self.assertEqual(job.os, ("ubuntu-latest", "macos-latest"))
        self.assertLess(current_index, baseline_index)
        self.assertIn(
            "python3 tests/support/run_baseline_tests.py --root . --git-ref "
            "6373436ab4a16170cd4d1911f255a14430e367ca --expected-ids "
            "tests/fixtures/baseline-test-ids.txt",
            baseline,
        )

    def test_complete_local_gate_alias_is_governed(self) -> None:
        manifest = json.loads(QA_COMMANDS.read_text(encoding="utf-8"))
        todo19 = next(item for item in manifest["todos"] if item["todo"] == 19)

        self.assertEqual(
            manifest["aliases"],
            [{"alias": "complete-local-gate", "step": 1, "todo": 19}],
        )
        self.assertEqual(todo19["steps"][0]["alias"], "complete-local-gate")
