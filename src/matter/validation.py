"""Repository integrity checks, including semantic graph constraints."""

from pathlib import Path
from typing import Any
import re

from jsonschema import Draft202012Validator

from .jsonio import read
from .tickets import projections


def graph_errors(tickets: list[dict[str, Any]], requirements: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    by_id: dict[str, dict[str, Any]] = {}
    for ticket in tickets:
        if ticket["id"] in by_id:
            errors.append(f"duplicate ticket ID: {ticket['id']}")
        by_id[ticket["id"]] = ticket
        ac_ids = [a["id"] for a in ticket["acceptance"]]
        if len(set(ac_ids)) != len(ac_ids):
            errors.append(f"{ticket['id']}: duplicate acceptance ID")
    requirement_ids = [r["id"] for r in requirements]
    if len(requirement_ids) != len(set(requirement_ids)):
        errors.append("duplicate requirement ID")
    known = set(requirement_ids)
    covered: set[str] = set()
    for ticket in tickets:
        covered.update(ticket["requirements"])
        for req in ticket["requirements"]:
            if req not in known:
                errors.append(f"{ticket['id']}: unknown requirement {req}")
        for dep in ticket["depends_on"]:
            if dep not in by_id:
                errors.append(f"{ticket['id']}: missing dependency {dep}")
            else:
                if ticket.get("phase", 0) < by_id[dep].get("phase", 0):
                    errors.append(f"{ticket['id']}: phase precedes dependency {dep}")
                if ticket["status"] == "done" and by_id[dep]["status"] != "done":
                    errors.append(f"{ticket['id']}: done with unfinished dependency {dep}")
        if ticket["status"] == "done" and (ticket["completion"]["state"] != "passed" or not ticket["completion"]["evidence"]):
            errors.append(f"{ticket['id']}: done without passed evidence")
    for req in sorted(known - covered):
        errors.append(f"uncovered requirement: {req}")
    visited: set[str] = set()
    stack: list[str] = []

    def visit(ticket_id: str) -> None:
        if ticket_id in stack:
            errors.append("dependency cycle: " + " -> ".join(stack[stack.index(ticket_id):] + [ticket_id]))
            return
        if ticket_id in visited:
            return
        stack.append(ticket_id)
        for dep in by_id[ticket_id]["depends_on"]:
            if dep in by_id:
                visit(dep)
        stack.pop()
        visited.add(ticket_id)

    for ticket_id in sorted(by_id):
        visit(ticket_id)
    return errors


def markdown_link_errors(root: Path) -> list[str]:
    errors = []
    for path in sorted(root.rglob("*.md")):
        if any(part in {".git", ".venv", "build", "dist"} for part in path.relative_to(root).parts):
            continue
        content = re.sub(r"```.*?```", "", path.read_text(encoding="utf-8"), flags=re.S)
        for destination in re.findall(r"\[[^\]]*\]\(([^)]+)\)", content):
            destination = destination.strip().split(' "', 1)[0].strip("<>")
            if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", destination) or destination.startswith("#"):
                continue
            target = destination.split("#", 1)[0]
            if target and not (path.parent / target).exists():
                errors.append(f"{path.relative_to(root)}: broken local link {destination}")
    return errors


def validate(root: Path) -> dict[str, Any]:
    errors: list[str] = []
    schemas = {}
    for path in sorted((root / "schemas").glob("*.schema.json")):
        try:
            schema = read(path)
            Draft202012Validator.check_schema(schema)
            schemas[path.name] = schema
        except Exception as exc:
            errors.append(f"{path.relative_to(root)}: invalid schema: {exc}")
    tickets = []
    ticket_schema = schemas.get("ticket.schema.json")
    if ticket_schema is None:
        errors.append("missing valid ticket.schema.json")
    for path in sorted((root / "tickets/records").glob("*.json")):
        try:
            ticket = read(path)
            problems = list(Draft202012Validator(ticket_schema).iter_errors(ticket)) if ticket_schema else []
            if problems:
                errors.extend(f"{path.name} {list(p.absolute_path)}: {p.message}" for p in problems)
                continue
            if path.stem != ticket["id"]:
                errors.append(f"{path.name}: filename and ticket ID differ")
            tickets.append(ticket)
        except Exception as exc:
            errors.append(f"{path.relative_to(root)}: {exc}")
    if not tickets:
        errors.append("no valid ticket records")
    requirements = []
    try:
        requirements = read(root / "docs/requirements.json")
        Draft202012Validator(schemas["requirements.schema.json"]).validate(requirements)
    except Exception as exc:
        errors.append(f"requirements inventory invalid: {exc}")
        requirements = []
    if tickets and requirements:
        errors.extend(graph_errors(tickets, requirements))
        for relative, expected in projections(root, tickets, requirements).items():
            path = root / relative
            if not path.is_file() or path.read_text(encoding="utf-8") != expected:
                errors.append(f"generated projection stale: {relative}")
        expected_ids = {t["id"] for t in tickets}
        for path in (root / "tickets").glob("MAT-*.md"):
            if path.stem not in expected_ids:
                errors.append(f"orphan ticket projection: {path.name}")
    from .demo import run_fixture
    fixture_count = 0
    for path in sorted((root / "examples").glob("*.json")):
        try:
            fixture = read(path)
            Draft202012Validator(schemas["walkthrough.schema.json"]).validate(fixture)
            result = run_fixture(fixture, schema=schemas["walkthrough.schema.json"])
            if result != fixture["expected"]:
                errors.append(f"{path.name}: walkthrough differs from declared expected results")
            fixture_count += 1
        except Exception as exc:
            errors.append(f"{path.name}: invalid walkthrough: {exc}")
    if fixture_count == 0:
        errors.append("no valid walkthrough fixtures")
    errors.extend(markdown_link_errors(root))
    return {"ok": not errors, "tickets": len(tickets), "requirements": len(requirements),
            "schemas": len(schemas), "walkthroughs": fixture_count, "errors": errors}
