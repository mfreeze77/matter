"""MAT-081 portable shape checks; not a runtime adapter or access-control test."""

from copy import deepcopy
import hashlib
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator
from referencing import Registry

from matter.canonical import loads
from matter.contracts import _FORMAT_CHECKER


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/fixtures/civic/handoff"
SCHEMA = ROOT / "docs/contracts/monitoring-handoff.schema.json"


def read(path):
    return loads(path.read_bytes())


class MonitoringHandoffContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = read(SCHEMA)
        Draft202012Validator.check_schema(cls.schema)
        # Local definitions only. No network retrieval or host capabilities.
        cls.validator = Draft202012Validator(
            cls.schema, registry=Registry(), format_checker=_FORMAT_CHECKER
        )
        cls.manifest = read(FIXTURES / "manifest.json")
        cls.request_validator = Draft202012Validator(
            {"$ref": "#/$defs/request", "$defs": cls.schema["$defs"]},
            registry=Registry(), format_checker=_FORMAT_CHECKER,
        )

    def test_portable_core_fragments_match_governing_schema(self):
        self.assertEqual(self.schema, read(ROOT / "schemas/monitoring-handoff.schema.json"))
        core = read(ROOT / "schemas/core-record.schema.json")["$defs"]
        for name in read(FIXTURES / "core-fragments.json"):
            with self.subTest(fragment=name):
                self.assertEqual(self.schema["$defs"][name], core[name])

    def test_all_request_and_response_examples_are_wire_compatible(self):
        for case in self.manifest["cases"]:
            for key in ("request", "expected"):
                with self.subTest(case=case["id"], message=key):
                    message = read(FIXTURES / case[key])
                    self.validator.validate(message)
                    self.assertEqual(message["contract_version"], self.manifest["contract_version"])
            self.assertFalse(case["runtime_executed"])

    def test_invalid_wire_vectors_are_rejected(self):
        def leaves(error):
            yield error
            for child in error.context:
                yield from leaves(child)

        def changed_paths(left, right, path=()):
            if isinstance(left, dict) and isinstance(right, dict):
                for key in left.keys() | right.keys():
                    if key not in left or key not in right:
                        yield [*path, key]
                    else:
                        yield from changed_paths(left[key], right[key], (*path, key))
            elif left != right:
                yield list(path)

        for case in self.manifest["invalid_wire_vectors"]:
            with self.subTest(case=case["id"]):
                base = read(FIXTURES / case["base"])
                self.request_validator.validate(base)
                invalid = read(FIXTURES / case["file"])
                self.assertNotEqual(base, invalid)
                self.assertCountEqual(list(changed_paths(base, invalid)), case["mutated_paths"])
                target = case["expected_error_path"]
                errors = [leaf for error in self.request_validator.iter_errors(invalid)
                          for leaf in leaves(error)]
                self.assertTrue(any(
                    list(error.absolute_path) == target
                    or (list(error.absolute_path) == target[:-1]
                        and error.validator in {"required", "additionalProperties"}
                        and repr(target[-1]) in error.message)
                    for error in errors
                ), [(list(error.absolute_path), error.message) for error in errors])

    def test_schema_does_not_claim_to_check_semantic_authority(self):
        semantic = {case["id"] for case in self.manifest["cases"]
                    if case["category"] == "semantic_refusal_example"}
        self.assertEqual(semantic, {"unknown-outcome", "future-source", "foreign-client",
                                    "stale-intent", "missing-host-controls", "foreign-jurisdiction"})
        for name in semantic:
            # These wire-valid examples need actual MAT-082/host runtime guards.
            self.validator.validate(read(FIXTURES / f"{name}-request.json"))
            self.assertEqual(read(FIXTURES / f"{name}-expected.json")["message_type"],
                             "monitoring_refusal")
        self.assertFalse(self.manifest["runtime_executed"])
        self.assertEqual(self.manifest["status"], "frozen_compatibility_examples")

    def test_contrasting_audiences_keep_shared_facts_and_separate_contexts(self):
        a, b = (read(FIXTURES / f"client-{name}-request.json") for name in ("a", "b"))
        ra, rb = (read(FIXTURES / f"client-{name}-expected.json") for name in ("a", "b"))
        self.assertEqual(a["evidence"], b["evidence"])
        self.assertNotEqual(a["context_components"], b["context_components"])
        self.assertNotEqual(a["host_binding"]["client_id"], b["host_binding"]["client_id"])
        self.assertEqual(ra["source_finding_reference"], rb["source_finding_reference"])
        self.assertEqual((ra["treatment"], rb["treatment"]), ("digest", "quiet"))
        self.assertIsNone(read(FIXTURES / "personal-request.json")["host_binding"]["client_id"])
        second = read(FIXTURES / "second-objective-request.json")
        self.assertEqual(a["host_binding"]["client_id"], second["host_binding"]["client_id"])
        self.assertNotEqual(a["intent"]["id"], second["intent"]["id"])

        personal = read(FIXTURES / "personal-request.json")
        requests = [a, b, second, personal]
        for field in ("id", "revision_id", "content_hash"):
            self.assertEqual(len({r["intent"][field] for r in requests}), len(requests))
        self.assertEqual(len({r["idempotency_key"] for r in requests}), len(requests))
        # D1 permits two objectives sharing an owned target; only cross-audience
        # fixture targets are distinct here, not a mandatory one-item-per-intent policy.
        for field in ("watchlist_item_id", "user_activity_event_id"):
            self.assertEqual(len({r["capture_binding"][field] for r in (a, b, personal)}), 3)
        for component in ("audience", "responsibility"):
            self.assertEqual(len({r["context_components"][component]["digest"] for r in requests}), len(requests))
        self.assertEqual(second["intent"]["defaults"]["profile_reference"],
                         a["intent"]["defaults"]["profile_reference"])
        self.assertIsNone(personal["intent"]["defaults"]["profile_reference"])

    def test_record_scope_and_distinct_commands_do_not_alias(self):
        record = read(FIXTURES / "record-request.json")
        objective = read(FIXTURES / "client-a-request.json")
        self.assertEqual(record["intent"]["scope"]["kind"], "record")
        self.assertEqual(objective["intent"]["scope"]["kind"], "objective")
        for field in ("id", "revision_id", "content_hash"):
            self.assertNotEqual(record["intent"][field], objective["intent"][field])
        self.assertNotEqual(record["context_components"]["scope"],
                            objective["context_components"]["scope"])
        keys = [read(FIXTURES / case["request"])["idempotency_key"]
                for case in self.manifest["cases"]]
        self.assertEqual(len(keys), len(set(keys)))

    def test_handled_feedback_is_scoped_outside_immutable_intent(self):
        correction = read(FIXTURES / "correction-request.json")
        handled = read(FIXTURES / "handled-correction-request.json")
        self.assertEqual(handled["intent"], correction["intent"])
        self.assertEqual(handled["context_components"], correction["context_components"])
        self.assertTrue(handled["dispositions"])
        self.assertNotIn("already_handled", handled["intent"]["responsibility"])
        self.assertEqual(read(FIXTURES / "handled-correction-expected.json")["treatment"], "correction")

    def test_uncorrelatable_errors_do_not_echo_invalid_request_identifiers(self):
        refusal = read(FIXTURES / "uncorrelatable-refusal.json")
        self.validator.validate(refusal)
        self.assertIsNone(refusal["request_id"])
        changed = deepcopy(refusal)
        changed.update(code="E_DELIVERY_UNKNOWN", reason="outcome_unknown")
        self.assertTrue(list(self.validator.iter_errors(changed)))

    def test_unknown_times_are_explicit_and_invalid_times_rejected(self):
        original = read(FIXTURES / "client-a-request.json")
        self.assertEqual(original["evidence"]["sources"][0]["occurred_at"]["state"], "unknown")
        changed = deepcopy(original)
        changed["evidence"]["sources"][0]["available_at"]["value"] = "2026-02-30T09:00:00Z"
        self.assertTrue(list(self.validator.iter_errors(changed)))

    def test_frozen_inventory_pins_exact_fixture_and_schema_bytes(self):
        inventory = read(FIXTURES / "contract-lock.json")
        self.assertEqual(inventory["contract_version"], self.manifest["contract_version"])
        self.assertEqual(inventory["status"], "frozen_compatibility_examples")
        expected = {str(SCHEMA.relative_to(ROOT)), "schemas/monitoring-handoff.schema.json",
                    "docs/contracts/monitoring-handoff.md", "docs/decisions/0002-monitoring-handoff.md"} | {
            str(path.relative_to(ROOT)) for path in FIXTURES.glob("*.json")
            if path.name != "contract-lock.json"
        }
        actual = {entry["path"] for entry in inventory["artifacts"]}
        self.assertEqual(len(actual), len(inventory["artifacts"]))
        self.assertEqual(actual, expected)
        for entry in inventory["artifacts"]:
            with self.subTest(path=entry["path"]):
                self.assertEqual(hashlib.sha256((ROOT / entry["path"]).read_bytes()).hexdigest(),
                                 entry["sha256"])


if __name__ == "__main__":
    unittest.main()
