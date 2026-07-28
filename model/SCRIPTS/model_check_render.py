from __future__ import annotations

import hashlib
import json
from pathlib import Path

from brain_state import current_model_root, detect_state, link_status
from model_check_context import build_context_report
from model_check_contract import JsonValue


def stable_json(value: JsonValue) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def source_files(root: Path) -> list[dict[str, JsonValue]]:
    files: list[dict[str, JsonValue]] = []
    root_agents = root / "AGENTS.md"
    if root_agents.exists() and root_agents.is_file() and not root_agents.is_symlink():
        raw = root_agents.read_bytes()
        files.append(
            {"path": "AGENTS.md", "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        )
    for parent in (root / "model", root / "skills" / "brain", root / "docs"):
        if not parent.exists():
            continue
        for path in sorted(parent.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            rel = path.relative_to(root).as_posix()
            raw = path.read_bytes()
            files.append(
                {"path": rel, "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
            )
    return files


def source_report(root: Path) -> dict[str, JsonValue]:
    files = source_files(root)
    payload = stable_json({"files": files}).encode()
    return {"source_digest": hashlib.sha256(payload).hexdigest(), "files": files}


def source_digest(root: Path) -> str:
    return str(source_report(root)["source_digest"])


def context_report(root: Path, model: dict[str, JsonValue]) -> dict[str, JsonValue]:
    return build_context_report(root, model, source_digest(root))


def brain_manifest(brain_root: Path, common_root: Path | None = None) -> dict[str, JsonValue]:
    common = common_root or current_model_root()
    status, desired = link_status(brain_root, common)
    return {
        "brain": str(brain_root),
        "common": {
            "desired": desired,
            "path": str(brain_root / "_COMMON"),
            "status": status,
        },
        "state": detect_state(brain_root, common),
    }
