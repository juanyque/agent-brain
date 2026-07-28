#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from baseline_materializer import (  # noqa: E402
    BaselineError,
    materialize_baseline_modules,
    module_refs_from_ids,
    run_materialized_ids,
)


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--git-ref", required=True)
    parser.add_argument("--expected-ids", type=Path, required=True)
    return parser.parse_args()


def expected_ids(path: Path) -> list[str]:
    ids = path.read_text("utf-8").splitlines()
    if len(ids) != 113 or ids != sorted(set(ids)):
        raise BaselineError("expected ID file must contain 113 unique sorted IDs")
    return ids


def main() -> int:
    parsed = arguments()
    root = parsed.root.resolve()
    temp_root_text = ""
    try:
        ids = expected_ids(parsed.expected_ids)
        refs = module_refs_from_ids(ids)
        with tempfile.TemporaryDirectory(prefix="baseline-tests-") as raw:
            temp_root_text = raw
            temp_root = Path(raw)
            modules = materialize_baseline_modules(root, parsed.git_ref, refs, temp_root)
            run = run_materialized_ids(root, temp_root, modules, ids)
    except (BaselineError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 2
    print(run.transcript, file=sys.stderr, end="")
    print(
        json.dumps(
            {
                "count": len(run.loaded_ids),
                "child_provenance": run.provenance,
                "git_ref": parsed.git_ref,
                "module_count": len(modules),
                "module_sha256": {
                    module.relative_path.as_posix(): module.sha256 for module in modules
                },
                "status": run.status,
                "temp_root_exists_after": Path(temp_root_text).exists(),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return run.status


if __name__ == "__main__":
    raise SystemExit(main())
