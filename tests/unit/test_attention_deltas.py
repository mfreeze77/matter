"""MAT-019 pure semantic projection invariants, separate from host authority."""

from copy import deepcopy
import unittest

from matter.attention import AttentionPolicy, decide_attention, project_material
from matter.contracts import ContractError
from matter.dispositions import disposition_scope_ref
from matter.storage import pin
from integration.helpers import record_input
from rule_helpers import component


def policy_value(schema, profile, *, roles=None, decision=None):
    return {"schema_version": "1.0", "namespace": "example", "id": "attention", "semantic_version": "1.0",
        "description": "Synthetic bounded typed condition policy.", "profile": profile,
        "fields": [{"name": "condition", "claim_schema": schema, "predicate": "example:condition",
            "condition_pointer": "/condition", "condition": {"key": "a", "circumstance": "required-operation"},
            "value_pointer": "/signal", "roles": roles or ["material", "relevance"],
            "accepted_statuses": ["supported"], "accepted_values": ["present"]}],
        "routine_treatment": "update", "disposition_namespace": "example:dispositions", "decision": decision,
        "delivery_producers": [{"producer": component("host-transport"), "outcome": "example:delivered"}]}


class AttentionDeltaTests(unittest.TestCase):
    def setUp(self):
        self.schema = component("condition-schema")
        self.policy = AttentionPolicy(policy_value(self.schema, component("profile")))
        self.assessment = record_input("assessment", "synthetic-assessment")
        self.matter = self.assessment["body"]["matter"]

    def claim(self, identity, *, signal="present", subject=None, narrative="Synthetic paraphrase."):
        record = record_input("claim", identity)
        record["creation_receipt"] = {"scope_id": record["scope_id"], "namespace": "example", "record_type": "receipt", "id": "claim-creation"}
        record["body"].update(subject=subject or {k: self.matter[k] for k in ("scope_id", "namespace", "record_type", "id")},
            predicate="example:condition", value={"schema": self.schema, "value": {
                "condition": {"key": "a", "circumstance": "required-operation"}, "signal": signal, "narrative": narrative}})
        return record

    def project(self, claims, statuses=None):
        self.assessment["body"]["propositions"] = [{"claim": pin(c), "status": (statuses or {}).get(c["id"], "supported"),
            "evidence_standard": component("evidence-standard")} for c in claims]
        return project_material(self.policy, self.assessment, claims)

    def test_paraphrase_ids_attempts_and_time_do_not_change_semantic_material(self):
        first = self.claim("original")
        original = self.project([first])[0]
        self.assessment["id"] = "new-internal-attempt"
        self.assessment["body"]["assessed_as_of"]["value"] = "2026-10-12T15:00:00Z"
        later = self.claim("different-claim-id", narrative="A completely different wording of the same typed condition.")
        self.assertEqual(self.project([later])[0], original)
        self.assertEqual(self.project([later, first])[0], original)

    def test_explicit_linked_correction_replaces_old_selected_assertion_without_policy_change(self):
        first = self.claim("old")
        corrected = self.claim("corrected", signal="retracted")
        corrected["supersedes"] = [pin(first)]
        material, selections, _ = self.project([first, corrected], {"corrected": "unknown"})
        self.assertEqual(material["condition"], {"status": "unknown", "value": "retracted"})
        self.assertEqual(selections["condition"], [pin(corrected)])

    def test_conflicting_matches_and_foreign_subject_cannot_satisfy_relevance(self):
        first, conflict = self.claim("first"), self.claim("conflict", signal="recovered")
        self.assertEqual(self.project([first, conflict])[0]["condition"], {"status": "unknown", "value": None})
        foreign = self.claim("foreign", subject={**self.claim("template")["body"]["subject"], "id": "other-matter"})
        self.assertEqual(self.project([foreign])[0]["condition"], {"status": "unknown", "value": None})
        material, selections, values = self.project([])
        decision = decide_attention(self.policy, self.assessment, values, material, None, purpose_active=True,
            audience_active=True, audience_reference=component("human"), audience_kind="human", owned=False,
            lifecycle_role=None, dispositions=[], selections=selections)
        self.assertIn("insufficient_evidence", decision["reasons"])

    def test_correction_cannot_borrow_an_unchanged_or_nonmaterial_field(self):
        claim = self.claim("ordinary-change", signal="recovered")
        material, selections, values = self.project([claim])
        baseline = {"material": {"condition": {"status": "supported", "value": "present"}},
                    "material_contract": self.policy.material_contract}
        result = decide_attention(self.policy, self.assessment, values, material, baseline, purpose_active=True,
            audience_active=True, audience_reference=component("human"), audience_kind="human", owned=False,
            lifecycle_role=None, dispositions=[], selections=selections, linked_fields={"other-nonmaterial-field"})
        self.assertNotEqual(result["treatment"], "correction")
        # Merely changing a projection contract cannot make a reassertion into
        # a source correction when the named material value did not change.
        baseline = {"material": deepcopy(material), "material_contract": component("different-material-contract")}
        result = decide_attention(self.policy, self.assessment, values, material, baseline, purpose_active=True,
            audience_active=True, audience_reference=component("human"), audience_kind="human", owned=False,
            lifecycle_role=None, dispositions=[], selections=selections, linked_fields={"condition"})
        self.assertNotEqual(result["treatment"], "correction")

    def test_low_confidence_or_unknown_alone_never_requests_a_person(self):
        claim = self.claim("uncertain")
        material, _, values = self.project([claim], {"uncertain": "unknown"})
        decision = decide_attention(self.policy, self.assessment, values, material, None, purpose_active=True,
            audience_active=True, audience_reference=component("human"), audience_kind="human", owned=False,
            lifecycle_role=None, dispositions=[])
        self.assertEqual(decision["treatment"], "quiet")
        self.assertIn("insufficient_evidence", decision["reasons"])
        self.assertIsNone(decision["decision_request"])

    def test_same_material_has_all_no_delta_and_coverage_quiet_reasons(self):
        material, _, values = self.project([self.claim("fact")])
        self.assessment["body"]["evidence_selection"]["coverage"]["status"] = "partial"
        baseline = {"material": deepcopy(material), "material_contract": self.policy.material_contract}
        decision = decide_attention(self.policy, self.assessment, values, material, baseline, purpose_active=False,
            audience_active=True, audience_reference=component("human"), audience_kind="human", owned=False,
            lifecycle_role=None, dispositions=["deferral"])
        self.assertEqual(decision["treatment"], "quiet")
        self.assertTrue({"no_active_purpose", "no_material_change", "already_delivered", "incomplete_coverage",
                         "disposition_applies", "deferred_until_checkpoint"} <= set(decision["reasons"]))

    def test_policy_namespaces_and_delivery_outcomes_match_consuming_core_contracts(self):
        for field in ("namespace", "disposition_namespace"):
            for invalid in ("1ops", "@ops", "+"):
                value = self.policy.value
                value[field] = invalid
                with self.subTest(field=field, invalid=invalid), self.assertRaises(ContractError):
                    AttentionPolicy(value)
        value = self.policy.value
        value.update(namespace="acme_ops", disposition_namespace="host_dispositions")
        value["delivery_producers"][0]["outcome"] = "host_ops:delivered"
        valid = AttentionPolicy(value)
        self.assertEqual(valid.reference["namespace"], "acme_ops")
        link = {"reference": component("context"), "context": {
            "scope_id": self.assessment["scope_id"], "namespace": "host_contexts", "record_type": "matter:projection", "id": "scope", "revision": 1}}
        self.assertEqual(disposition_scope_ref(namespace=valid.value["disposition_namespace"], kind="acknowledgement",
            matter={key: self.matter[key] for key in ("scope_id", "namespace", "record_type", "id")},
            purpose=link, audience=link, subject=pin(self.claim("subject")))["namespace"], "host_dispositions")
        value["delivery_producers"][0]["outcome"] = "delivered"
        with self.assertRaises(ContractError):
            AttentionPolicy(value)

    def test_exact_json_conditions_and_admitted_values_distinguish_false_and_zero(self):
        for condition, other in ((False, 0), ({"flag": False}, {"flag": 0})):
            value = self.policy.value
            value["fields"][0]["condition"] = condition
            policy = AttentionPolicy(value)
            claim = self.claim("different-type-condition")
            claim["body"]["value"]["value"]["condition"] = other
            self.assessment["body"]["propositions"] = [{"claim": pin(claim), "status": "supported", "evidence_standard": component("standard")}]
            material, selections, _ = project_material(policy, self.assessment, [claim])
            self.assertEqual(selections["condition"], [])
            self.assertEqual(material["condition"]["status"], "unknown")
        value = self.policy.value
        value["fields"][0]["accepted_values"] = [0]
        policy = AttentionPolicy(value)
        claim = self.claim("false-is-not-zero", signal=False)
        self.assessment["body"]["propositions"] = [{"claim": pin(claim), "status": "supported", "evidence_standard": component("standard")}]
        material, selections, values = project_material(policy, self.assessment, [claim])
        decision = decide_attention(policy, self.assessment, values, material, None, purpose_active=True, audience_active=True,
            audience_reference=component("human"), audience_kind="human", owned=False, lifecycle_role=None,
            dispositions=[], selections=selections)
        self.assertEqual(decision["treatment"], "quiet")
        self.assertIn("no_relevance", decision["reasons"])

    def test_false_to_zero_is_an_actual_material_delta_including_nested_values(self):
        for before, after in ((False, 0), ({"flag": False}, {"flag": 0})):
            definition = self.policy.value
            definition["fields"][0]["accepted_values"] = [before, after]
            policy = AttentionPolicy(definition)
            claim = self.claim("typed-material", signal=before)
            self.assessment["body"]["propositions"] = [{"claim": pin(claim), "status": "supported", "evidence_standard": component("standard")}]
            old, _, _ = project_material(policy, self.assessment, [claim])
            changed = self.claim("typed-material-next", signal=after)
            self.assessment["body"]["propositions"][0]["claim"] = pin(changed)
            material, selections, values = project_material(policy, self.assessment, [changed])
            result = decide_attention(policy, self.assessment, values, material,
                {"material": old, "material_contract": policy.material_contract}, purpose_active=True, audience_active=True,
                audience_reference=component("human"), audience_kind="human", owned=False, lifecycle_role=None,
                dispositions=[], selections=selections)
            self.assertEqual(result["changed_fields"], ["condition"])
            self.assertEqual(result["treatment"], "update")
