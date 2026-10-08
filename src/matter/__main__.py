"""Command-line tools for the Matter repository scaffold."""

import argparse
import json
from pathlib import Path


def repository_root(value: str | None) -> Path:
    if value:
        root = Path(value).resolve()
        if (root / "schemas/ticket.schema.json").is_file():
            return root
        raise ValueError(f"not a Matter scaffold root: {root}")
    for path in (Path.cwd(), *Path.cwd().parents):
        if (path / "schemas/ticket.schema.json").is_file():
            return path
    raise ValueError("run from the Matter checkout or pass --root PATH")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate, inspect and demonstrate the Matter planning scaffold.")
    parser.add_argument("--root", help="repository checkout containing schemas/ and tickets/")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate", help="validate schemas, ticket graph, coverage, projections, links and examples")
    render_parser = sub.add_parser("render", help="regenerate ticket Markdown, index and coverage")
    render_parser.add_argument("--check", action="store_true")
    tickets_parser = sub.add_parser("tickets", help="show tickets and dependency readiness")
    tickets_parser.add_argument("--ready", action="store_true")
    demo_parser = sub.add_parser("demo", help="run a synthetic deterministic contract walkthrough")
    demo_parser.add_argument("name", choices=["oil", "civic", "diat", "all"], default="all", nargs="?")
    args = parser.parse_args()
    try:
        root = repository_root(args.root)
        if args.command == "validate":
            from .validation import validate
            result = validate(root)
            print(json.dumps(result, indent=2))
            return 0 if result["ok"] else 1
        if args.command == "render":
            from .tickets import render
            mismatches = render(root, check=args.check)
            print(json.dumps({"ok": not mismatches, "stale": mismatches, "mode": "check" if args.check else "write"}, indent=2))
            return int(bool(mismatches))
        if args.command == "tickets":
            from .tickets import load_inventory, readiness
            tickets, _ = load_inventory(root)
            by_id = {t["id"]: t for t in tickets}
            selected = [{"id": t["id"], "title": t["title"], "readiness": readiness(t, by_id), "depends_on": t["depends_on"]}
                        for t in tickets if not args.ready or readiness(t, by_id) == "ready"]
            print(json.dumps(selected, indent=2))
            return 0
        from .demo import run_fixture, validate_fixture
        from .jsonio import read
        names = ["oil", "civic", "diat"] if args.name == "all" else [args.name]
        schema = read(root / "schemas/walkthrough.schema.json")
        fixtures = {name: read(root / "examples" / f"{name}.json") for name in names}
        for fixture in fixtures.values():
            validate_fixture(fixture, schema=schema)
        results = {name: run_fixture(fixture, schema=schema) for name, fixture in fixtures.items()}
        print(json.dumps(results, indent=2))
        return 0
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(2, f"matter: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
