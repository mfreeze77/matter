"""Synthetic exact-snapshot packet behavior over actual Matter storage APIs."""

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import unittest

from matter.canonical import canonical_bytes, canonical_digest
from matter.citations import Utf8LineLocatorAdapter, line_selector
from matter.contracts import ContractError
from matter.payloads import PayloadRead
from matter.semantic.packets import PacketProfile, PreparedPacket, prepare_packet, preparation_reference
from matter.semantic.questions import QuestionSpecification
from matter.semantic.rendering import render_question
from matter.storage import StorageError, pin

from occurrence_helpers import OccurrenceTestCase, SCOPE, declared, group_key
from observation_helpers import observation_command


AS_OF = {"state": "known", "value": "2050-01-01T00:00:00Z", "precision": "second"}
EARLY = {"state": "known", "value": "2026-10-09T00:00:00Z", "precision": "second"}
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/semantic/packet_cases.json"


def component(identity):
    return {"namespace": "synthetic", "id": identity, "version": "1.0", "digest": "a" * 64}


class PacketTests(OccurrenceTestCase):
    def setUp(self):
        super().setUp()
        self.adapter = Utf8LineLocatorAdapter(self.payloads)
        self.support = self.observe("support", payload=b"SYNTHETIC: diagnostic failure observed.\n")
        self.counter = self.observe("counterexample", payload=b"SYNTHETIC: later check contradicts the failure claim.\n")
        self.occurrence = self.group("execution", [self.support, self.counter],
                                     assignments=[declared(self.support, group_key("support")), declared(self.counter, group_key("counter"))])
        self.profile_value = {"namespace": "synthetic", "id": "claim-evidence-packet", "version": "1.0",
                              "required_roles": ["synthetic:basis", "synthetic:counterexample"],
                              "allowed_origins": ["source", "derived", "evaluator"],
                              "locator_adapters": [self.adapter.reference], "max_sources": 16,
                              "max_source_bytes": 65536, "max_packet_bytes": 262144}

    def evidence(self, record, roles):
        locator = deepcopy(record["body"]["content"]["locator"])
        return {"reference": pin(record), "roles": roles, "locator": locator, "quotation": None,
                "validation": self.adapter.validate(record, locator, checked_at=AS_OF)}

    def arguments(self):
        return {"scope_id": SCOPE,
                "binding": {"kind": "candidate_relation", "left": pin(self.support), "right": pin(self.counter), "relation": "synthetic:same_matter"},
                "as_of": AS_OF, "evidence": [self.evidence(self.support, ["synthetic:basis"]),
                                              self.evidence(self.counter, ["synthetic:counterexample"])],
                "occurrences": [pin(self.occurrence)],
                "coverage": {"status": "complete", "snapshot": component("explicit-cohort")}}

    def prepare(self, *, profile=None, payloads=None, **changes):
        arguments = self.arguments()
        arguments.update(changes)
        with self.storage.snapshot() as view:
            return prepare_packet(view, PacketProfile(profile or self.profile_value), payloads=payloads or self.payloads, **arguments)

    def case(self, identity):
        return next(item for item in json.loads(FIXTURE.read_text())["cases"] if item["id"] == identity)

    def assert_code(self, code, function, *args, **kwargs):
        with self.assertRaises(ContractError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)

    def test_complete_packet_binds_profile_sources_locators_and_calculation_inputs(self):
        packet = self.prepare()
        self.assertEqual(packet.state["coverage"]["status"], "complete")
        self.assertEqual(packet.state["mechanical"]["counts"], {"observations": 2, "occurrences": 1, "provenance_groups": 2})
        self.assertEqual(packet.state["profile"], PacketProfile(self.profile_value).reference)
        self.assertEqual(packet.state["preparation"], preparation_reference())
        self.assertEqual(packet.digest, canonical_digest(packet.state, "matter.semantic.packet.v1"))
        self.assertEqual(packet.canonical, canonical_bytes(packet.state))
        calculation = packet.state["mechanical"]
        self.assertEqual(len(calculation["inputs"]), 2)
        self.assertFalse(calculation["identifier_matches"][0]["same_source_event"])
        self.assertEqual(calculation["date_comparisons"][0]["availability_order"], 0)
        self.assertEqual(calculation["date_comparisons"][0]["event_order"], 0)
        self.assertEqual(packet.source_manifest["excluded"], [])
        for item in packet.state["evidence"]:
            self.assertIn("validation", item)
            self.assertIn("locator", item)

    def test_input_candidate_order_cannot_change_packet_or_manifest(self):
        first = self.prepare()
        reversed_evidence = list(reversed(self.arguments()["evidence"]))
        second = self.prepare(evidence=reversed_evidence)
        self.assertEqual(first.value, second.value)
        self.assertEqual(first.audit_digest, second.audit_digest)

    def test_packet_renders_through_actual_question_interface_without_audit_leakage(self):
        spec = QuestionSpecification({"schema_version": "1.0", "namespace": "synthetic", "id": "packet-relation",
            "family": "synthetic.relation", "revision": "1.0", "primitive": "proposition_probability",
            "instructions": "Do {{sources}} support relation {{relation}}? Preserve uncertainty and counterevidence.",
            "criteria": {"true": "Selected evidence supports the declared relation.", "false": "Selected evidence does not support the declared relation."},
            "required_fields": [{"name": "sources", "path": ["evidence"], "description": "Exact selected sources only."},
                                {"name": "relation", "path": ["binding", "relation"], "description": "The candidate relation under evaluation."}],
            "renderer": {"id": "canonical-json-bindings", "version": "1.0"}})
        profile = deepcopy(self.profile_value)
        profile["max_source_bytes"] = 40
        packet = self.prepare(profile=profile)
        rendered = render_question(spec, packet.state, "packet-comparison", source_manifest=packet.source_manifest)
        self.assertEqual(rendered.question.value["packet_digest"], packet.digest)
        self.assertEqual(rendered.manifest["included_sources"], packet.source_manifest["included"])
        self.assertEqual(rendered.manifest["excluded_sources"], packet.source_manifest["excluded"])
        self.assertEqual(rendered.manifest["truncation"], packet.source_manifest["truncation"])
        instructions = rendered.question.value["instructions"]
        self.assertIn("diagnostic failure observed", instructions)
        self.assertNotIn("later check contradicts", instructions)
        self.assertNotIn("source_byte_limit", instructions)

    def test_unassigned_root_stays_unknown_without_invented_group(self):
        unassigned = self.observe("unassigned", payload=b"SYNTHETIC source without declared root group.\n")
        profile = deepcopy(self.profile_value)
        profile["required_roles"] = ["synthetic:basis"]
        packet = self.prepare(profile=profile, evidence=[self.evidence(unassigned, ["synthetic:basis"])], occurrences=[])
        self.assertEqual(packet.state["coverage"]["provenance_status"], "incomplete")
        self.assertEqual(packet.state["mechanical"]["counts"]["provenance_groups"], 0)
        self.assertEqual(packet.value["provenance_omissions"][0]["reason"], "unassigned_root")

    def test_same_frozen_snapshot_rebuilds_identically_in_separate_processes(self):
        arguments = self.arguments()
        path = self.directory / "packet-input.json"
        path.write_bytes(canonical_bytes({"profile": self.profile_value, "arguments": arguments}))
        script = '''import sys
from pathlib import Path
from matter.canonical import loads,canonical_bytes
from matter.payloads import FilePayloadStore
from matter.storage import SQLiteStore
from matter.semantic.packets import PacketProfile,prepare_packet
request=loads(Path(sys.argv[1]).read_bytes())
with SQLiteStore(sys.argv[2],scope_id=request['arguments']['scope_id']) as store:
 with store.snapshot() as view:
  result=prepare_packet(view,PacketProfile(request['profile']),payloads=FilePayloadStore(sys.argv[3],scope_id=request['arguments']['scope_id']),**request['arguments'])
  sys.stdout.buffer.write(canonical_bytes({'packet':result.value,'digest':result.digest,'audit_digest':result.audit_digest}))
'''
        args = [sys.executable, "-c", script, str(path), str(self.database), str(self.directory / "payloads")]
        one = subprocess.run(args, check=True, capture_output=True, timeout=30)
        two = subprocess.run(args, check=True, capture_output=True, timeout=30)
        self.assertEqual(one.stdout, two.stdout)
        result = json.loads(one.stdout)
        self.assertEqual(result["digest"], self.prepare().digest)
        self.assertEqual(result["packet"], self.prepare().value)

    def test_required_counterexample_missing_is_visible_in_coverage(self):
        packet = self.prepare(evidence=[self.evidence(self.support, ["synthetic:basis"])])
        expected = self.case("mandatory-counterexample")["expected"]
        self.assertEqual(packet.state["coverage"]["status"], expected["coverage"])
        self.assertEqual(packet.state["coverage"]["missing_roles"], [expected["missing_role"]])

    def test_required_source_currently_unavailable_is_not_silent(self):
        real = self.payloads
        counter_digest = self.counter["body"]["content"]["digest"]
        class ReadGate:
            scope_id = real.scope_id
            def read(self, content):
                if content["digest"] == counter_digest:
                    return PayloadRead("unavailable", counter_digest, None, "Synthetic missing bytes.")
                return real.read(content)
        packet = self.prepare(payloads=ReadGate())
        self.assertEqual(packet.state["coverage"]["status"], "incomplete")
        self.assertIn("payload_unavailable", [item["reason"] for item in packet.source_manifest["excluded"]])
        self.assertNotIn(self.counter["id"], [item["reference"]["id"] for item in packet.state["evidence"]])

    def test_oversized_required_counterexample_remains_in_omissions(self):
        profile = deepcopy(self.profile_value)
        profile["max_source_bytes"] = len(b"SYNTHETIC: diagnostic failure observed.\n")
        packet = self.prepare(profile=profile)
        self.assertEqual(packet.state["coverage"]["status"], "incomplete")
        self.assertEqual(packet.source_manifest["excluded"][0]["reason"], self.case("oversized-counterexample")["expected"]["reason"])
        self.assertTrue(packet.source_manifest["excluded"][0]["mandatory"])
        self.assertEqual(packet.source_manifest["truncation"]["status"], "truncated")

    def test_exact_source_byte_boundary_includes_without_text_chopping(self):
        profile = deepcopy(self.profile_value)
        profile["max_source_bytes"] = len(b"SYNTHETIC: later check contradicts the failure claim.\n")
        packet = self.prepare(profile=profile)
        self.assertEqual(packet.state["coverage"]["status"], "complete")
        self.assertEqual(next(item["text"] for item in packet.state["evidence"] if item["reference"] == pin(self.counter)),
                         "SYNTHETIC: later check contradicts the failure claim.\n")

    def test_packet_total_bound_omits_whole_source_including_mechanical_overhead(self):
        full = self.prepare()
        profile = deepcopy(self.profile_value)
        profile["max_packet_bytes"] = len(full.canonical) - 50
        profile["max_source_bytes"] = profile["max_packet_bytes"]
        packet = self.prepare(profile=profile)
        self.assertLessEqual(len(packet.canonical), profile["max_packet_bytes"])
        self.assertEqual(packet.state["coverage"]["status"], "incomplete")
        self.assertIn("packet_byte_limit", [item["reason"] for item in packet.source_manifest["excluded"]])

    def test_too_small_metadata_budget_fails_explicitly(self):
        profile = deepcopy(self.profile_value)
        profile.update(max_packet_bytes=1, max_source_bytes=1)
        self.assert_code("E_BUDGET_EXHAUSTED", self.prepare, profile=profile)

    def test_required_sources_are_selected_before_optional_sources(self):
        optional = self.observe("a-optional", payload=b"SYNTHETIC optional supporting description.\n")
        evidence = [self.evidence(optional, ["synthetic:context"]), *self.arguments()["evidence"]]
        profile = deepcopy(self.profile_value)
        profile["max_sources"] = 2
        packet = self.prepare(profile=profile, evidence=evidence)
        self.assertEqual({item["reference"]["id"] for item in packet.state["evidence"]}, {self.support["id"], self.counter["id"]})
        self.assertEqual(packet.source_manifest["excluded"][0]["reference"], pin(optional))
        self.assertFalse(packet.source_manifest["excluded"][0]["mandatory"])
        self.assertEqual(packet.state["coverage"]["status"], "complete")

    def test_duplicate_evidence_and_foreign_scope_refused_before_content_read(self):
        evidence = self.arguments()["evidence"]
        self.assert_code("E_SCHEMA_INVALID", self.prepare, evidence=[evidence[0], evidence[0]])
        foreign = deepcopy(evidence[0])
        foreign["reference"]["scope_id"] = "foreign:similar-project"
        self.assert_code(self.case("foreign-project-scope")["expected"]["error"], self.prepare, evidence=[foreign])
        binding = deepcopy(self.arguments()["binding"])
        binding["right"]["scope_id"] = "foreign:similar-project"
        self.assert_code("E_SCOPE_FORBIDDEN", self.prepare, binding=binding)

    def test_late_cancellation_is_excluded_even_with_earlier_event_time(self):
        command = observation_command("late-cancellation", "late-cancellation", scope_id=SCOPE,
                                      payload=b"SYNTHETIC cancellation published after the cut.\n")
        command["body"]["observation"]["body"]["available_at"] = {**AS_OF, "value": "2050-01-01T00:00:00.000000001Z", "precision": "nanosecond"}
        result = self.observations.ingest(self.observations.prepare(command), payload=b"SYNTHETIC cancellation published after the cut.\n")
        late = self.storage.get(result["body"]["observation"])
        evidence = [*self.arguments()["evidence"], self.evidence(late, ["synthetic:counterexample"])]
        packet = self.prepare(evidence=evidence)
        self.assertEqual(packet.state["coverage"]["status"], "incomplete")
        self.assertIn({"reference": pin(late), "roles": ["synthetic:counterexample"], "mandatory": True,
                       "reason": self.case("late-cancellation")["expected"]["reason"]}, packet.source_manifest["excluded"])
        self.assertNotIn(b"late-cancellation", packet.canonical)
        self.assertNotIn(b"cancellation published after", packet.canonical)

    def test_late_locator_dependency_cannot_enter_an_earlier_source_packet(self):
        command = observation_command("late-locator-proof", "late-locator-proof", scope_id=SCOPE,
                                      payload=b"SYNTHETIC proof produced after the cut.\n")
        command["body"]["observation"]["body"]["available_at"] = {**AS_OF, "value": "2050-01-01T00:00:01Z"}
        result = self.observations.ingest(self.observations.prepare(command), payload=b"SYNTHETIC proof produced after the cut.\n")
        late = self.storage.get(result["body"]["observation"])
        source = self.evidence(self.counter, ["synthetic:counterexample"])
        source["validation"]["value"]["dependencies"] = sorted([pin(self.counter), pin(late)], key=canonical_bytes)
        packet = self.prepare(evidence=[self.evidence(self.support, ["synthetic:basis"]), source])
        self.assertEqual(packet.source_manifest["excluded"][0]["reason"], "locator_dependency_not_available_at_cut")
        self.assertEqual(packet.state["coverage"]["status"], "incomplete")
        self.assertNotIn(b"late-locator-proof", packet.canonical)

    def test_two_summaries_and_log_copy_do_not_inflate_group_count(self):
        copied = self.observe("copy", parents=[self.support], payload=b"SYNTHETIC copy of original diagnostic.\n")
        summary = self.observe("summary", parents=[copied], payload=b"SYNTHETIC summary of the copied diagnostic.\n", origin="evaluator")
        second_summary = self.observe("second-summary", parents=[self.support], payload=b"SYNTHETIC another summary of the diagnostic.\n")
        occurrence = self.group("one-root-many-descriptions", [self.support, copied, summary, second_summary])
        profile = deepcopy(self.profile_value)
        profile["required_roles"] = ["synthetic:basis"]
        inputs = [self.support, copied, summary, second_summary]
        evidence = [self.evidence(item, ["synthetic:basis"]) for item in inputs]
        packet = self.prepare(profile=profile, evidence=evidence, occurrences=[pin(occurrence)])
        self.assertEqual(packet.state["mechanical"]["counts"], self.case("copy-summary-lineage")["expected"])
        self.assertEqual(packet.state["coverage"]["status"], "complete")

    def test_current_grouping_is_not_backdated_to_historical_cut(self):
        packet = self.prepare(as_of=EARLY)
        self.assertEqual(packet.state["coverage"]["status"], "incomplete")
        self.assertEqual(packet.state["coverage"]["provenance_status"], "incomplete")
        self.assertEqual(packet.state["mechanical"]["counts"]["provenance_groups"], 0)
        self.assertEqual(packet.state["mechanical"]["counts"]["occurrences"], 0)
        self.assertEqual(packet.value["occurrence_omissions"][0]["reason"], "grouping_not_available_at_cut")
        self.assertEqual(packet.value["provenance_omissions"], [{"reason": "provenance_not_available_at_cut"}])

    def test_partial_source_coverage_never_becomes_complete(self):
        packet = self.prepare(coverage={"status": "partial", "snapshot": component("partial"), "reason": "Synthetic collection incomplete."})
        self.assertEqual(packet.state["coverage"]["status"], "incomplete")
        self.assertEqual(packet.state["coverage"]["source_coverage"]["status"], "partial")

    def test_selected_span_retains_validated_exact_quotation(self):
        item = self.evidence(self.counter, ["synthetic:counterexample"])
        item["locator"] = {"kind": "selected_span", "uri": self.counter["body"]["content"]["locator"]["uri"], "selector": line_selector(1, 1)}
        item["quotation"] = "contradicts the failure claim"
        item["validation"] = self.adapter.validate(self.counter, item["locator"], quotation=item["quotation"], checked_at=AS_OF)
        packet = self.prepare(evidence=[self.evidence(self.support, ["synthetic:basis"]), item])
        excerpt = next(entry for entry in packet.state["evidence"] if entry["reference"] == pin(self.counter))
        self.assertEqual(excerpt["text"], item["quotation"])
        wrong = deepcopy(item)
        wrong["quotation"] = "invented quotation"
        self.assert_code("E_EVIDENCE_INVALID", self.prepare, evidence=[wrong])

    def test_missing_and_invalid_locators_record_explicit_omissions(self):
        item = self.evidence(self.counter, ["synthetic:counterexample"])
        item["locator"] = {"kind": "unavailable", "reason": "Synthetic absent citation."}
        item["validation"] = self.adapter.validate(self.counter, item["locator"], checked_at=AS_OF)
        packet = self.prepare(evidence=[self.evidence(self.support, ["synthetic:basis"]), item])
        self.assertEqual(packet.state["coverage"]["status"], "incomplete")
        self.assertEqual(packet.source_manifest["excluded"][0]["reason"], "locator_unavailable")

    def test_profile_mutations_change_preparation_binding_and_cannot_mutate_capture(self):
        original = PacketProfile(self.profile_value)
        captured = original.reference
        self.profile_value["required_roles"].clear()
        self.assertEqual(original.reference, captured)
        revised = PacketProfile({**original.value, "version": "2.0"})
        self.assertNotEqual(original.reference, revised.reference)
        packet = self.prepare(profile=original.value)
        digest = packet.digest
        packet.state["evidence"].clear()
        packet.source_manifest["excluded"].append({"reason": "caller alteration"})
        self.assertEqual(packet.digest, digest)
        with self.assertRaises(AttributeError):
            packet._encoded = b"{}"
        self.assert_code("E_POLICY_INVALID", PreparedPacket, {})

    def test_packet_profile_refuses_impossible_bounds(self):
        for change in ({"max_sources": True}, {"max_packet_bytes": 1}, {"locator_adapters": []}, {"allowed_origins": ["fictional"]}):
            self.assert_code("E_POLICY_INVALID", PacketProfile, {**self.profile_value, **change})

if __name__ == "__main__":
    unittest.main()
