from __future__ import annotations

import unittest

from tests.model_check_todo19_cases import ROOT, stdlib_contracts_job


class CiWorkflowContractTests(unittest.TestCase):
    def test_ci_provisions_ripgrep_on_both_platforms(self) -> None:
        # Given: the workflow job that executes the canonical stale scan.
        job = stdlib_contracts_job()

        # When: its platform-specific dependency steps are inspected.
        ubuntu = job.step_named("Install Ubuntu test dependencies")
        macos = job.step_named("Install ripgrep")

        # Then: both runners receive the executable used by the stale scan.
        self.assertIn("runner.os == 'Linux'", ubuntu)
        self.assertIn("apt-get install -y pandoc ripgrep weasyprint", ubuntu)
        self.assertIn("runner.os == 'macOS'", macos)
        self.assertIn("brew install ripgrep", macos)

    def test_ci_provisions_document_renderers_on_both_platforms(self) -> None:
        # Given: the workflow job that runs document rendering tests.
        job = stdlib_contracts_job()

        # When: its platform-specific renderer provisioning steps are inspected.
        ubuntu = job.step_named("Install Ubuntu test dependencies")
        macos = job.step_named("Install document renderers (macOS)")

        # Then: both runners receive Pandoc and its configured PDF engine.
        self.assertIn("runner.os == 'Linux'", ubuntu)
        self.assertIn("apt-get install -y pandoc ripgrep weasyprint", ubuntu)
        self.assertIn("runner.os == 'macOS'", macos)
        self.assertIn("brew install pandoc weasyprint", macos)

    def test_operating_model_evidence_is_host_independent(self) -> None:
        # Given: the tests executed on both macOS and Linux runners.
        source = (ROOT / "tests" / "test_operating_model_evidence.py").read_text(
            encoding="utf-8"
        )

        # When: their source is checked for a developer-specific macOS home.
        maintainer_home = "/" + "Users/"
        absolute_home_lines = [
            line_number
            for line_number, line in enumerate(source.splitlines(), start=1)
            if maintainer_home in line
        ]

        # Then: every fixture can be created inside the test sandbox.
        self.assertEqual(absolute_home_lines, [])

    def test_ci_provisions_document_project_test_runtime(self) -> None:
        # Given: the workflow job that discovers every repository test.
        job = stdlib_contracts_job()

        # When: its runtime provisioning and test steps are inspected.
        python = job.step_named("Set up Python")
        uv = job.step_named("Install uv")
        tests = job.step_named("Run contract and integration tests")

        # Then: CI matches the document-project scripts' declared runtime.
        self.assertIn('python-version: "3.12"', python)
        self.assertIn("astral-sh/setup-uv@", uv)
        self.assertIn("uv run --python 3.12", tests)
        self.assertIn("jsonschema>=4.25,<5", tests.lower())
        self.assertIn("pydantic>=2.10,<3", tests.lower())
        self.assertIn("pyyaml>=6.0.2,<7", tests.lower())


if __name__ == "__main__":
    unittest.main()
