#!/usr/bin/env python3
from __future__ import annotations

import sys

from evidence_cli import build_parser, execute
from evidence_json import ContractError


def main() -> int:
    try:
        return execute(build_parser().parse_args())
    except ContractError as error:
        print(str(error), file=sys.stderr)
        return 2
    except (KeyError, OSError, TypeError, ValueError) as error:
        print(f"contract boundary error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
