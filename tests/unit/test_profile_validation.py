"""Synthetic MAT-013 behavior; no provider accuracy or publication assertions."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import unittest

from matter.canonical import canonical_digest
from matter.contracts import ContractError
from matter.profiles import ProfileDefinition, ProfileRegistry, ProfileValidationError, compare_profiles
from matter.rules import RuleDefinition, RuleRegistry, SchemaDefinition, SchemaRegistry
from matter._rule_values import preparation_reference
from matter.evaluators import QualificationRegistry, RecordedBinding


def ref(identity):
    return {"namespace": "example", "id": identity, "version": "1.0",
            "digest": canonical_digest({"identity": identity}, "example.declaration.v1")}


def schema(identity, properties):
    return SchemaDefinition("example", identity, "1.0", {
        "$schema": "https://json-schema.org/draft/2020-12/schema", "$id": "urn:profile:" + identity,
        "type": "object", "additionalProperties": False, "properties": properties, "required": list(properties)})


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.input = schema("question", {"question": {"type": "string"}})
        self.output = schema("answer", {"label": {"type": "string"}})
        self.proposal = schema("proposal", {"reason": {"type": "string"}})
        self.schemas = SchemaRegistry([self.input, self.output, self.proposal])
        self.resolver = ref("retain-conflicts")
        self.binding = RecordedBinding("example", "fixture", "1.0", evaluator=ref("recorded-model"), semantics="Synthetic recording.")
        self.rule = self.make_rule()

    def make_rule(self, *, identity="comparison", change=None):
        value = {"schema_version": "1.0", "namespace": "example", "rule_id": identity, "semantic_version": "1.0",
                 "family": "association", "description": "Compare whether the subjects concern the same topic.",
                 "input_schema": self.input.reference, "output_schema": self.output.reference,
                 "proposition_template": "Do these subjects concern the same topic?",
                 "evidence_preparation": preparation_reference(),
                 "evidence_requirements": {"allowed_kinds": ["observation"], "allowed_origins": ["source"],
                    "minimum": 0, "required_roles": [], "require_complete_coverage": False,
                    "locator_adapters": [], "incomplete_label": "example:unknown"},
                 "preconditions": [], "dependencies": [],
                 "outcomes": [{"label": "example:yes", "description": "The subjects have the same topic.",
                               "evaluation_status": "applicable", "implications": []},
                              {"label": "example:unknown", "description": "Insufficient basis.",
                               "evaluation_status": "insufficient_evidence", "implications": [],
                               "fallback_output": {"schema": self.output.reference, "value": {"label": "example:unknown"}}}],
                 "evaluator_binding": self.binding.reference,
                 "qualification_requirement": {"kind": "certificate", "reason": "Separate qualification required.",
                    "task_scope": ref("task"), "threshold_policy": ref("threshold")},
                 "conflict_policy": self.resolver, "consequence_permissions": [],
                 "resource_limits": {"max_input_bytes": 1024, "max_output_bytes": 512,
                    "max_evidence": 16, "max_elapsed_ms": 1000, "max_calls": 1, "max_retries": 0},
                 "temporal_dependencies": [],
                 "conformance_cases": [{"name": "unknown", "invariant": "Insufficient evidence stays unknown."}]}
        if change:
            change(value)
        return RuleDefinition(value, schemas=self.schemas)

    def component(self, rules=()):
        return {"semantic_version": "1.0", "description": "Synthetic component.",
                "rules": [rule.reference for rule in rules], "parameters": {}, "dependencies": [],
                "outputs": [{"name": "example:conclusion", "rule": rule.reference, "schema": self.output.reference,
                    "accepted_labels": ["example:yes"], "accepted_statuses": ["applicable"]} for rule in rules],
                "data_scopes": ["synthetic"], "capabilities": [], "conflict_resolvers": [self.resolver],
                "resource_limits": {"max_calls": len(rules), "max_input_bytes": 1024 * len(rules),
                    "max_output_bytes": 512 * len(rules), "max_evidence": 16 if rules else 0,
                    "max_elapsed_ms": 1000 * len(rules)}, "lifecycle_extensions": [],
                "conformance_cases": [{"name": "explicit", "invariant": "No implicit conflict fallback."}]}

    def definition(self, rule=None):
        return {"schema_version": "1.0", "namespace": "example", "profile_id": "neutral-profile",
                "semantic_version": "1.0", "description": "Synthetic profile.",
                "components": {"evidence": self.component([rule or self.rule]), "audience": self.component()},
                "required_outputs": ["example:conclusion"],
                "resource_limits": {"max_calls": 8, "max_input_bytes": 8192, "max_output_bytes": 4096,
                    "max_evidence": 32, "max_elapsed_ms": 8000}, "incomplete_evaluation": "retain_unresolved"}

    def profile(self, value=None, *, rules=None, **kwargs):
        return ProfileDefinition(self.definition() if value is None else value,
            rules=RuleRegistry([self.rule] if rules is None else rules), schemas=self.schemas,
            allowed_data_scopes=kwargs.pop("allowed_data_scopes", ["synthetic"]),
            conflict_resolvers=kwargs.pop("conflict_resolvers", [self.resolver]), **kwargs)

    def invalid(self, value, path, *, rules=None, **kwargs):
        with self.assertRaises(ProfileValidationError) as error:
            self.profile(value, rules=rules, **kwargs)
        self.assertEqual(error.exception.code, "E_POLICY_INVALID")
        self.assertEqual(error.exception.path, path)
        return error.exception

    def test_same_shape_changed_question_has_new_semantic_binding(self):
        changed = self.make_rule(change=lambda d: d.update(description="Compare continuing subject identity.",
            proposition_template="Do these reports concern the same continuing matter?"))
        before = self.profile()
        after = self.profile(self.definition(changed), rules=[changed])
        result = compare_profiles(before, after)
        self.assertTrue(result["structurally_compatible"])
        self.assertFalse(result["semantic_equivalent"])
        self.assertFalse(result["qualification_transfer"])
        self.assertEqual(result["changed_components"], ["evidence"])
        self.assertNotEqual(before.reference, after.reference)

    def test_audience_cadence_does_not_change_independent_evidence(self):
        before = self.profile()
        value = self.definition()
        value["components"]["audience"]["parameters"]["cadence"] = "daily"
        after = self.profile(value)
        self.assertEqual(before.component_references["evidence"], after.component_references["evidence"])
        self.assertEqual(before.dependencies["evidence"], after.dependencies["evidence"])
        self.assertEqual(compare_profiles(before, after)["changed_components"], ["audience"])

    def test_profile_level_semantic_changes_are_separate_from_component_changes(self):
        before = self.profile()
        for field, replacement in (("required_outputs", []),
                                   ("incomplete_evaluation", "withhold_consequences"),
                                   ("description", "Requires a new interpretation."),
                                   ("resource_limits", {**self.definition()["resource_limits"], "max_calls": 7})):
            value = self.definition()
            value[field] = replacement
            comparison = compare_profiles(before, self.profile(value))
            self.assertEqual(comparison["changed_components"], [])
            self.assertEqual(comparison["profile_changes"], [field])
            self.assertFalse(comparison["semantic_equivalent"])
            self.assertFalse(comparison["qualification_transfer"])

    def test_declared_dependency_propagates_component_semantics(self):
        value = self.definition()
        value["components"]["evidence"]["dependencies"] = ["audience"]
        before = self.profile(value)
        value["components"]["audience"]["parameters"]["cadence"] = "daily"
        after = self.profile(value)
        self.assertNotEqual(before.component_references["evidence"], after.component_references["evidence"])
        self.assertEqual(compare_profiles(before, after)["changed_components"], ["evidence", "audience"])

    def test_order_labels_rendering_and_preparation_are_fingerprinted(self):
        original = self.profile()
        for change in (
            lambda d: d["outcomes"].reverse(),
            lambda d: d["outcomes"][0].update(description="Same continuing matter, not topic."),
            lambda d: d.update(evidence_preparation=ref("changed-preparation")),
        ):
            changed = self.make_rule(change=change)
            profile = self.profile(self.definition(changed), rules=[changed])
            self.assertNotEqual(original.component_references["evidence"], profile.component_references["evidence"])
        value = self.definition()
        value["components"]["evidence"]["parameters"]["rendering"] = {"ordered_options": ["same", "different"]}
        self.assertNotEqual(original.reference, self.profile(value).reference)

    def test_missing_exact_rule_never_resolves_latest(self):
        value = self.definition()
        value["components"]["evidence"]["rules"][0]["version"] = "missing"
        self.invalid(value, "/components/evidence/rules/0")

    def test_undefined_label_and_mismatched_schema_fail_at_binding(self):
        value = self.definition()
        value["components"]["evidence"]["outputs"][0]["accepted_labels"] = ["example:invented"]
        self.invalid(value, "/components/evidence/outputs/0/accepted_labels/0")
        value = self.definition()
        value["components"]["evidence"]["outputs"][0]["schema"] = self.input.reference
        self.invalid(value, "/components/evidence/outputs/0/schema")

    def test_output_statuses_must_match_label_meaning(self):
        value = self.definition()
        value["components"]["evidence"]["outputs"][0]["accepted_statuses"] = ["insufficient_evidence"]
        self.invalid(value, "/components/evidence/outputs/0/accepted_statuses")

    def test_denied_capability_is_not_created_by_profile_text(self):
        value = self.definition()
        value["components"]["evidence"]["capabilities"] = [self.proposal.reference]
        self.invalid(value, "/components/evidence/capabilities")
        self.profile(value, allowed_capabilities=[self.proposal.reference])

    def test_rule_implications_require_component_and_host_admission(self):
        changed = self.make_rule(change=lambda d: (d.update(consequence_permissions=[self.proposal.reference]),
            d["outcomes"][0].update(implications=[self.proposal.reference])))
        value = self.definition(changed)
        self.invalid(value, "/components/evidence/rules/0/consequence_permissions", rules=[changed],
                     allowed_capabilities=[self.proposal.reference])
        value["components"]["evidence"]["capabilities"] = [self.proposal.reference]
        self.profile(value, rules=[changed], allowed_capabilities=[self.proposal.reference])

    def test_data_scope_requires_host_ceiling(self):
        self.invalid(self.definition(), "/components/evidence/data_scopes/0", allowed_data_scopes=[])

    def test_missing_conflict_resolver_does_not_choose_last_writer(self):
        value = self.definition()
        value["components"]["evidence"]["conflict_resolvers"] = []
        self.invalid(value, "/components/evidence/rules/0/conflict_policy")
        self.invalid(self.definition(), "/components/evidence/conflict_resolvers", conflict_resolvers=[])

    def test_required_output_needs_a_producer(self):
        value = self.definition()
        value["required_outputs"].append("example:missing")
        self.invalid(value, "/required_outputs/1")

    def test_component_cycles_and_unknown_components_fail(self):
        value = self.definition()
        value["components"]["evidence"]["dependencies"] = ["audience"]
        value["components"]["audience"]["dependencies"] = ["evidence"]
        self.invalid(value, "/components/evidence/dependencies")
        value = self.definition()
        value["components"]["evidence"]["dependencies"] = ["purpose"]
        self.invalid(value, "/components/evidence/dependencies")

    def test_each_resource_dimension_has_a_concrete_failure_path(self):
        for name in ("max_calls", "max_input_bytes", "max_output_bytes", "max_evidence", "max_elapsed_ms"):
            value = self.definition()
            value["components"]["evidence"]["resource_limits"][name] = 0
            self.invalid(value, "/components/evidence/resource_limits/" + name)

    def test_profile_budget_cannot_be_exceeded_by_components(self):
        value = self.definition()
        value["resource_limits"]["max_calls"] = 0
        self.invalid(value, "/components/evidence/resource_limits/max_calls")

    def test_rule_dependencies_require_exact_selected_predecessor_and_labels(self):
        changed = self.make_rule(identity="dependent", change=lambda d: d.update(dependencies=[{
            "rule": self.rule.reference, "accepted_labels": ["example:yes"],
            "accepted_statuses": ["applicable"], "require_qualified": True}]))
        self.invalid(self.definition(changed), "/components/evidence/rules/0/dependencies/0", rules=[changed, self.rule])
        value = self.definition()
        dependent_component = self.component([changed])
        dependent_component["outputs"][0]["name"] = "example:dependent"
        value["components"]["purpose"] = dependent_component
        self.invalid(value, "/components/purpose/rules/0/dependencies/0", rules=[changed, self.rule])
        value["components"]["purpose"]["dependencies"] = ["evidence"]
        accepted = self.profile(value, rules=[self.rule, changed])
        self.assertEqual(len(accepted.dependencies["purpose"]["rules"]), 2)
        changed_bad = self.make_rule(identity="dependent", change=lambda d: d.update(dependencies=[{
            "rule": self.rule.reference, "accepted_labels": ["example:missing"],
            "accepted_statuses": ["applicable"], "require_qualified": True}]))
        value["components"]["purpose"] = self.component([changed_bad])
        value["components"]["purpose"]["outputs"][0]["name"] = "example:dependent"
        value["components"]["purpose"]["dependencies"] = ["evidence"]
        self.invalid(value, "/components/purpose/rules/0/dependencies/0/accepted_labels/0", rules=[self.rule, changed_bad])

    def test_input_and_public_copies_cannot_mutate_profile(self):
        value = self.definition()
        profile = self.profile(value)
        original = profile.reference
        value["components"]["evidence"]["parameters"]["changed"] = True
        profile.value["components"].clear()
        profile.component_references["evidence"]["version"] = "changed"
        profile.dependencies["evidence"]["rules"].clear()
        self.assertEqual(profile.reference, original)
        self.assertEqual(len(profile.dependencies["evidence"]["rules"]), 1)
        with self.assertRaises(AttributeError):
            profile._encoded = b"{}"

    def test_registry_supersession_retains_history_and_returns_notice_only(self):
        previous = self.profile()
        registry = ProfileRegistry([previous])
        value = self.definition()
        value["semantic_version"] = "2.0"
        value["components"]["audience"]["parameters"]["cadence"] = "daily"
        replacement = self.profile(value)
        updated, notice = registry.supersede(previous.reference, replacement)
        self.assertIs(updated.resolve(previous.reference), previous)
        self.assertIs(updated.resolve(replacement.reference), replacement)
        self.assertEqual(notice["cause"], "policy_change")
        self.assertEqual(notice["changed_components"], ["audience"])
        self.assertFalse(notice["qualification_transfer"])
        with self.assertRaises(ContractError):
            registry.resolve(replacement.reference)
        wrong = previous.reference
        wrong["digest"] = replacement.reference["digest"]
        with self.assertRaises(ContractError):
            updated.resolve(wrong)
        with self.assertRaises(ContractError):
            ProfileRegistry([previous, previous])
        with self.assertRaises(AttributeError):
            registry._profiles = ()

    def test_same_version_changed_meaning_cannot_supersede(self):
        before = self.profile()
        value = self.definition()
        value["components"]["audience"]["parameters"]["cadence"] = "daily"
        with self.assertRaises(ContractError):
            ProfileRegistry([before]).supersede(before.reference, self.profile(value))

    def test_two_profiles_bind_same_matter_concurrently_without_mutation(self):
        first = self.profile()
        value = self.definition()
        value["profile_id"] = "second-profile"
        second = self.profile(value)
        matter = {"scope_id": "synthetic", "namespace": "example", "record_type": "matter", "id": "continuing", "revision": 1}
        with ThreadPoolExecutor(max_workers=2) as pool:
            values = list(pool.map(lambda profile: profile.assessment_binding(matter,
                purpose=ref("purpose"), audience=ref("audience")), [first, second]))
        self.assertEqual(values[0]["matter"], values[1]["matter"])
        self.assertNotEqual(values[0]["profile"], values[1]["profile"])
        values[0]["matter"]["revision"] = 999
        self.assertEqual(matter["revision"], 1)
        with self.assertRaises(ProfileValidationError):
            first.assessment_binding(matter, purpose=ref("purpose"))

    def test_lifecycle_extensions_are_schema_checked_and_scoped(self):
        value = self.definition()
        value["components"]["audience"]["lifecycle_extensions"] = [{"schema": self.input.reference, "value": {"question": "declaration"}}]
        self.invalid(value, "/components/audience/lifecycle_extensions")
        value["components"]["audience"]["lifecycle_extensions"] = []
        value["components"]["lifecycle"] = self.component()
        value["components"]["lifecycle"]["lifecycle_extensions"] = [{"schema": self.input.reference, "value": {"invented": True}}]
        self.invalid(value, "/components/lifecycle/lifecycle_extensions/0")

    def test_source_text_is_only_data_and_missing_fields_have_safe_paths(self):
        value = self.definition()
        value["components"]["evidence"]["parameters"]["source_text"] = "__import__('os').system('touch SHOULD_NOT_RUN')"
        self.profile(value)
        del value["components"]["evidence"]["conflict_resolvers"]
        error = self.invalid(value, "/components/evidence/conflict_resolvers")
        self.assertNotIn("SHOULD_NOT_RUN", str(error))

    def test_an_old_certificate_cannot_qualify_new_same_shape_meaning(self):
        old = self.rule
        changed = self.make_rule(change=lambda d: d.update(proposition_template="Same continuing matter?"))
        value = {"rule": old.reference, "binding": self.binding.reference,
                 "input_schema": self.input.reference, "output_schema": self.output.reference,
                 "preparation": old.value["evidence_preparation"], "task_scope": ref("task"),
                 "threshold_policy": ref("threshold"),
                 "valid_from": {"state": "known", "value": "2026-10-01T00:00:00Z", "precision": "second"},
                 "valid_until": {"state": "known", "value": "2026-11-01T00:00:00Z", "precision": "second"},
                 "evaluation_evidence": [{"scope_id": "synthetic", "namespace": "example", "record_type": "observation", "id": "evidence", "digest": "a" * 64}]}
        certificate_ref = {**ref("certificate"), "digest": canonical_digest(value, "matter.qualification-certificate.v1")}
        registry = QualificationRegistry([{**value, "reference": certificate_ref}])
        reported = {"status": "qualified", "certificate": certificate_ref}
        now = {"state": "known", "value": "2026-10-26T00:00:00Z", "precision": "second"}
        self.assertEqual(registry.classify(reported, rule=old, binding=self.binding, context=[ref("task")], as_of=now)["status"], "qualified")
        self.assertEqual(registry.classify(reported, rule=changed, binding=self.binding, context=[ref("task")], as_of=now)["status"], "mismatched")


if __name__ == "__main__":
    unittest.main()
