from __future__ import annotations

from evidence_json import ContractError, JsonValue


def _array(value: JsonValue, name: str) -> list[JsonValue]:
    if not isinstance(value, list):
        raise ContractError(f"{name} must be an array")
    return value


def validate_operating_model(value: dict[str, JsonValue]) -> None:
    graph = _array(value.get("dependency_graph"), "dependency_graph")
    todos = [row.get("todo") for row in graph if isinstance(row, dict)]
    if todos != list(range(1, 20)):
        raise ContractError("dependency graph must contain sorted todos 1 through 19")
    for row in graph:
        if not isinstance(row, dict) or not isinstance(row.get("depends_on"), list):
            raise ContractError("invalid dependency row")
        todo = row["todo"]
        dependencies = row["depends_on"]
        if dependencies != sorted(set(dependencies)) or any(
            not isinstance(item, int) or item >= todo for item in dependencies
        ):
            raise ContractError("dependency graph is cyclic, duplicate, or out of order")
    routes = _array(value.get("future_routes"), "future_routes")
    route_ids = [row.get("route_id") for row in routes if isinstance(row, dict)]
    expected = [
        "skill.constraints",
        "skill.documentation",
        "skill.session-routing",
        "skill.tool-catalog",
    ]
    if route_ids != expected:
        raise ContractError("future route IDs differ from the frozen set")
    temporary: set[str] = set()
    final: set[str] = set()
    scenarios: set[str] = set()
    for row in routes:
        if not isinstance(row, dict):
            raise ContractError("invalid future route")
        scenario = row.get("scenario_id")
        if not isinstance(scenario, str) or scenario in scenarios:
            raise ContractError("future scenario IDs must be unique")
        scenarios.add(scenario)
        before = row.get("temporary_payloads")
        after = row.get("final_payloads")
        if not isinstance(before, list) or not isinstance(after, list):
            raise ContractError("future payload mappings must be arrays")
        temporary.update(str(item) for item in before)
        final.update(str(item) for item in after)
    if temporary & final:
        raise ContractError("temporary and final payload mappings overlap")


def validate_ledger(value: dict[str, JsonValue]) -> None:
    documents = _array(value.get("documents"), "documents")
    paths: list[str] = []
    ids: set[str] = set()
    for document in documents:
        if not isinstance(document, dict) or not isinstance(document.get("path"), str):
            raise ContractError("invalid ledger document")
        path = document["path"]
        paths.append(path)
        ranges = _array(document.get("ranges"), "ranges")
        expected_start = 1
        for row in ranges:
            if not isinstance(row, dict):
                raise ContractError("invalid ledger range")
            if row.get("start_line") != expected_start:
                raise ContractError("ledger range gap or overlap")
            end = row.get("end_line")
            identifier = row.get("id")
            sha256 = row.get("sha256")
            if (
                not isinstance(end, int)
                or end < expected_start
                or not isinstance(identifier, str)
                or identifier in ids
                or not isinstance(sha256, str)
                or len(sha256) != 64
            ):
                raise ContractError("invalid ledger range contract")
            ids.add(identifier)
            expected_start = end + 1
    if paths != sorted(set(paths)):
        raise ContractError("ledger documents must be unique and sorted")
    claims = _array(value.get("relocation_claims"), "relocation_claims")
    for claim in claims:
        if not isinstance(claim, dict) or claim.get("approval_required") is not True:
            raise ContractError("relocation claim weakens copy-before-trim")
        status = claim.get("status")
        if status == "destination-unverified":
            continue
        if status != "copy-then-trim":
            raise ContractError("relocation claim weakens copy-before-trim")
        destination = claim.get("copied_destination")
        sources = claim.get("source_evidence")
        if not isinstance(destination, dict) or not isinstance(sources, list):
            raise ContractError("copy-then-trim claim lacks hash evidence")
        if not isinstance(destination.get("heading"), str) or not isinstance(
            destination.get("sha256"), str
        ):
            raise ContractError("copy-then-trim destination evidence is incomplete")
        for source in sources:
            if not isinstance(source, dict) or not isinstance(source.get("sha256"), str):
                raise ContractError("copy-then-trim source evidence is incomplete")


def validate_qa(value: dict[str, JsonValue]) -> None:
    todos = _array(value.get("todos"), "todos")
    if [item.get("todo") for item in todos if isinstance(item, dict)] != list(range(1, 20)):
        raise ContractError("QA manifest must contain todos 1 through 19")
    for todo in todos:
        if not isinstance(todo, dict):
            raise ContractError("invalid QA todo")
        steps = _array(todo.get("steps"), "steps")
        if [step.get("step") for step in steps if isinstance(step, dict)] != list(
            range(1, len(steps) + 1)
        ):
            raise ContractError("QA steps must be contiguous")
        for step in steps:
            if (
                not isinstance(step, dict)
                or step.get("mode") not in {"argv", "shell"}
                or not isinstance(step.get("command"), str)
                or not step["command"]
            ):
                raise ContractError("invalid QA command")


def validate_schema(value: dict[str, JsonValue]) -> None:
    schema = value.get("schema_version")
    if schema == "agent-brain-operating-model/v1":
        validate_operating_model(value)
    elif schema == "agent-brain-operating-model-ledger/v1":
        validate_ledger(value)
    elif schema == "agent-brain-qa-commands/v1":
        validate_qa(value)
