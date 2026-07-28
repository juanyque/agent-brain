from __future__ import annotations

import argparse
import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from typing import TypeAlias


JsonValue: TypeAlias = (
    None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
)


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    return parser.parse_args()


def _flatten(suite: unittest.TestSuite | unittest.TestCase) -> list[unittest.TestCase]:
    if isinstance(suite, unittest.TestCase):
        return [suite]
    result: list[unittest.TestCase] = []
    for item in suite:
        result.extend(_flatten(item))
    return result


def _read_request(path: Path) -> tuple[Path, Path, list[str]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    root = Path(value["root"])
    temp_root = Path(value["temp_root"])
    ids = [str(identifier) for identifier in value["ids"]]
    return root, temp_root, ids


def _module_name(identifier: str) -> str:
    parts = identifier.split(".")
    return ".".join(parts[:-2])


def _provenance(
    ids: list[str],
    root: Path,
    temp_root: Path,
    initial_sys_path: list[str],
) -> dict[str, JsonValue]:
    modules: dict[str, JsonValue] = {}
    for identifier in ids:
        name = _module_name(identifier)
        module = sys.modules.get(name)
        path = getattr(module, "__file__", "") if module is not None else ""
        modules[name] = os.fspath(path) if path else ""
    return {
        "cwd": os.getcwd(),
        "executable": sys.executable,
        "initial_sys_path": initial_sys_path,
        "root": os.fspath(root),
        "sys_path": list(sys.path),
        "temp_root": os.fspath(temp_root),
        "test_modules": modules,
    }


def _interpreter_paths() -> list[str]:
    support_dir = Path(__file__).resolve().parent
    paths: list[str] = []
    for entry in sys.path:
        if not entry:
            continue
        if Path(entry).resolve() == support_dir:
            continue
        paths.append(entry)
    return paths


def main() -> int:
    parsed = arguments()
    root, temp_root, ids = _read_request(parsed.request)
    interpreter_paths = _interpreter_paths()
    sys.path[:] = [
        os.fspath(temp_root / "tests"),
        os.fspath(temp_root),
        os.fspath(root),
        os.fspath(root / "tests"),
        *interpreter_paths,
    ]
    initial_sys_path = list(sys.path)
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromNames(ids)
    loaded = sorted(test.id() for group in suite for test in _flatten(group))
    stream = io.StringIO()
    if loaded == ids:
        with redirect_stdout(stream):
            result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
        status = 0 if result.wasSuccessful() else 1
        error = ""
    else:
        status = 2
        error = "loaded test IDs differ from expected IDs"
    print(
        json.dumps(
            {
                "error": error,
                "loaded_ids": loaded,
                "provenance": _provenance(loaded, root, temp_root, initial_sys_path),
                "status": status,
                "transcript": stream.getvalue(),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return status


if __name__ == "__main__":
    raise SystemExit(main())
