from __future__ import annotations

import unittest

from tests.support.evidence_json import ContractError


class ContractErrorTests(unittest.TestCase):
    def test_contract_error_accepts_traceback_assignment(self) -> None:
        # Given: a traceback produced by the Python runtime.
        source = KeyError("source")
        try:
            raise source
        except KeyError as raised:
            source_traceback = raised.__traceback__
        error = ContractError("contract failure")

        # When: a test runner attaches that traceback to the contract error.
        error.__traceback__ = source_traceback

        # Then: the original traceback is retained for error reporting.
        self.assertIs(error.__traceback__, source_traceback)


if __name__ == "__main__":
    unittest.main()
