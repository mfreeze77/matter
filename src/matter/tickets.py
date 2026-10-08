"""Deterministic projections of the canonical ticket records."""

from collections import Counter
from pathlib import Path
from typing import Any
import json
import re

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from .jsonio import read


def _schema(root: Path, filename: str) -> dict[str, Any]:
    schema = read(root / "schemas" / filename)
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise ValueError(f"invalid {filename}: {exc.message}") from exc
    return schema


def _validate(value: Any, schema: dict[str, Any], label: str) -> None:
    problem = next(Draft202012Validator(schema).iter_errors(value), None)
    if problem is not None:
        raise ValueError(f"invalid {label} {list(problem.absolute_path)}: {problem.message}")


def _ticket_id(value: Any) -> str:
    if not isinstance(value, str) or re.fullmatch(r"MAT-[0-9]{3}", value) is None:
        raise ValueError(f"invalid ticket ID: {value!r}")
    return value


def load_tickets(root: Path) -> list[dict[str, Any]]:
    """Load only schema-valid records with filenames matching their safe IDs."""
    schema = _schema(root, "ticket.schema.json")
    tickets = []
    for path in sorted((root / "tickets/records").glob("*.json")):
        ticket = read(path)
        _validate(ticket, schema, path.name)
        identity = _ticket_id(ticket["id"])
        if path.stem != identity:
            raise ValueError(f"{path.name}: filename and ticket ID differ")
        tickets.append(ticket)
    if not tickets:
        raise ValueError("no valid ticket records")
    return tickets


def load_inventory(root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Preflight source data without requiring generated projections to be current."""
    tickets = load_tickets(root)
    requirements = read(root / "docs/requirements.json")
    _validate(requirements, _schema(root, "requirements.schema.json"), "requirements inventory")
    # Local import avoids the validator/projection module import cycle.
    from .validation import graph_errors
    problems = graph_errors(tickets, requirements)
    if problems:
        raise ValueError("invalid ticket graph: " + "; ".join(problems))
    return tickets, requirements


def readiness(ticket: dict[str, Any], tickets: dict[str, dict[str, Any]]) -> str:
    if ticket["status"] != "planned":
        return ticket["status"]
    return "ready" if all(tickets.get(dep, {}).get("status") == "done" for dep in ticket["depends_on"]) else "waiting"


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items) if items else "- None declared."


def _inline(value: str) -> str:
    return " ".join(value.splitlines())


def _table(value: str) -> str:
    return _inline(value).replace("\\", "\\\\").replace("|", "\\|")


def _link_label(value: str) -> str:
    return _table(value).replace("[", "\\[").replace("]", "\\]")


def render_ticket(ticket: dict[str, Any], root: Path) -> str:
    t = ticket
    dependencies = ", ".join(f"[{d}]({d}.md)" for d in t["depends_on"]) or "None"
    text = [f"# {t['id']}: {_inline(t['title'])}",
            "<!-- Generated from records/; edit the JSON and run python -m matter render. -->",
            f"**Status:** {t['status']} · **Track:** {t['track']} · **Phase:** {t['phase']} · **Priority:** {t['priority']}",
            f"**Type:** {t['type']} · **Owner repository:** `{t['owner_repo']}` · **Component:** `{t['component']}`",
            f"**Dependencies:** {dependencies}",
            f"**Requirements:** {', '.join(t['requirements'])}",
            "## Purpose", t["summary"], "## In scope", _bullets(t["in_scope"]),
            "## Scope boundaries", _bullets(t["out_of_scope"]), "## Implementation",
            "\n".join(f"{i}. {step}" for i, step in enumerate(t["implementation"], 1)),
            "## Acceptance criteria"]
    for criterion in t["acceptance"]:
        text += [f"### {criterion['id']}", criterion["criterion"], f"**Verify:** {criterion['verification']}"]
    text += ["## Planned artifacts", _bullets([f"`{p}`" for p in t["artifacts"]]),
             "## Required test cases", _bullets(t["tests"]), "## Risks", _bullets(t["risks"]),
             "## Existing work to inspect and reuse"]
    text += [f"- {entry['source']} — {entry['application']}" for entry in t["reuse"]] or ["No reuse source declared."]
    text += ["## Sources"]
    for source in t["sources"]:
        if source.startswith(("https://", "http://")):
            text.append(f"- [Source]({source})")
        elif (root / source).is_file():
            text.append(f"- [{source}](../{source})")
        else:
            text.append(f"- {source}")
    text += ["## Completion evidence", f"**Validation state:** {t['completion']['state']}",
             _bullets(t["completion"]["evidence"])]
    return "\n\n".join(text) + "\n"


def projections(root: Path, tickets: list[dict[str, Any]], requirements: list[dict[str, Any]]) -> dict[str, str]:
    for ticket in tickets:
        _ticket_id(ticket["id"])
    by_id = {t["id"]: t for t in tickets}
    outputs = {f"tickets/{t['id']}.md": render_ticket(t, root) for t in tickets}
    records = [{k: t[k] for k in ("id", "title", "track", "phase", "priority", "status", "owner_repo", "depends_on", "requirements")} |
               {"readiness": readiness(t, by_id), "path": f"records/{t['id']}.json"} for t in tickets]
    index = {"schema_version": "1.0", "ticket_count": len(tickets),
             "counts_by_track": dict(sorted(Counter(t["track"] for t in tickets).items())),
             "counts_by_status": dict(sorted(Counter(t["status"] for t in tickets).items())), "tickets": records}
    outputs["tickets/index.json"] = json.dumps(index, indent=2, ensure_ascii=False) + "\n"
    lines = ["# Implementation backlog", "", "Generated from the canonical JSON records. Readiness means recorded dependencies are complete; it does not assert qualification or completion.",
             "", "Future work in another repository remains owned by that repository. This scaffold does not execute those changes.", "",
             "| Ticket | Track | Phase | Priority | Status | Readiness | Depends on |",
             "|---|---|---:|---|---|---|---|"]
    for t in tickets:
        fields = [f"[{t['id']}: {_link_label(t['title'])}]({t['id']}.md)",
                  _table(t["track"]), str(t["phase"]), _table(t["priority"]),
                  _table(t["status"]), _table(readiness(t, by_id)),
                  _table(", ".join(t["depends_on"]) or "—")]
        lines.append("| " + " | ".join(fields) + " |")
    outputs["tickets/INDEX.md"] = "\n".join(lines) + "\n"
    lines = ["# Requirement coverage", "", "Every inventory requirement maps to at least one implementation or qualification ticket. Coverage records planned work; it is not a claim of implemented behavior.", "",
             "| Requirement | Description | Tickets |", "|---|---|---|"]
    for requirement in requirements:
        links = ", ".join(f"[{t['id']}](../tickets/{t['id']}.md)" for t in tickets if requirement["id"] in t["requirements"])
        desc = _table(requirement["title"] + ": " + requirement["description"])
        lines.append(f"| {_table(requirement['id'])} | {desc} | {links} |")
    outputs["docs/COVERAGE.md"] = "\n".join(lines) + "\n"
    return outputs


def _projection_path(root: Path, relative: str) -> Path:
    """Reject anything outside the fixed projection namespace, including links."""
    if relative not in {"tickets/INDEX.md", "tickets/index.json", "docs/COVERAGE.md"} and re.fullmatch(
        r"tickets/MAT-[0-9]{3}\.md", relative
    ) is None:
        raise ValueError(f"invalid projection destination: {relative}")
    root = root.resolve()
    path = root
    parts = Path(relative).parts
    for index, part in enumerate(parts):
        path = path / part
        if path.is_symlink():
            raise ValueError(f"projection destination contains a symlink: {relative}")
        if path.exists() and index < len(parts) - 1 and not path.is_dir():
            raise ValueError(f"projection parent is not a directory: {relative}")
    if path.exists() and not path.is_file():
        raise ValueError(f"projection destination is not a file: {relative}")
    return path


def render(root: Path, *, check: bool = False) -> list[str]:
    tickets, requirements = load_inventory(root)
    outputs = projections(root, tickets, requirements)
    # Validate every record, render every string, and check every destination
    # before the first write. Invalid later data cannot leave earlier outputs.
    planned = [(relative, _projection_path(root, relative), text) for relative, text in outputs.items()]
    mismatches = []
    for relative, path, text in planned:
        if check:
            if not path.is_file() or path.read_text(encoding="utf-8") != text:
                mismatches.append(relative)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
    return mismatches
