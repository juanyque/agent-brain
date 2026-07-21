#!/usr/bin/env python3
"""Return a small, ranked set of curated-memory candidates.

The tool reads memory indexes only. It never loads note bodies, so callers can
decide which (if any) candidate is worth adding to their context.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path


INDEX_ENTRY = re.compile(r"^\s*-\s+\[([^]]+)]\(([^)]+)\)\s*(?:[—–-]\s*)?(.*)$")
STOP_WORDS = {
    "about", "after", "antes", "como", "con", "cuando", "desde", "esta",
    "este", "para", "pero", "por", "que", "the", "this", "una", "using",
    "with", "work",
}


@dataclass(frozen=True)
class Candidate:
    path: str
    description: str
    scope: str
    score: int


def tokens(value: str) -> set[str]:
    normalized = unicodedata.normalize("NFKD", value.lower())
    ascii_value = "".join(char for char in normalized if not unicodedata.combining(char))
    return {
        token
        for token in re.findall(r"[a-z0-9]+", ascii_value)
        if len(token) >= 3 and token not in STOP_WORDS
    }


def index_paths(memory_root: Path) -> list[tuple[Path, str]]:
    indexes: list[tuple[Path, str]] = []
    root_index = memory_root / "MEMORY.md"
    if root_index.is_file():
        indexes.append((root_index, "general"))
    projects = memory_root / "projects"
    if projects.is_dir():
        for path in sorted(projects.glob("*/MEMORY.md")):
            indexes.append((path, f"project:{path.parent.name}"))
    return indexes


def is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def collect(memory_root: Path, cwd: Path, keywords: str) -> list[Candidate]:
    query_tokens = tokens(keywords)
    cwd_tokens = tokens(str(cwd))
    candidates: dict[str, Candidate] = {}

    for index, scope in index_paths(memory_root):
        scope_name = scope.partition(":")[2] if scope.startswith("project:") else ""
        project_affinity = len(tokens(scope_name) & cwd_tokens)
        for line in index.read_text(encoding="utf-8", errors="replace").splitlines():
            match = INDEX_ENTRY.match(line)
            if not match:
                continue
            label, raw_path, description = match.groups()
            note = (index.parent / raw_path).resolve()
            if note.name == "MEMORY.md" or not note.is_file() or not is_within(note, memory_root):
                continue

            relative = note.relative_to(memory_root.resolve()).as_posix()
            searchable = tokens(f"{label} {raw_path} {description}")
            exact = len(query_tokens & searchable)
            partial = sum(
                1
                for query in query_tokens
                if query not in searchable
                and any(query in term or term in query for term in searchable)
            )
            if exact == 0 and partial == 0:
                continue

            score = exact * 10 + partial * 3
            if scope.startswith("project:") and project_affinity:
                score += 6 * project_affinity
            elif scope == "general":
                score += 1

            candidate = Candidate(
                path=relative,
                description=description.strip()[:240],
                scope=scope,
                score=score,
            )
            previous = candidates.get(relative)
            if previous is None or candidate.score > previous.score:
                candidates[relative] = candidate

    return sorted(candidates.values(), key=lambda item: (-item.score, item.path))


def render_text(candidates: list[Candidate], max_bytes: int) -> str:
    header = "Memory candidates (index metadata only; open only if relevant):\n"
    if not candidates:
        return header + "  (no relevant indexed notes)\n"
    output = header
    for item in candidates:
        line = f"- [{item.scope}] {item.path} — {item.description}\n"
        if len((output + line).encode("utf-8")) > max_bytes:
            break
        output += line
    return output


def render_json(candidates: list[Candidate], max_bytes: int) -> str:
    selected: list[Candidate] = []
    for item in candidates:
        candidate_output = json.dumps(
            {"candidates": [asdict(value) for value in selected + [item]]},
            ensure_ascii=False,
            indent=2,
        ) + "\n"
        if len(candidate_output.encode("utf-8")) > max_bytes:
            break
        selected.append(item)
    return json.dumps(
        {"candidates": [asdict(value) for value in selected]},
        ensure_ascii=False,
        indent=2,
    ) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rank curated-memory notes without reading their bodies."
    )
    parser.add_argument(
        "--memory-root",
        default="~/.agents/brain-memory",
        help="Curated memory root (default: ~/.agents/brain-memory).",
    )
    parser.add_argument("--cwd", default=str(Path.cwd()), help="Active working directory.")
    parser.add_argument("--keywords", required=True, help="Three to eight task keywords.")
    parser.add_argument("--limit", type=int, default=5, help="Maximum candidates (1-10).")
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=4096,
        help="Maximum output size (512-16384 bytes).",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    args = parser.parse_args()

    memory_root = Path(args.memory_root).expanduser().resolve()
    if not memory_root.is_dir():
        print(f"ERROR: curated memory root not found: {memory_root}", file=sys.stderr)
        return 2
    if not 1 <= args.limit <= 10:
        parser.error("--limit must be between 1 and 10")
    if not 512 <= args.max_bytes <= 16384:
        parser.error("--max-bytes must be between 512 and 16384")

    ranked = collect(memory_root, Path(args.cwd).expanduser(), args.keywords)[: args.limit]
    output = render_json(ranked, args.max_bytes) if args.json else render_text(ranked, args.max_bytes)
    sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
