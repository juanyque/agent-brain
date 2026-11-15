from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "model" / "SCRIPTS" / "model_check.py"
MODEL = ROOT / "model" / "OPERATING-MODEL.json"
WORKFLOW = ROOT / ".github" / "workflows" / "tests.yml"


def run_cli(*args: str, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *args],
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
    def test_resolves_model_base_per_event(self) -> None:
        job = stdlib_contracts_job()
        checkout = job.step_named("Check out repository")
        resolve = job.step_named("Resolve comparison base")

        self.assertIn("fetch-depth: 0", checkout)
        self.assertIn("tests/support/resolve_model_base.sh", resolve)
        self.assertIn("EVENT_NAME: ${{ github.event_name }}", resolve)
        self.assertIn(
            "PR_BASE_SHA: ${{ github.event.pull_request.base.sha }}", resolve
        )
        self.assertIn("PUSH_BEFORE_SHA: ${{ github.event.before }}", resolve)
        self.assertIn(
            "DEFAULT_BRANCH: ${{ github.event.repository.default_branch }}", resolve
        )
        self.assertIn('git cat-file -e "${MODEL_BASE}^{commit}"', resolve)
        self.assertIn('"MODEL_BASE=%s\\n" "$MODEL_BASE" >> "$GITHUB_ENV"', resolve.replace("'", '"'))
        # The base must come from the resolver only: reject any constant pin, however
        # it is spelled, so re-adding one fails here even if the old SHA changes.
        self.assertIn('MODEL_BASE="$(bash tests/support/resolve_model_base.sh)"', resolve)
        self.assertNotRegex(resolve, r"MODEL_BASE[:=]\s*[\"']?[0-9a-f]{7,40}")
        self.assertNotRegex(WORKFLOW.read_text(), r"MODEL_BASE[:=]\s*[\"']?[0-9a-f]{7,40}")
        self.assertNotIn("993247b", resolve)
        self.assertNotIn("993247b", WORKFLOW.read_text())
        self.assertNotIn("rev-list --max-parents=0", resolve)

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

    def test_macos_and_linux_run_current_tests(self) -> None:
        job = stdlib_contracts_job()
        names = tuple(name for name, _ in job.steps)

        self.assertEqual(job.os, ("ubuntu-latest", "macos-latest"))
        self.assertIn("Run contract and integration tests", names)


def canonical_model() -> dict[str, object]:
    raw = MODEL.read_bytes()
    parsed = json.loads(raw)
    expected = (
        json.dumps(
            parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode()
        + b"\n"
    )
    if raw != expected:
        raise AssertionError(f"{MODEL} is not canonical JSON")
    return parsed


class OperatingModelContractTests(unittest.TestCase):
    def test_governed_inventory_matches_model_markdown(self) -> None:
        model = canonical_model()
        governed = set(model["governed_inventory"])
        discovered = {
            str(path.relative_to(ROOT))
            for parent in (ROOT, ROOT / "model", ROOT / "skills" / "brain")
            for path in parent.rglob("*.md")
            if parent != ROOT or path.name == "AGENTS.md"
        }
        self.assertEqual(governed, discovered)

    def test_route_graph_has_13_unique_triples_and_linked_skill_routes(self) -> None:
        model = canonical_model()
        routes = model["route_graph"]
        triples = [(r["route_id"], r["scenario_id"], r["terminal"]) for r in routes]

        self.assertEqual(len(triples), 13)
        for index in range(3):
            self.assertEqual(len({triple[index] for triple in triples}), 13)
        skill_routes = {r["route_id"]: r["terminal"] for r in routes if r["route_id"].startswith("skill.")}
        self.assertEqual(
            set(skill_routes),
            {
                "skill.session-routing",
                "skill.documentation",
                "skill.tool-catalog",
                "skill.constraints",
            },
        )
        router = (ROOT / "skills" / "brain" / "SKILL.md").read_text(encoding="utf-8")
        section = router.split("## Conditional Reference Router", 1)[1].split("\n## ", 1)[0]
        for terminal in skill_routes.values():
            self.assertIn(f"`{terminal.removeprefix('skills/brain/')}`", section)
        self.assertEqual(
            sorted(terminal for _route, _scenario, terminal in triples),
            sorted(model["context_contract"]["conditional_artifacts"]),
        )


class TrackedTextWhitespaceTests(unittest.TestCase):
    def test_tracked_markdown_and_jinja_files_carry_no_trailing_whitespace(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        listing = subprocess.run(
            ["git", "ls-files", "--", "*.md", "*.j2"],
            cwd=repo_root,
            text=True,
            capture_output=True,
            check=True,
        )
        offenders: list[str] = []
        for rel in listing.stdout.splitlines():
            for lineno, line in enumerate(
                (repo_root / rel).read_text(encoding="utf-8", errors="replace").splitlines(),
                start=1,
            ):
                if line != line.rstrip(" \t"):
                    offenders.append(f"{rel}:{lineno}")
        self.assertEqual(
            offenders,
            [],
            "trailing whitespace reintroduced (git diff --check would fail on "
            "any future diff touching these lines)",
        )


if __name__ == "__main__":
    unittest.main()
