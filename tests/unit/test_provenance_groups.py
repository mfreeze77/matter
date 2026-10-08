"""Declared dependence over exact synthetic evidence, without source inference."""

from copy import deepcopy
import hashlib
from importlib.resources import files
import json
from pathlib import Path
import unittest

from matter.canonical import canonical_bytes
from matter.provenance_groups import (
    ASSIGNMENT_NAMESPACE, ASSIGNMENT_SCHEMA, assignment_ref, assignment_schema_ref,
    assignment_value, read_assignment, resolve_groups, root_watch_key,
)
from matter.storage import StorageError, entity_ref, pin


SCOPE = "synthetic:provenance-groups"
GROUP = {"namespace": "example:lineage", "value": "source:one"}
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/contracts/records/observation.json"


def observation(identity="one", *, parents=(), origin="source", scope=SCOPE):
    value = json.loads(FIXTURE.read_text())
    value.update(scope_id=scope, id=identity)
    value["creation_receipt"]["scope_id"] = scope
    value["body"]["source_identity"]["event_id"] = "source:" + identity
    value["provenance"].update(origin=origin, parents=deepcopy(list(parents)), run_id="run:" + identity)
    return value


def declaration(group=GROUP):
    return {"status": "declared", "group": deepcopy(group)}


def assigned(value, assignment=None, *, revision=1):
    """Also permits forged ineligible assignments for stored-integrity cases."""
    return {
        "schema_version": "1.0", **assignment_ref(SCOPE, pin(value)), "revision": revision,
        "creation_receipt": {"scope_id": SCOPE, "namespace": "example", "record_type": "receipt", "id": "assignment:receipt"},
        "value": {
            "schema": assignment_schema_ref(),
            "value": {"scope_id": SCOPE, "observation": pin(value), "assignment": deepcopy(assignment or declaration())},
        },
        "watch_keys": [],
    }


def identity(value):
    return value["scope_id"], value["namespace"], value["id"]


class Port:
    """Return shared values intentionally, so callers must detach their results."""

    def __init__(self, observations=(), assignments=(), *, get_error=None, lookup_error=None):
        self.observations = {identity(value): value for value in observations}
        self.assignments = {identity(value): value for value in assignments}
        self.get_error, self.lookup_error = get_error, lookup_error
        self.reads, self.lookups = [], []

    def get(self, reference):
        self.reads.append(deepcopy(reference))
        if self.get_error is not None:
            raise self.get_error
        try:
            return self.observations[identity(reference)]
        except KeyError:
            raise StorageError("E_NOT_FOUND") from None

    def lookup_identity(self, reference):
        self.lookups.append(deepcopy(reference))
        if self.lookup_error is not None:
            raise self.lookup_error
        try:
            return self.assignments[identity(reference)]
        except KeyError:
            raise StorageError("E_NOT_FOUND") from None


class ProvenanceTests(unittest.TestCase):
    def assert_error(self, code, operation, *args, **kwargs):
        with self.assertRaises(StorageError) as caught:
            operation(*args, **kwargs)
        self.assertEqual(code, caught.exception.code)
        return caught.exception

    def resolve(self, port, *values, **kwargs):
        return resolve_groups(port, SCOPE, [pin(value) for value in values], **kwargs)

    def test_assignment_descriptor_binds_exact_packaged_schema_bytes(self):
        content = files("matter._schemas").joinpath("provenance-root-assignment.schema.json").read_bytes()
        self.assertEqual(ASSIGNMENT_SCHEMA, json.loads(content)["$id"])
        self.assertEqual({"namespace": "matter", "id": "provenance-root-assignment", "version": "1.0",
                          "digest": hashlib.sha256(content).hexdigest()}, assignment_schema_ref())
        detached = assignment_schema_ref()
        detached["digest"] = "changed"
        self.assertNotEqual(detached, assignment_schema_ref())

    def test_assignment_identity_is_scoped_bare_identity_with_pin_verified_in_value(self):
        value = observation()
        reference = pin(value)
        wrong_pin = {**reference, "digest": "f" * 64}
        first = assignment_ref(SCOPE, reference)
        self.assertEqual(ASSIGNMENT_NAMESPACE, first["namespace"])
        self.assertEqual(first, assignment_ref(SCOPE, wrong_pin))
        self.assertEqual(root_watch_key(SCOPE, reference), root_watch_key(SCOPE, wrong_pin))
        other = observation(scope="synthetic:other")
        self.assertNotEqual(first["id"], assignment_ref(other["scope_id"], pin(other))["id"])
        self.assert_error("E_SCHEMA_INVALID", assignment_ref, SCOPE, entity_ref(value))
        self.assert_error("E_SCOPE_FORBIDDEN", assignment_ref, SCOPE, pin(other))
        forged = assigned(value)
        forged["value"]["value"]["observation"] = wrong_pin
        self.assert_error("E_EVIDENCE_INVALID", read_assignment, Port(assignments=[forged]), SCOPE, value)

    def test_assignment_values_are_detached_and_keep_exact_keys(self):
        value, decision = observation(), declaration({"namespace": "Example:lineage", "value": "e\u0301"})
        expected = deepcopy(decision)
        result = assignment_value(SCOPE, value, decision)
        self.assertEqual(expected, result["value"]["assignment"])
        self.assertEqual(pin(value), result["value"]["observation"])
        result["value"]["assignment"]["group"]["value"] = "changed"
        result["value"]["observation"]["digest"] = "0" * 64
        self.assertEqual(expected, decision)
        self.assertEqual(pin(value), assignment_value(SCOPE, value, decision)["value"]["observation"])

    def test_assignment_requires_eligible_root_and_exclusive_shape(self):
        root = observation()
        for origin in ("source", "host", "adapter", "system"):
            with self.subTest(origin=origin):
                self.assertEqual(declaration(), assignment_value(SCOPE, observation(origin=origin), declaration())["value"]["assignment"])
        for value in (observation(origin="evaluator"), observation(parents=[pin(root)]),
                      observation(parents=[pin(root)], origin="derived")):
            self.assert_error("E_EVIDENCE_INVALID", assignment_value, SCOPE, value, declaration())
        for decision in ({}, {"status": "unknown"}, {"status": "unknown", "reason": "", "group": GROUP},
                         {**declaration(), "reason": "extra"}, {**declaration(), "observation": pin(root)},
                         {"status": "declared", "group": {**GROUP, "extra": True}}, None):
            with self.subTest(decision=decision):
                self.assert_error("E_SCHEMA_INVALID", assignment_value, SCOPE, root, decision)

    def test_stored_assignment_requires_exact_projection_schema_and_no_watches(self):
        value, valid = observation(), assigned(observation())
        mutations = [
            lambda item: item.update(watch_keys=["unexpected-assignment-watch"]),
            lambda item: item.update(record_type="matter"),
            lambda item: item.update(id="wrong-target"),
            lambda item: item["creation_receipt"].update(scope_id="foreign"),
            lambda item: item["value"]["schema"].update(digest="0" * 64),
            lambda item: item["value"]["schema"].update(version="2.0"),
            lambda item: item["value"]["value"].update(scope_id="foreign"),
            lambda item: item["value"]["value"].update(extra="ignored?"),
            lambda item: item["value"]["value"]["observation"].update(digest="0" * 64),
            lambda item: item["value"]["value"].pop("assignment"),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                broken = deepcopy(valid)
                mutate(broken)
                port = Port()
                port.assignments[identity(valid)] = broken
                self.assert_error("E_EVIDENCE_INVALID", read_assignment, port, SCOPE, value)
        returned = read_assignment(Port(assignments=[valid]), SCOPE, value)
        returned["value"]["value"]["assignment"]["group"]["value"] = "changed"
        self.assertEqual(GROUP, valid["value"]["value"]["assignment"]["group"])

    def test_absent_assignment_is_distinct_from_storage_and_revision_failure(self):
        value = observation()
        self.assertIsNone(read_assignment(Port(), SCOPE, value))
        for code in ("E_STORAGE_UNAVAILABLE", "E_REVISION_CONFLICT", "E_SCOPE_FORBIDDEN"):
            error = StorageError(code, "Synthetic port failure.", retriable=True)
            with self.subTest(code=code):
                self.assertIs(error, self.assert_error(code, read_assignment, Port(lookup_error=error), SCOPE, value))
                self.assertIs(error, self.assert_error(code, self.resolve, Port([value], lookup_error=error), value))
                self.assertIs(error, self.assert_error(code, self.resolve, Port(get_error=error), value))

    def test_declared_root_returns_actual_observation_and_assignment_pins(self):
        value = observation()
        assignment = assigned(value)
        result = self.resolve(Port([value], [assignment]), value)
        self.assertEqual([GROUP], result["groups"])
        self.assertEqual([pin(value)], result["roots"])
        self.assertCountEqual([pin(value), pin(assignment)], result["dependencies"])
        self.assertEqual([root_watch_key(SCOPE, pin(value))], result["watch_keys"])
        self.assertEqual([], result["unresolved"])
        self.assertEqual("complete", result["provenance_coverage"]["status"])

    def test_unassigned_and_explicit_unknown_are_visible_without_invented_groups(self):
        value = observation()
        unassigned = self.resolve(Port([value]), value)
        unknown = assigned(value, {"status": "unknown", "reason": "Publisher dependence is unknown."})
        explicit = self.resolve(Port([value], [unknown]), value)
        self.assertEqual([{"observation": pin(value), "reason": "unassigned_root"}], unassigned["unresolved"])
        self.assertEqual([{"observation": pin(value), "reason": "unknown_root", "detail": "Publisher dependence is unknown."}], explicit["unresolved"])
        for result in (unassigned, explicit):
            self.assertEqual([], result["groups"])
            self.assertEqual([pin(value)], result["roots"])
            self.assertEqual("partial", result["provenance_coverage"]["status"])
            self.assertTrue(result["provenance_coverage"]["reason"])
        self.assertIn(pin(unknown), explicit["dependencies"])

    def test_repeated_diagnostics_and_different_runs_do_not_generate_group_identity(self):
        first, second = observation("first-run"), observation("second-run")
        self.assertEqual(first["body"]["content"], second["body"]["content"])
        self.assertNotEqual(first["provenance"]["run_id"], second["provenance"]["run_id"])
        unresolved = self.resolve(Port([first, second]), first, second)
        self.assertEqual([], unresolved["groups"])
        self.assertEqual(2, len(unresolved["roots"]))
        self.assertEqual(2, len(unresolved["unresolved"]))
        declared = self.resolve(Port([first, second], [assigned(first), assigned(second)]), first, second)
        self.assertEqual([GROUP], declared["groups"])
        self.assertEqual(2, len(declared["roots"]))

    def test_summary_preserves_two_groups_without_merging_or_adding_one(self):
        left, right = observation("left"), observation("right")
        summary = observation("summary", origin="derived", parents=[pin(left), pin(right)])
        other_group = {**GROUP, "value": "source:two"}
        port = Port([left, right, summary], [assigned(left), assigned(right, declaration(other_group))])
        result = self.resolve(port, summary)
        self.assertCountEqual([GROUP, other_group], result["groups"])
        self.assertCountEqual([pin(left), pin(right)], result["roots"])
        self.assertEqual(5, len(result["dependencies"]))
        self.assertCountEqual([root_watch_key(SCOPE, pin(value)) for value in (left, right, summary)], result["watch_keys"])
        self.assertEqual("complete", result["provenance_coverage"]["status"])

    def test_diamond_inheritance_reads_shared_ancestor_once_and_watches_every_node(self):
        root = observation("root")
        copied = observation("copy", parents=[pin(root)])
        derived = observation("derived", origin="derived", parents=[pin(root)])
        joined = observation("join", origin="derived", parents=[pin(copied), pin(derived)])
        port = Port([root, copied, derived, joined], [assigned(root)])
        result = self.resolve(port, joined, copied)
        self.assertEqual([GROUP], result["groups"])
        self.assertCountEqual([pin(value) for value in (root, copied, derived, joined)], port.reads)
        self.assertEqual(4, len(port.lookups))
        self.assertEqual(4, len(result["watch_keys"]))
        self.assertEqual(5, len(result["dependencies"]))

    def test_forged_assignment_on_parented_or_evaluator_observation_is_not_ignored(self):
        root = observation("root")
        for value in (observation("copy", parents=[pin(root)]),
                      observation("summary", origin="derived", parents=[pin(root)]),
                      observation("evaluator", origin="evaluator")):
            with self.subTest(origin=value["provenance"]["origin"]):
                self.assert_error("E_EVIDENCE_INVALID", self.resolve,
                                  Port([root, value], [assigned(root), assigned(value)]), value)

    def test_missing_ancestor_is_explicit_and_watched_then_resolves_on_arrival(self):
        absent = observation("later")
        summary = observation("summary", origin="derived", parents=[pin(absent)])
        port = Port([summary])
        partial = self.resolve(port, summary)
        self.assertEqual([{"observation": pin(summary), "reason": "missing_parent", "parent": pin(absent)}], partial["unresolved"])
        self.assertEqual([pin(summary)], partial["dependencies"])
        self.assertIn(root_watch_key(SCOPE, pin(absent)), partial["watch_keys"])
        self.assertEqual("partial", partial["provenance_coverage"]["status"])
        port.observations[identity(absent)] = absent
        assignment = assigned(absent)
        port.assignments[identity(assignment)] = assignment
        complete = self.resolve(port, summary)
        self.assertEqual([GROUP], complete["groups"])
        self.assertEqual([], complete["unresolved"])
        self.assertEqual("complete", complete["provenance_coverage"]["status"])

    def test_missing_requested_observation_fails_even_when_also_an_ancestor(self):
        absent = observation("absent")
        summary = observation("summary", origin="derived", parents=[pin(absent)])
        for selected in ([pin(absent)], [pin(summary), pin(absent)]):
            self.assert_error("E_NOT_FOUND", resolve_groups, Port([summary]), SCOPE, selected)

    def test_non_observation_ancestry_is_preserved_as_unresolved_without_inference(self):
        judgment = {"scope_id": SCOPE, "namespace": "example", "record_type": "judgment",
                    "id": "upstream-evaluator", "digest": "1" * 64}
        summary = observation("summary", origin="derived", parents=[judgment])
        port = Port([summary])
        result = self.resolve(port, summary)
        self.assertEqual([{"observation": pin(summary), "reason": "non_observation_parent", "parent": judgment}], result["unresolved"])
        self.assertEqual([pin(summary)], port.reads)
        self.assertEqual([], result["groups"])
        self.assertEqual([], result["roots"])
        self.assertEqual("partial", result["provenance_coverage"]["status"])

    def test_parentless_evaluator_never_becomes_a_source_root(self):
        value = observation(origin="evaluator")
        result = self.resolve(Port([value]), value)
        self.assertEqual([{"observation": pin(value), "reason": "non_source_root"}], result["unresolved"])
        self.assertEqual([], result["roots"])
        self.assertEqual([], result["groups"])
        self.assertEqual([root_watch_key(SCOPE, pin(value))], result["watch_keys"])

    def test_foreign_scope_is_rejected_before_any_foreign_read(self):
        foreign = observation("foreign", scope="synthetic:foreign")
        local = observation("local", parents=[pin(foreign)])
        direct = Port([foreign])
        self.assert_error("E_SCOPE_FORBIDDEN", self.resolve, direct, foreign)
        self.assertEqual([], direct.reads)
        ancestor = Port([local, foreign])
        self.assert_error("E_SCOPE_FORBIDDEN", self.resolve, ancestor, local)
        self.assertEqual([pin(local)], ancestor.reads)

    def test_conflicting_pins_and_incorrect_fetched_snapshot_are_invalid(self):
        value = observation()
        wrong = {**pin(value), "digest": "f" * 64}
        port = Port([value])
        self.assert_error("E_EVIDENCE_INVALID", resolve_groups, port, SCOPE, [pin(value), wrong])
        self.assertEqual([], port.reads)
        self.assert_error("E_EVIDENCE_INVALID", resolve_groups, Port([value]), SCOPE, [wrong])
        # An immutable self-reference cannot match its own digest. The identity
        # conflict must still fail explicitly instead of looping forever.
        cyclic = observation("cycle")
        cyclic["provenance"]["parents"] = [pin(cyclic)]
        self.assert_error("E_EVIDENCE_INVALID", self.resolve, Port([cyclic]), cyclic)

    def test_budget_bounds_closure_including_missing_and_unsupported_parents(self):
        chain = [observation("root")]
        for number in range(1, 12):
            chain.append(observation(f"node:{number}", origin="derived", parents=[pin(chain[-1])]))
        result = self.resolve(Port(chain, [assigned(chain[0])]), chain[-1], max_nodes=12)
        self.assertEqual([GROUP], result["groups"])
        self.assert_error("E_BUDGET_EXHAUSTED", self.resolve, Port(chain), chain[-1], max_nodes=11)
        missing = observation("missing")
        child = observation("child", parents=[pin(missing)])
        self.assert_error("E_BUDGET_EXHAUSTED", self.resolve, Port([child]), child, max_nodes=1)
        judgment = {"scope_id": SCOPE, "namespace": "example", "record_type": "judgment",
                    "id": "bounded-unsupported-parent", "digest": "1" * 64}
        unsupported = observation("unsupported", origin="derived", parents=[judgment])
        self.assert_error("E_BUDGET_EXHAUSTED", self.resolve, Port([unsupported]), unsupported, max_nodes=1)
        for budget in (0, -1, True, 1.0, "2"):
            self.assert_error("E_SCHEMA_INVALID", self.resolve, Port(), max_nodes=budget)

    def test_result_is_deterministic_deduplicated_and_detached(self):
        left, right = observation("left"), observation("right")
        left_assignment = assigned(left)
        right_assignment = assigned(right, {"status": "unknown", "reason": "Not yet reviewed."})
        port = Port([left, right], [left_assignment, right_assignment])
        original_inputs = deepcopy([left, right, left_assignment, right_assignment])
        result = self.resolve(port, left, right, left)
        expected = self.resolve(port, right, left)
        self.assertEqual(expected, result)
        for field in ("groups", "dependencies", "roots", "watch_keys", "unresolved"):
            self.assertEqual(sorted(result[field], key=canonical_bytes), result[field])
        result["groups"][0]["value"] = "changed"
        result["dependencies"][0]["id"] = "changed"
        result["unresolved"][0]["detail"] = "changed"
        self.assertEqual(original_inputs, [left, right, left_assignment, right_assignment])
        self.assertEqual(expected, self.resolve(port, left, right))

    def test_coverage_binds_selection_and_assignment_revision_even_when_groups_unchanged(self):
        root = observation("root")
        summary = observation("summary", origin="derived", parents=[pin(root)])
        first = assigned(root, {"status": "unknown", "reason": "Not reviewed."})
        port = Port([root, summary], [first])
        root_only = self.resolve(port, root)
        selected_summary = self.resolve(port, summary)
        summary_and_root = self.resolve(port, summary, root)
        self.assertEqual(selected_summary["dependencies"], summary_and_root["dependencies"])
        self.assertNotEqual(selected_summary["provenance_coverage"], summary_and_root["provenance_coverage"])
        corrected = assigned(root, {"status": "unknown", "reason": "Reviewed; lineage still unavailable."}, revision=2)
        port.assignments[identity(corrected)] = corrected
        updated = self.resolve(port, root)
        self.assertEqual(root_only["groups"], updated["groups"])
        self.assertNotEqual(root_only["provenance_coverage"], updated["provenance_coverage"])
        self.assertIn(pin(corrected), updated["dependencies"])

    def test_empty_packet_has_explicit_vacuous_provenance_coverage(self):
        result = self.resolve(Port())
        for field in ("groups", "dependencies", "roots", "watch_keys", "unresolved"):
            self.assertEqual([], result[field])
        self.assertEqual("complete", result["provenance_coverage"]["status"])
        self.assertEqual("provenance-resolution", result["provenance_coverage"]["snapshot"]["id"])
        for invalid in (None, (), [entity_ref(observation())]):
            self.assert_error("E_SCHEMA_INVALID", resolve_groups, Port(), SCOPE, invalid)


if __name__ == "__main__":
    unittest.main()
