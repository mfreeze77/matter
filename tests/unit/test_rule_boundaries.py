from copy import deepcopy
import unittest

from matter.canonical import canonical_bytes
from matter.contracts import ContractError
from matter.evaluators import BindingRegistry
from matter.evaluators.packets import check_input_current, requires_currentness_guard
from matter.evaluators.packets import prepare_input
from matter.evaluators.runner import admit_result
from matter.rules import SchemaDefinition, SchemaRegistry
from matter.storage import entity_ref, pin, StorageError
from matter_helpers import metadata_command
from rule_helpers import RuleTestCase, NOW, EARLY, LATE, component
from coverage_helpers import CoverageTestCase, T2, T3, T4


class RuleBoundaryTests(RuleTestCase):
    def gate(self, prepared, *, as_of):
        with self.storage.snapshot() as view:
            return check_input_current(view, prepared, as_of=as_of)

    def predecessor(self, result):
        # A read-view fixture represents a host-persisted prerequisite; this
        # test helper is not an assessment or evaluator persistence operation.
        record = result.judgment
        record["creation_receipt"] = deepcopy(self.subject["creation_receipt"])
        return record

    def overlay(self, snapshot, records):
        class View:
            def get(inner, reference):
                for record in records:
                    if entity_ref(reference) == entity_ref(record):
                        return deepcopy(record)
                return snapshot.get(reference)
        return View()

    def dependent(self, rule, binding):
        def change(definition):
            definition["dependencies"] = [{"rule": rule.reference, "accepted_labels": ["example:positive"],
                "accepted_statuses": ["applicable"], "require_qualified": True}]
        return self.rule(binding, identity="dependent", change=change)

    def test_consumed_result_revalidates_citations_and_proposal_permissions(self):
        result, rule, binding, packet = self.evaluate()
        for code, mutate in (
            ("E_EVIDENCE_INVALID", lambda b: b["used_evidence"][0]["reference"].update(id="invented")),
            ("E_EVIDENCE_INVALID", lambda b: b["used_evidence"][0]["locator"].update(uri="urn:invented")),
            ("E_AUTHORITY_REQUIRED", lambda b: b["proposed_consequences"].append(
                {"schema": self.proposal_schema.reference, "value": {"reason": "Unpermitted transition."}})),
        ):
            judgment = result.judgment
            mutate(judgment["body"])
            self.assert_code(code, admit_result, judgment, rule, binding=binding, schemas=self.schemas,
                expected_input=packet, as_of=NOW, accepted_labels=["example:positive"])

    def test_other_question_and_manifest_cannot_substitute_for_exact_input(self):
        result, rule, binding, packet = self.evaluate()
        other = self.packet(rule, proposition={"schema": self.input_schema.reference, "value": {"enabled": False}})
        for expected, mutate in ((other, lambda b: None), (packet, lambda b: b["dependency_manifest"]["positive"].clear())):
            judgment = result.judgment
            mutate(judgment["body"])
            admission = admit_result(judgment, rule, binding=binding, schemas=self.schemas,
                expected_input=expected, as_of=NOW, accepted_labels=["example:positive"])
            self.assertEqual(admission["reason"], "expected_input_mismatch")

    def test_consumption_and_attempt_cannot_import_future_knowledge(self):
        binding = self.binding()
        rule = self.rule(binding)
        packet = self.packet(rule)
        result = self.runner([rule], [binding], clock=lambda: LATE).evaluate(packet,
            judgment_id="later", attempt_id="later-attempt")
        admission = admit_result(result.judgment, rule, binding=binding, schemas=self.schemas,
            expected_input=packet, as_of=NOW, accepted_labels=["example:positive"])
        self.assertEqual(admission["reason"], "not_available_at_admission")
        result = self.runner([rule], [binding], clock=lambda: EARLY).evaluate(packet,
            judgment_id="earlier", attempt_id="earlier-attempt")
        self.assertEqual(result.judgment["body"]["failure"]["code"], "E_EVIDENCE_INVALID")
        self.assertFalse(result.receipt["body"]["details"]["value"]["called"])

    def test_explicit_upstream_input_mapping_allows_different_proposition(self):
        first_binding = self.binding(identity="first")
        first_rule = self.rule(first_binding, identity="first")
        original = self.packet(first_rule, proposition={"schema": self.input_schema.reference, "value": {"enabled": False}})
        result, _, _, _ = self.evaluate(first_binding, first_rule, original)
        record = self.predecessor(result)
        binding = self.binding(identity="dependent")
        rule = self.dependent(first_rule, binding)
        with self.storage.snapshot() as view:
            packet = self.packet(rule, view=self.overlay(view, [record]), upstream=[
                {"reference": pin(record), "expected_input": original.value, "available_at": NOW}])
        self.assertTrue(requires_currentness_guard(packet))
        self.assertFalse(packet.value["packet"]["upstream"][0]["expected_input"]["packet"]["proposition"]["value"]["enabled"])
        def gate(value, *, as_of):
            with self.storage.snapshot() as view:
                return check_input_current(self.overlay(view, [record]), value, as_of=as_of)
        result = self.runner([first_rule, rule], [first_binding, binding]).evaluate(packet,
            judgment_id="dependent", attempt_id="dependent-attempt", check_current=gate)
        self.assertEqual(result.judgment["body"]["evaluation_status"], "applicable")
        wrong = self.packet(first_rule)
        with self.storage.snapshot() as view:
            self.assert_code("E_EVIDENCE_INVALID", self.packet, rule, view=self.overlay(view, [record]), upstream=[
                {"reference": pin(record), "expected_input": wrong.value, "available_at": NOW}])

    def test_future_upstream_knowledge_is_omitted_despite_backdated_availability(self):
        result, original_rule, original_binding, original = self.evaluate()
        record = self.predecessor(result)
        record["body"]["execution_interval"] = {"start": LATE, "end": LATE, "bounds": "closed"}
        record["provenance"]["recorded_at"] = LATE
        binding = self.binding(identity="dependent")
        rule = self.dependent(original_rule, binding)
        with self.storage.snapshot() as view:
            packet = self.packet(rule, view=self.overlay(view, [record]), upstream=[
                {"reference": pin(record), "expected_input": original.value, "available_at": EARLY}])
        self.assertEqual(packet.value["packet"]["upstream"], [])
        self.assertTrue(packet.value["packet"]["omitted"][0]["mandatory"])
        result = self.runner([rule, original_rule], [binding, original_binding]).evaluate(packet,
            judgment_id="future", attempt_id="future-attempt")
        self.assertEqual(result.judgment["body"]["evaluation_status"], "insufficient_evidence")

    def test_future_judgment_as_ordinary_evidence_is_also_omitted(self):
        result, original_rule, original_binding, original = self.evaluate()
        record = self.predecessor(result)
        record["body"]["execution_interval"] = {"start": LATE, "end": LATE, "bounds": "closed"}
        record["provenance"]["recorded_at"] = LATE
        binding = self.binding(identity="ordinary")
        def change(definition):
            definition["evidence_requirements"].update(allowed_kinds=["judgment"], allowed_origins=["evaluator"])
        rule = self.rule(binding, change=change)
        evidence = self.evidence()
        evidence.update(reference=pin(record), available_at=EARLY)
        with self.storage.snapshot() as view:
            packet = self.packet(rule, view=self.overlay(view, [record]), evidence=[evidence])
        self.assertEqual(packet.value["packet"]["evidence"], [])
        self.assertEqual(packet.value["packet"]["omitted"][0]["reason"], "not_yet_available")

    def test_subject_currentness_is_required_and_rechecked_after_callback(self):
        def mutate(request):
            command = metadata_command("subject-changed", self.subject, {"title": "Changed subject context"})
            changed = self.matters.update_metadata(self.matters.prepare(command))
            self.assertEqual(changed["status"], "success")
            return self.response()
        binding = self.binding(mutate)
        rule = self.rule(binding)
        packet = self.packet(rule, subject=pin(self.subject))
        runner = self.runner([rule], [binding])
        self.assert_code("E_POLICY_INVALID", runner.evaluate, packet, judgment_id="missing", attempt_id="gate")
        result = runner.evaluate(packet, judgment_id="subject", attempt_id="subject-attempt", check_current=self.gate)
        self.assertEqual(result.judgment["body"]["failure"]["code"], "E_DEPENDENCY_STALE")
        self.assertNotIn("semantic_output", result.judgment["body"])
        self.assertEqual(result.receipt["body"]["details"]["value"]["events"][-1]["stage"], "post_gate")

    def test_temporal_expiry_uses_attempt_time_not_knowledge_cut(self):
        binding = self.binding()
        rule = self.rule(binding, change=lambda d: d["temporal_dependencies"].append(
            {"condition": component("deadline"), "next_check_at": LATE, "expires_at": LATE}))
        packet = self.packet(rule)
        result = self.runner([rule], [binding], clock=lambda: LATE).evaluate(packet,
            judgment_id="expired", attempt_id="expired-attempt", check_current=self.gate)
        self.assertEqual(result.judgment["body"]["failure"]["code"], "E_DEPENDENCY_STALE")
        self.assertEqual(self.calls, [])

    def test_fixed_control_is_rechecked_after_timeout_without_recapture(self):
        checks = []
        token = {"scope_id": self.subject["scope_id"], "control_epoch": 3, "opaque_host_targets": ["subject-a"]}
        def timeout(request):
            self.assertNotIn("opaque_host_targets", str(request))
            raise TimeoutError("do not expose")
        binding = self.binding(timeout)
        rule = self.rule(binding)
        packet = self.packet(rule, control_token=token)
        runner = self.runner([rule], [binding])
        self.assert_code("E_POLICY_INVALID", runner.evaluate, packet, judgment_id="missing", attempt_id="control")
        def control(value):
            checks.append(deepcopy(value))
            value["control_epoch"] = 100
            if len(checks) == 2:
                raise StorageError("E_CANCELLED")
        result = runner.evaluate(packet, judgment_id="control", attempt_id="control-attempt", check_control=control)
        self.assertEqual(checks, [token, token])
        self.assertEqual(result.judgment["body"]["execution_status"], "cancelled")
        events = result.receipt["body"]["details"]["value"]["events"]
        self.assertIn({"stage": "binding", "status": "timed_out"}, events)
        self.assertEqual(events[-1], {"stage": "post_gate", "status": "cancelled", "code": "E_CANCELLED"})

    def test_upstream_control_context_is_required_and_not_epoch_equivalence(self):
        token = {"scope_id": self.subject["scope_id"], "control_epoch": 3, "targets": ["old"]}
        binding = self.binding(identity="first")
        rule = self.rule(binding, identity="first")
        original = self.packet(rule, control_token=token)
        result, _, _, _ = self.evaluate(binding, rule, original, check_control=lambda token: None)
        record = self.predecessor(result)
        next_binding = self.binding(identity="next")
        next_rule = self.dependent(rule, next_binding)
        with self.storage.snapshot() as view:
            packet = self.packet(next_rule, view=self.overlay(view, [record]), upstream=[
                {"reference": pin(record), "expected_input": original.value, "available_at": NOW}])
            overlay = self.overlay(view, [record])
            self.assert_code("E_POLICY_INVALID", check_input_current, overlay, packet, as_of=NOW)
            contexts = []
            check_input_current(overlay, packet, as_of=NOW, check_control_context=lambda **context: contexts.append(context))
        self.assertEqual(contexts[0]["input_digest"], original.digest)
        self.assertEqual(contexts[0]["token_digest"], original.value["packet"]["control_token_digest"])
        self.assertEqual(contexts[0]["control_epoch"], 3)

    def test_returned_raw_artifact_survives_validation_failure_and_elapsed_timeout(self):
        artifact = deepcopy(self.source["body"]["content"])
        initial = self.recorded()
        rule = self.rule(initial)
        packet = self.packet(rule)
        binding = self.recorded([{"input_digest": packet.digest, "response": self.response(label="example:invented"),
                                  "raw_result": artifact}])
        result = self.runner([rule], [binding]).evaluate(packet, judgment_id="invalid", attempt_id="invalid-attempt")
        self.assertEqual(result.judgment["body"]["raw_result"], artifact)
        self.assertEqual(result.judgment["body"]["execution_status"], "failed")
        binding = self.recorded([{"input_digest": packet.digest, "response": self.response(), "raw_result": artifact}])
        ticks = iter([0, 2])
        result = self.runner([rule], [binding], monotonic=lambda: next(ticks)).evaluate(packet,
            judgment_id="slow", attempt_id="slow-attempt")
        self.assertEqual(result.judgment["body"]["raw_result"], artifact)
        self.assertEqual(result.judgment["body"]["execution_status"], "timed_out")

    def test_input_order_budget_and_detached_callback_preserve_identity(self):
        second = self.observe("source-b")
        binding = self.binding()
        rule = self.rule(binding)
        first = self.packet(rule, evidence=[self.evidence(), self.evidence(second)])
        reverse = self.packet(rule, evidence=[self.evidence(second), self.evidence()])
        self.assertNotEqual(first.digest, reverse.digest)
        too_small = self.rule(binding, change=lambda d: d["resource_limits"].update(max_input_bytes=1024))
        self.assert_code("E_BUDGET_EXHAUSTED", self.packet, too_small)
        def mutate(request):
            request["input"]["packet"]["evidence"].clear()
            return self.response()
        binding = self.binding(mutate)
        rule = self.rule(binding)
        packet = self.packet(rule)
        before = packet.canonical_bytes
        successful, _, _, _ = self.evaluate(binding, rule, packet)
        def failure(request):
            raise RuntimeError("private")
        failed, _, _, _ = self.evaluate(self.binding(failure, identity="failure"))
        self.assertEqual(packet.canonical_bytes, before)
        self.assertEqual(successful.judgment["body"]["execution_status"], "completed")
        self.assertEqual(failed.judgment["body"]["execution_status"], "failed")

    def test_missing_exact_recording_and_output_budget_have_no_conclusion(self):
        second = self.observe("source-second")
        initial = self.recorded()
        rule = self.rule(initial)
        original = self.packet(rule, evidence=[self.evidence(), self.evidence(second)])
        reversed_packet = self.packet(rule, evidence=[self.evidence(second), self.evidence()])
        binding = self.recorded([{"input_digest": original.digest, "response": self.response()}])
        result = self.runner([rule], [binding]).evaluate(reversed_packet,
            judgment_id="order-miss", attempt_id="order-miss-attempt")
        self.assertEqual(result.judgment["body"]["failure"]["code"], "E_EVIDENCE_UNAVAILABLE")
        binding = self.binding()
        rule = self.rule(binding, change=lambda d: d["resource_limits"].update(max_output_bytes=64))
        result, _, _, _ = self.evaluate(binding, rule)
        self.assertEqual(result.judgment["body"]["execution_status"], "budget_exhausted")
        self.assertNotIn("semantic_output", result.judgment["body"])

    def test_malformed_return_is_unavailable_not_a_claim_that_nothing_returned(self):
        original = self.binding()
        class MalformedBinding:
            reference = original.reference
            mode = "deterministic"
            def evaluate(self, request):
                return {"unexpected": "returned content"}
        binding = MalformedBinding()
        rule = self.rule(binding)
        result, _, _, _ = self.evaluate(binding, rule)
        self.assertEqual(result.judgment["body"]["execution_status"], "failed")
        self.assertEqual(result.judgment["body"]["raw_result"]["state"], "unavailable")
        self.assertEqual(result.judgment["body"]["raw_result"]["reason"], "not_persisted")


class DomainSchemaBoundaryTests(unittest.TestCase):
    def definition(self, schema):
        return SchemaDefinition("example", "closure", "1.0", {
            "$schema": "https://json-schema.org/draft/2020-12/schema", "$id": "urn:example:closure", **schema})

    def test_external_child_swap_and_dynamic_remapping_are_rejected(self):
        for schema in ({"$ref": "urn:example:child"}, {"$ref": "child.json"},
                       {"$dynamicRef": "#child"}, {"$defs": {"child": {"$id": "urn:other", "type": "string"}}}):
            with self.assertRaises(ContractError) as error:
                self.definition(schema)
            self.assertEqual(error.exception.code, "E_POLICY_INVALID")

    def test_local_definition_and_literal_reference_property_names_are_supported(self):
        definition = self.definition({"type": "object", "properties": {
            "$ref": {"$ref": "#/$defs/text"}, "$id": {"type": "string"}},
            "required": ["$ref", "$id"], "$defs": {"text": {"type": "string"}}})
        registry = SchemaRegistry([definition])
        registry.validate({"schema": definition.reference, "value": {"$ref": "source content", "$id": "source ID"}})
        with self.assertRaises(ContractError):
            registry.validate({"schema": definition.reference, "value": {"$ref": 1, "$id": "source ID"}})

    def test_local_pointer_into_annotation_cannot_rebind_external_child(self):
        outer = self.definition({"$ref": "#/examples/0", "examples": [{"$ref": "urn:example:child"}]})
        for version, child_type in (("1.0", "string"), ("2.0", "integer")):
            child = SchemaDefinition("example", "child", version, {
                "$schema": "https://json-schema.org/draft/2020-12/schema", "$id": "urn:example:child",
                "type": child_type})
            registry = SchemaRegistry([outer, child])
            with self.assertRaises(ContractError) as error:
                registry.validate({"schema": outer.reference, "value": 42})
            self.assertEqual(error.exception.code, "E_POLICY_INVALID")


class NegativeRuleBoundaryTests(CoverageTestCase):
    def test_historically_valid_absence_expires_before_actual_attempt(self):
        kit = RuleTestCase(methodName="runTest")
        kit.setUp()
        self.addCleanup(kit.doCleanups)
        coverage, _, _ = self.publish_coverage()
        registration, _, _ = self.register_watch(coverage, as_of=T2, next_check_at=T3, expires_at=T4)
        binding = kit.binding()
        rule = kit.rule(binding, change=lambda d: d["evidence_requirements"].update(minimum=0, required_roles=[]))
        with self.storage.snapshot() as view:
            packet = prepare_input(view, rule, schemas=kit.schemas, scope_id=self.storage.scope_id,
                proposition={"schema": kit.input_schema.reference, "value": {"enabled": True}},
                coverage={"status": "complete", "snapshot": component("absence-coverage")},
                as_of=T2, negative_dependencies=[pin(registration)])
        def gate(prepared, *, as_of):
            with self.storage.snapshot() as view:
                return check_input_current(view, prepared, as_of=as_of)
        result = kit.runner([rule], [binding], clock=lambda: T3).evaluate(packet,
            judgment_id="historical-absence", attempt_id="historical-absence-attempt", check_current=gate)
        self.assertEqual(result.judgment["body"]["failure"]["code"], "E_DEPENDENCY_STALE")
        self.assertEqual(kit.calls, [])


if __name__ == "__main__":
    unittest.main()
