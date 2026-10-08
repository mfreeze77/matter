"""Regressions for scaffold input admission and projection integrity."""

from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from matter.__main__ import main
from matter.demo import Walkthrough, run_fixture
from matter.jsonio import loads, read
from matter.tickets import projections, render


ROOT = Path(__file__).resolve().parents[1]
SCOPE = "synthetic:hardening"


def observation(identity, minute, *, classification="material", qualified=True,
                effective=None, occurrence=None):
    return {
        "id": identity, "source": "fixture", "scope_id": SCOPE,
        "at": f"2026-10-01T09:{minute:02d}:00Z", "kind": "observation",
        "matter_key": "condition", "context_revision": "v1", "condition_id": "check",
        "occurrence_id": occurrence or identity,
        "effective_at": f"2026-10-01T09:{minute if effective is None else effective:02d}:00Z",
        "classification": classification, "host_qualified": qualified,
    }


def fixture(events):
    return {
        "schema_version": "1.0", "name": "Hardening fixture",
        "description": "Synthetic events for testing structural and lifecycle admission.",
        "scope_id": SCOPE, "audience": "reviewer", "events": events,
        "expected": {"outcomes": [], "delivered_updates": 0,
                     "forwarded_controls": [], "matters": {}},
    }


def ticket(identity="MAT-026"):
    return {
        "id": identity, "title": "A valid synthetic ticket", "track": "foundation",
        "phase": 0, "priority": "P0", "status": "planned", "type": "implementation",
        "owner_repo": "mfreeze77/matter", "component": "synthetic", "depends_on": [],
        "requirements": ["TEST-01"],
        "summary": "A synthetic ticket used to verify record and projection integrity.",
        "in_scope": ["Validate canonical records."], "out_of_scope": ["Production changes."],
        "implementation": ["Read the synthetic input.", "Validate it before writing outputs."],
        "acceptance": [
            {"id": "AC-1", "criterion": "Malformed records cannot be rendered.",
             "verification": "Submit a malformed later record and compare existing output."},
            {"id": "AC-2", "criterion": "Every dependency resolves to a valid ticket.",
             "verification": "Introduce a missing dependency and inspect the rejection."},
            {"id": "AC-3", "criterion": "Generated paths remain in the projection namespace.",
             "verification": "Try a symlink destination and check its target is unchanged."},
        ],
        "artifacts": ["tests/synthetic.py"],
        "tests": ["Reject path traversal.", "Reject incomplete records."],
        "risks": ["An invalid record could damage generated output."], "reuse": [],
        "sources": ["Synthetic test specification."],
        "completion": {"state": "not_run", "evidence": []},
    }


def requirements():
    return [{"id": "TEST-01", "title": "Safe projections",
             "description": "Generated output must follow validated canonical records.",
             "source": "Synthetic test specification."}]


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


class StrictJsonTests(unittest.TestCase):
    def test_nonfinite_constants_and_overflow_are_rejected(self):
        for literal in ("NaN", "Infinity", "-Infinity", "1e999", "-1e999"):
            with self.subTest(literal=literal), self.assertRaises(ValueError):
                loads('{"value": [' + literal + "]}")

    def test_duplicate_nested_keys_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
            loads('{"outer": {"value": 1, "value": 2}}')

    def test_finite_json_is_preserved(self):
        self.assertEqual(loads('{"count": 2, "probability": 5e-1, "qualified": false}'),
                         {"count": 2, "probability": 0.5, "qualified": False})


class WalkthroughHardeningTests(unittest.TestCase):
    def test_unqualified_material_does_not_reopen_or_advance_state(self):
        runner = Walkthrough(SCOPE, "reviewer")
        runner.apply(observation("failure", 0))
        runner.apply(observation("recovery", 1, classification="resolution"))
        before = deepcopy(runner.matters["condition"])

        self.assertEqual(runner.apply(observation("uncertain", 10, qualified=False)),
                         "material_unqualified")
        after = runner.matters["condition"]
        self.assertEqual(after.status, "resolved")
        for field in ("latest_effective", "resolved_at", "episode", "change", "occurrences", "pending"):
            self.assertEqual(getattr(after, field), getattr(before, field), field)
        self.assertEqual(after.observations, before.observations + 1)

    def test_unqualified_later_report_does_not_veto_qualified_recovery(self):
        runner = Walkthrough(SCOPE, "reviewer")
        runner.apply(observation("failure", 0))
        runner.apply(observation("uncertain", 10, qualified=False))
        outcome = runner.apply(observation("recovery", 11, classification="resolution", effective=5))
        self.assertEqual(outcome, "resolved")
        self.assertEqual(runner.result()["matters"]["condition"]["distinct_occurrences"], 1)

    def test_initial_unqualified_material_is_only_an_evidence_receipt(self):
        runner = Walkthrough(SCOPE, "reviewer")
        event = observation("uncertain", 0, qualified=False)
        self.assertEqual(runner.apply(event), "material_unqualified")
        self.assertEqual(runner.matters, {})
        self.assertIn(("fixture", "uncertain"), runner.seen)
        repeat = event | {"at": "2026-10-01T09:01:00Z"}
        self.assertEqual(runner.apply(repeat), "duplicate")
        self.assertEqual(runner.matters, {})

    def test_nonboolean_qualification_is_rejected_before_apply(self):
        for value in ("false", "true", 0, 1, None):
            with self.subTest(value=value):
                runner = Walkthrough(SCOPE, "reviewer")
                with self.assertRaises(ValueError):
                    runner.apply(observation("bad", 0, qualified=value))
                self.assertEqual(runner.seen, {})
                self.assertEqual(runner.matters, {})
                self.assertIsNone(runner.clock)

    def test_fixture_preflight_rejects_later_fault_before_first_apply(self):
        first = observation("first", 1)
        cases = {
            "wrong type": observation("bad", 2, qualified="false"),
            "cross scope": observation("bad", 2) | {"scope_id": "another-scope"},
            "backward time": observation("bad", 0),
            "future occurrence": observation("bad", 2, effective=3),
            "conflicting redelivery": first | {"at": "2026-10-01T09:02:00Z", "classification": "routine"},
        }
        for label, event in cases.items():
            with self.subTest(label=label), patch.object(Walkthrough, "apply") as apply:
                with self.assertRaises(ValueError):
                    run_fixture(fixture([first, event]))
                apply.assert_not_called()

    def test_conflicting_event_rolls_back_every_existing_field(self):
        runner = Walkthrough(SCOPE, "reviewer")
        event = observation("first", 0)
        runner.apply(event)
        before = deepcopy(runner.__dict__)
        conflict = event | {"at": "2026-10-01T09:01:00Z", "classification": "routine"}
        with self.assertRaisesRegex(ValueError, "identity reused"):
            runner.apply(conflict)
        self.assertEqual(runner.__dict__, before)

    def test_stop_bypasses_material_attention_and_clears_pending(self):
        runner = Walkthrough(SCOPE, "reviewer")
        runner.apply(observation("first", 0))
        control = {"id": "stop", "source": "host", "scope_id": SCOPE,
                   "at": "2026-10-01T09:01:00Z", "kind": "control", "instruction": "stop"}
        self.assertEqual(runner.apply(control), "forwarded_control")
        self.assertTrue(runner.paused)
        self.assertEqual(runner.matters["condition"].pending, {})
        self.assertEqual(runner.apply(observation("second", 2)), "recorded_while_paused")
        self.assertEqual(runner.delivered_updates, 0)

    def test_reports_do_not_expose_mutable_history_lists(self):
        runner = Walkthrough(SCOPE, "reviewer")
        runner.apply(observation("first", 0))
        result = runner.result()
        result["outcomes"].append("invented")
        result["forwarded_controls"].append("invented")
        self.assertEqual(runner.outcomes, ["eligible"])
        self.assertEqual(runner.controls, [])

    def test_existing_examples_match_their_declared_expected_values(self):
        for path in sorted((ROOT / "examples").glob("*.json")):
            with self.subTest(example=path.name):
                value = read(path)
                self.assertEqual(run_fixture(value), value["expected"])


class ProjectionHardeningTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.base = Path(directory.name)
        self.root = self.base / "repo"
        shutil.copytree(ROOT / "schemas", self.root / "schemas")
        write_json(self.root / "docs/requirements.json", requirements())
        write_json(self.root / "tickets/records/MAT-026.json", ticket())

    def test_malformed_later_record_causes_no_projection_writes(self):
        existing = self.root / "tickets/MAT-026.md"
        existing.write_text("unchanged\n", encoding="utf-8")
        invalid = ticket("MAT-027")
        invalid["id"] = "../../outside"
        write_json(self.root / "tickets/records/MAT-027.json", invalid)
        with self.assertRaises(ValueError):
            render(self.root)
        self.assertEqual(existing.read_text(), "unchanged\n")
        self.assertFalse((self.root / "tickets/index.json").exists())
        self.assertFalse((self.base / "outside.md").exists())

    def test_projection_function_rejects_invalid_id_itself(self):
        with self.assertRaisesRegex(ValueError, "invalid ticket ID"):
            projections(self.root, [ticket("../outside")], requirements())

    def test_missing_dependency_and_cycle_are_rejected_before_writes(self):
        for mode in ("missing", "cycle"):
            with self.subTest(mode=mode):
                first, second = ticket(), ticket("MAT-027")
                first["depends_on"] = ["MAT-027" if mode == "cycle" else "MAT-999"]
                second["depends_on"] = ["MAT-026"] if mode == "cycle" else []
                write_json(self.root / "tickets/records/MAT-026.json", first)
                write_json(self.root / "tickets/records/MAT-027.json", second)
                with self.assertRaisesRegex(ValueError, "invalid ticket graph"):
                    render(self.root)
                self.assertFalse((self.root / "tickets/MAT-026.md").exists())

    def test_filename_mismatch_cannot_create_a_different_ticket(self):
        write_json(self.root / "tickets/records/MAT-027.json", ticket("MAT-028"))
        with self.assertRaisesRegex(ValueError, "filename and ticket ID differ"):
            render(self.root)
        self.assertFalse((self.root / "tickets/MAT-028.md").exists())

    def test_late_symlink_destination_prevents_all_writes(self):
        outside = self.base / "outside.txt"
        inside = self.root / "README.md"
        for target in (outside, inside):
            with self.subTest(target=target.name):
                target.write_text("unchanged\n", encoding="utf-8")
                link = self.root / "docs/COVERAGE.md"
                link.symlink_to(target)
                try:
                    with self.assertRaisesRegex(ValueError, "symlink"):
                        render(self.root)
                    self.assertEqual(target.read_text(), "unchanged\n")
                    self.assertFalse((self.root / "tickets/MAT-026.md").exists())
                finally:
                    link.unlink()

    def test_late_directory_destination_prevents_all_writes(self):
        (self.root / "docs/COVERAGE.md").mkdir()
        with self.assertRaisesRegex(ValueError, "not a file"):
            render(self.root)
        self.assertFalse((self.root / "tickets/MAT-026.md").exists())

    def test_valid_render_and_check_do_not_confuse_stale_output_with_bad_input(self):
        self.assertEqual(render(self.root), [])
        self.assertEqual(render(self.root, check=True), [])
        output = self.root / "tickets/MAT-026.md"
        output.write_text("stale\n", encoding="utf-8")
        self.assertEqual(render(self.root, check=True), ["tickets/MAT-026.md"])
        self.assertEqual(output.read_text(), "stale\n")
        self.assertEqual(render(self.root), [])
        self.assertEqual(render(self.root, check=True), [])

    def test_ticket_title_is_one_escaped_markdown_table_cell(self):
        value = ticket()
        value["title"] = "Choice | Noul [review]\nSecond line"
        output = projections(self.root, [value], requirements())["tickets/INDEX.md"]
        row = next(line for line in output.splitlines() if line.startswith("| [MAT-"))
        self.assertIn(r"Choice \| Noul \[review\] Second line", row)
        self.assertEqual(len(re.findall(r"(?<!\\)\|", row)), 8)

    def test_demo_cli_preflights_all_fixtures_before_execution(self):
        for name in ("oil", "civic", "diat"):
            value = fixture([observation("first", 0)])
            if name == "diat":
                value["events"][0]["host_qualified"] = "false"
            write_json(self.root / "examples" / f"{name}.json", value)
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(sys, "argv", ["matter", "--root", str(self.root), "demo", "all"]), \
                patch.object(Walkthrough, "apply") as apply, \
                redirect_stdout(stdout), redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as error:
                main()
        self.assertEqual(error.exception.code, 2)
        apply.assert_not_called()
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("invalid walkthrough", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
