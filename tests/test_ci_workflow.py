from __future__ import annotations

import unittest

from tests.model_check_todo19_cases import stdlib_contracts_job


class CiWorkflowContractTests(unittest.TestCase):
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
        self.assertIn("uv run", tests)
        self.assertIn("pydantic>=2.10,<3", tests.lower())
        self.assertIn("pyyaml>=6.0.2,<7", tests.lower())


if __name__ == "__main__":
    unittest.main()
