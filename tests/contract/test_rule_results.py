from copy import deepcopy
import unittest

from matter.contracts import ContractError
from matter.rules import RuleDefinition, RuleRegistry, SchemaRegistry
from matter.evaluators import BindingRegistry, EvaluationInput, QualificationRegistry
from matter.evaluators.runner import admit_result
from rule_helpers import RuleTestCase, NOW, LATE, component


class RuleContractTests(RuleTestCase):
    def test_rule_meaning_and_registry_are_immutable(self):
        binding = self.binding()
        definition = self.definition(binding)
        rule = RuleDefinition(definition, schemas=self.schemas)
        reference = rule.reference
        definition["outcomes"][0]["description"] = "mutated"
        copy = rule.value
        copy["evidence_requirements"].clear()
        self.assertEqual(rule.reference, reference)
        self.assertEqual(rule.value["outcomes"][0]["description"], "positive")
        with self.assertRaises(AttributeError):
            rule.extra = "mutation"
        changed = RuleDefinition(definition, schemas=self.schemas)
        self.assertNotEqual(changed.reference, reference)
        self.assert_code("E_POLICY_INVALID", RuleRegistry, [rule, changed])

    def test_input_and_result_contracts_retain_four_distinct_dimensions(self):
        result, rule, binding, packet = self.evaluate()
        body = result.judgment["body"]
        self.assertEqual(body["execution_status"], "completed")
        self.assertEqual(body["evaluation_status"], "applicable")
        self.assertEqual(body["semantic_output"]["value"]["label"], "example:positive")
        self.assertEqual(body["qualification"]["status"], "not_required")
        self.assertEqual(body["input_digest"], packet.digest)
        self.assertEqual(body["input_artifact"], {"state": "unavailable", "reason": "not_persisted"})
        self.assertEqual(result.receipt["body"]["stage"], "evaluation")
        self.assertNotIn("creation_receipt", result.judgment)
        self.assertNotIn("creation_receipt", result.receipt)

    def test_rule_fallback_is_checked_against_exact_schema_and_label(self):
        for mutate in (
            lambda d: d["outcomes"][2]["fallback_output"]["value"].update(label="example:negative"),
            lambda d: d["outcomes"][2]["fallback_output"].update(schema=component("absent-schema")),
            lambda d: d["outcomes"][2]["fallback_output"]["value"].update(unexpected="bad"),
        ):
            definition = self.definition(self.binding())
            mutate(definition)
            with self.assertRaises(ContractError):
                RuleDefinition(definition, schemas=self.schemas)

    def test_unknown_label_and_label_status_mismatch_fail_without_conclusion(self):
        for response in (
            self.response(label="example:invented"),
            self.response(label="example:negative", status="not_applicable"),
        ):
            binding = self.binding(lambda request, output=response: deepcopy(output))
            result, _, _, _ = self.evaluate(binding)
            body = result.judgment["body"]
            self.assertEqual(body["execution_status"], "failed")
            self.assertEqual(body["failure"]["code"], "E_EVIDENCE_INVALID")
            self.assertNotIn("semantic_output", body)
            self.assertEqual(body["proposed_consequences"], [])

    def test_unknown_evidence_or_changed_locator_is_refused(self):
        for mutate in (
            lambda use: use["reference"].update(id="nonexistent"),
            lambda use: use["locator"].update(uri="urn:other-source"),
        ):
            use = {"reference": self.evidence()["reference"], "locator": self.evidence()["locator"]}
            mutate(use)
            binding = self.binding(lambda request, use=use: self.response(uses=[use]))
            result, _, _, _ = self.evaluate(binding)
            self.assertEqual(result.judgment["body"]["failure"]["code"], "E_EVIDENCE_INVALID")

    def test_timeout_cannot_satisfy_negative_prerequisite(self):
        def timeout(request):
            raise TimeoutError("private provider text")
        result, rule, binding, packet = self.evaluate(self.binding(timeout))
        self.assertEqual(result.judgment["body"]["execution_status"], "timed_out")
        self.assertNotIn("semantic_output", result.judgment["body"])
        admission = admit_result(result.judgment, rule, binding=binding, schemas=self.schemas, expected_input=packet,
            as_of=NOW, accepted_labels=["example:negative"])
        self.assertEqual(admission, {"status": "blocked", "reason": "execution_timed_out"})
        self.assertNotIn("private provider", str(result.value))

    def test_insufficient_and_inapplicable_are_completed_distinct_outcomes(self):
        binding = self.binding()
        rule = self.rule(binding)
        incomplete = self.runner([rule], [binding]).evaluate(self.packet(rule, evidence=[]),
            judgment_id="empty-judgment", attempt_id="empty-attempt")
        self.assertEqual(incomplete.judgment["body"]["execution_status"], "completed")
        self.assertEqual(incomplete.judgment["body"]["evaluation_status"], "insufficient_evidence")
        self.assertEqual(self.calls, [])
        self.assertEqual(incomplete.receipt["body"]["details"]["value"]["called"], False)
        rule = self.rule(binding, change=lambda d: d["preconditions"].append(
            {"pointer": "/enabled", "equals": False, "otherwise_label": "example:inapplicable"}))
        packet = self.packet(rule)
        result = self.runner([rule], [binding]).evaluate(packet,
            judgment_id="na-judgment", attempt_id="na-attempt")
        self.assertEqual(result.judgment["body"]["evaluation_status"], "not_applicable")
        self.assertEqual(result.judgment["body"]["semantic_output"]["value"]["label"], "example:inapplicable")
        self.assertEqual(admit_result(result.judgment, rule, binding=binding, schemas=self.schemas, expected_input=packet,
            as_of=NOW, accepted_labels=["example:negative"])["status"], "blocked")

    def test_ambiguous_and_conflicting_remain_inspectable(self):
        for label in ("ambiguous", "conflicting"):
            result, _, _, _ = self.evaluate(self.binding(lambda request, label=label:
                self.response(label="example:" + label, status=label)))
            self.assertEqual(result.judgment["body"]["execution_status"], "completed")
            self.assertEqual(result.judgment["body"]["evaluation_status"], label)
            self.assertEqual(result.judgment["body"]["proposed_consequences"], [])

    def test_recorded_and_deterministic_share_the_input_contract(self):
        deterministic, _, _, first = self.evaluate()
        recorded, _, _, second = self.recorded_result(qualifier="unknown")
        self.assertEqual(set(first.value["packet"]), set(second.value["packet"]))
        self.assertEqual(set(first.value["rule_definition"]), set(second.value["rule_definition"]))
        self.assertEqual(recorded.judgment["body"]["execution_status"], "completed")
        self.assertEqual(recorded.judgment["body"]["qualification"]["status"], "unknown")
        self.assertNotEqual(first.digest, second.digest)

    def test_prepared_input_cannot_be_constructed_from_unverified_packet(self):
        binding = self.binding()
        rule = self.rule(binding)
        packet = self.packet(rule)
        self.assert_code("E_POLICY_INVALID", EvaluationInput, rule, packet.value["packet"])

    def test_exact_rule_and_binding_versions_are_required(self):
        binding = self.binding()
        rule = self.rule(binding)
        bad = rule.reference
        bad["digest"] = "0" * 64
        self.assert_code("E_POLICY_INVALID", RuleRegistry([rule]).resolve, bad)
        bad = binding.reference
        bad["version"] = "different"
        self.assert_code("E_POLICY_INVALID", BindingRegistry([binding]).resolve, bad)

    def test_unknown_certificate_and_high_score_do_not_grant_qualification(self):
        result, rule, binding, packet = self.recorded_result(
            certificate={"reference": component("unknown-certificate")})
        self.assertEqual(result.judgment["body"]["qualification"]["status"], "unknown")
        self.assertEqual(admit_result(result.judgment, rule, binding=binding, schemas=self.schemas, expected_input=packet,
            as_of=NOW, accepted_labels=["example:positive"])["reason"], "qualification_unknown")

    def test_admitted_certificate_exact_match_expiry_and_scope(self):
        binding = self.recorded()
        rule = self.rule(binding)
        certificate = self.certificate(rule, binding)
        registry = QualificationRegistry([certificate])
        result, rule, binding, packet = self.recorded_result(certificate=certificate, qualifications=registry)
        self.assertEqual(result.judgment["body"]["qualification"]["status"], "qualified")
        self.assertEqual(admit_result(result.judgment, rule, binding=binding, schemas=self.schemas, expected_input=packet,
            qualifications=registry, as_of=LATE, accepted_labels=["example:positive"])["reason"], "qualification_expired")
        wrong = self.certificate(rule, binding, change=lambda c: c.update(task_scope=component("other-task")))
        result, _, _, _ = self.recorded_result(certificate=wrong, qualifications=QualificationRegistry([wrong]))
        self.assertEqual(result.judgment["body"]["qualification"]["status"], "mismatched")

    def test_certificate_is_checked_at_execution_time_not_historical_cut(self):
        binding = self.recorded()
        rule = self.rule(binding)
        packet = self.packet(rule)
        certificate = self.certificate(rule, binding)
        response = self.response(qualification={"status": "qualified", "certificate": certificate["reference"]})
        recorded = self.recorded([{"input_digest": packet.digest, "response": response}])
        result = self.runner([rule], [recorded], qualifications=QualificationRegistry([certificate]),
            clock=lambda: deepcopy(LATE)).evaluate(packet, judgment_id="historical", attempt_id="historical-attempt")
        self.assertEqual(result.judgment["body"]["qualification"]["status"], "expired")

    def test_qualification_cannot_authorize_undeclared_proposal(self):
        initial = self.recorded()
        rule = self.rule(initial)
        packet = self.packet(rule)
        certificate = self.certificate(rule, initial)
        output = self.response(qualification={"status": "qualified", "certificate": certificate["reference"]},
            proposals=[{"schema": self.proposal_schema.reference, "value": {"reason": "Take action."}}])
        binding = self.recorded([{"input_digest": packet.digest, "response": output}])
        result = self.runner([rule], [binding], qualifications=QualificationRegistry([certificate])).evaluate(
            packet, judgment_id="attempted-authority", attempt_id="attempted-authority-receipt")
        self.assertEqual(result.judgment["body"]["execution_status"], "failed")
        self.assertEqual(result.judgment["body"]["failure"]["code"], "E_AUTHORITY_REQUIRED")
        self.assertEqual(result.judgment["body"]["proposed_consequences"], [])


if __name__ == "__main__":
    unittest.main()

