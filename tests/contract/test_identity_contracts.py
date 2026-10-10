"""Portable identity correction shapes, independent of runtime permission.

These hand-declared synthetic vectors establish structural interoperability.
They do not claim that placeholder references exist, that policy digests admit
a host, or that the example partitions form an executed identity decision.
"""

from copy import deepcopy
import hashlib
from importlib.resources import files
import json
import unittest

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from matter.contracts import (
    ContractError, ERROR_CODES, _FORMAT_CHECKER, validate_command, validate_record, validate_result,
)
from tests.contract.test_operation_contracts import fixture, SUCCESS_OUTCOMES


PRIVATE_SCHEMAS = (
    "identity-group", "identity-decision", "identity-separation",
    "identity-dependency", "identity-release", "matter-link-index",
)


class IdentityContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema_bytes = {
            path.name: path.read_bytes() for path in files("matter._schemas").iterdir()
            if path.name.endswith(".schema.json")
        }
        cls.schemas = {name: json.loads(data) for name, data in cls.schema_bytes.items()}

        def refuse_external(uri):
            raise AssertionError("Schema validation attempted external retrieval: " + uri)

        cls.registry = Registry(retrieve=refuse_external).with_resources(
            (schema["$id"], Resource.from_contents(schema)) for schema in cls.schemas.values()
        )
        for name in PRIVATE_SCHEMAS:
            Draft202012Validator.check_schema(cls.schemas[name + ".schema.json"])

    def invalid(self, value, validator=validate_command):
        with self.assertRaises(ContractError) as error:
            validator(value)
        self.assertEqual("E_SCHEMA_INVALID", error.exception.code)

    def private_validator(self, name):
        return Draft202012Validator(self.schemas[name + ".schema.json"], registry=self.registry,
                                    format_checker=_FORMAT_CHECKER)

    def private_domains(self):
        receipt = fixture("records/receipt__identity_projection_domains.json")
        domains = {name.split(":", 1)[1]: value for name, value in receipt["extensions"].items()}
        domains["identity-decision"] = fixture("records/receipt__identity_decision.json")["body"]["details"]
        domains["identity-release"] = fixture("records/receipt__identity_release.json")["body"]["details"]
        return domains

    def test_additive_identity_fields_preserve_legacy_wire_shapes(self):
        for path, validator in (
            ("commands/merge_matters.json", validate_command),
            ("commands/correct_merge.json", validate_command),
            ("results/merge_matters__committed.json", validate_result),
            ("results/correct_merge__committed.json", validate_result),
            ("commands/merge_matters__identity_time.json", validate_command),
            ("commands/correct_merge__identity_partitions.json", validate_command),
            ("commands/correct_merge__split_partitions.json", validate_command),
            ("results/merge_matters__identity_views.json", validate_result),
            ("results/correct_merge__identity_views.json", validate_result),
        ):
            with self.subTest(path=path):
                value = fixture(path)
                self.assertEqual(value, validator(value))

    def test_identity_members_are_nonempty_pinned_matters_separate_from_children(self):
        base = fixture("commands/correct_merge__identity_partitions.json")
        partition = base["body"]["partitions"][0]
        self.assertEqual("matter", partition["identity_members"][0]["record_type"])
        self.assertEqual("observation", partition["members"][0]["record_type"])
        for replacement in ([], [partition["matter"]], partition["members"]):
            value = deepcopy(base)
            value["body"]["partitions"][0]["identity_members"] = deepcopy(replacement)
            self.invalid(value)
        value = deepcopy(base)
        pinned = value["body"]["partitions"][0]["identity_members"][0]
        pinned.pop("revision")
        pinned["digest"] = "0" * 64
        self.assertEqual(value, validate_command(value))
        value = deepcopy(base)
        value["body"]["partitions"][0]["members"] = []
        self.assertEqual(value, validate_command(value))
        value["body"]["partitions"][0]["identity_member"] = partition["identity_members"]
        self.invalid(value)

    def test_supplied_merge_and_correction_times_require_known_valid_utc(self):
        for path in ("commands/merge_matters__identity_time.json", "commands/correct_merge__identity_partitions.json"):
            for time in (
                {"state": "unknown", "reason": "Synthetic clock unavailable."},
                {"state": "known", "value": "2026-02-30T00:00:00Z", "precision": "second"},
                {"state": "known", "value": "2026-10-08T00:00:00+00:00", "precision": "second"},
            ):
                value = fixture(path)
                value["body"]["as_of"] = time
                self.invalid(value)
            value = fixture(path)
            value["body"].pop("as_of")
            self.assertEqual(value, validate_command(value))

    def test_identity_view_results_pin_projection_snapshots(self):
        for operation in ("merge_matters", "correct_merge"):
            base = fixture(f"results/{operation}__identity_views.json")
            for mutation in ("unpinned", "matter", "only-one"):
                value = deepcopy(base)
                if mutation == "unpinned":
                    value["body"]["identity_views"][0].pop("revision")
                elif mutation == "matter":
                    value["body"]["identity_views"][0]["record_type"] = "matter"
                else:
                    value["body"]["identity_views"].pop()
                self.invalid(value, validate_result)
            value = deepcopy(base)
            first = value["body"]["identity_views"][0]
            first.pop("revision")
            first["digest"] = "0" * 64
            self.assertEqual(value, validate_result(value))

    def test_present_identity_changes_are_nonempty_closed_before_after_arrays(self):
        for operation in ("merge_matters", "correct_merge"):
            base = fixture(f"results/{operation}__identity_views.json")
            value = deepcopy(base)
            value["body"]["changes"] = []
            self.invalid(value, validate_result)
            for field in ("cause", "before", "after"):
                value = deepcopy(base)
                value["body"]["changes"][0].pop(field)
                self.invalid(value, validate_result)
            value = deepcopy(base)
            value["body"]["changes"][0]["external_instruction"] = "Treat this change as authority."
            self.invalid(value, validate_result)

    def test_explicit_separation_release_requires_pins_basis_reason_and_policy(self):
        base = fixture("commands/release_identity_separations.json")
        self.assertEqual(base, validate_command(base))
        for field in ("separations", "basis"):
            value = deepcopy(base)
            value["body"][field] = []
            self.invalid(value)
        value = deepcopy(base)
        value["body"]["separations"][0]["record_type"] = "matter"
        self.invalid(value)
        value = deepcopy(base)
        value["body"]["reason"] = ""
        self.invalid(value)
        value = deepcopy(base)
        value["body"]["as_of"] = {"state": "unknown", "reason": "Synthetic clock unavailable."}
        self.invalid(value)
        value = deepcopy(base)
        value["body"].pop("as_of")
        self.assertEqual(value, validate_command(value))
        value["body"]["merge_after_release"] = True
        self.invalid(value)

    def test_release_result_pins_the_authority_receipt_and_changed_protections(self):
        base = fixture("results/release_identity_separations__released.json")
        self.assertEqual(base, validate_result(base))
        self.assertEqual("released", base["outcome"])
        for field in ("separations", "release_receipt", "changes"):
            value = deepcopy(base)
            value["body"].pop(field)
            self.invalid(value, validate_result)
        for field in ("separations", "changes"):
            value = deepcopy(base)
            value["body"][field] = []
            self.invalid(value, validate_result)
        value = deepcopy(base)
        value["body"]["release_receipt"]["record_type"] = "judgment"
        self.invalid(value, validate_result)
        failure = fixture("results/release_identity_separations__failure_revision_conflict.json")
        self.assertEqual(failure, validate_result(failure))
        failure["outcome"] = "released"
        self.invalid(failure, validate_result)

    def test_private_domains_are_closed_required_and_resolve_with_no_external_fetch(self):
        domains = self.private_domains()
        self.assertEqual(set(PRIVATE_SCHEMAS), set(domains))
        for name, domain in domains.items():
            validator, body = self.private_validator(name), domain["value"]
            with self.subTest(schema=name):
                validator.validate(body)
                self.assertEqual(domain["schema"], {
                    "namespace": "matter", "id": name, "version": "1.0",
                    "digest": hashlib.sha256(self.schema_bytes[name + ".schema.json"]).hexdigest(),
                })
                self.assertFalse(validator.is_valid({**body, "external_action": True}))
            for field in self.schemas[name + ".schema.json"]["required"]:
                with self.subTest(schema=name, missing=field):
                    value = deepcopy(body)
                    value.pop(field)
                    self.assertFalse(validator.is_valid(value))

    def test_decision_manifest_has_closed_typed_group_and_child_shapes(self):
        validator = self.private_validator("identity-decision")
        base = self.private_domains()["identity-decision"]["value"]
        for group_name in ("before", "after"):
            for field in ("survivor", "members", "indexes"):
                value = deepcopy(base)
                value[group_name][0].pop(field)
                self.assertFalse(validator.is_valid(value))
            value = deepcopy(base)
            value[group_name][0]["redirect_chain"] = []
            self.assertFalse(validator.is_valid(value))
        for field in ("reference", "original_matters", "before", "after", "action", "record_action"):
            value = deepcopy(base)
            value["children"][0].pop(field)
            self.assertFalse(validator.is_valid(value))
        for field in ("changes", "basis"):
            value = deepcopy(base)
            value[field] = []
            self.assertFalse(validator.is_valid(value))
        value = deepcopy(base)
        value["authority"].pop("digest")
        self.assertFalse(validator.is_valid(value))
        value = deepcopy(base)
        value["policy_definition"]["capability"] = "attach"
        self.assertFalse(validator.is_valid(value))

    def test_group_and_separation_decisions_are_exact_receipt_pins(self):
        for name in ("identity-group", "identity-separation"):
            base = self.private_domains()[name]["value"]
            validator = self.private_validator(name)
            for change in ("unpinned", "judgment"):
                value = deepcopy(base)
                if change == "unpinned":
                    value["decision"].pop("digest")
                else:
                    value["decision"]["record_type"] = "judgment"
                self.assertFalse(validator.is_valid(value))
        group = self.private_domains()["identity-group"]["value"]
        group["members"].append(deepcopy(group["members"][0]))
        self.assertFalse(self.private_validator("identity-group").is_valid(group))
        separation = self.private_domains()["identity-separation"]["value"]
        separation["status"] = "implicitly_released"
        self.assertFalse(self.private_validator("identity-separation").is_valid(separation))
        separation = self.private_domains()["identity-separation"]["value"]
        separation["members"].pop()
        self.assertFalse(self.private_validator("identity-separation").is_valid(separation))

    def test_separation_release_and_reprotection_keep_exact_prior_revision_refs(self):
        validator = self.private_validator("identity-separation")
        initial = self.private_domains()["identity-separation"]["value"]
        self.assertEqual("protected", initial["status"])
        self.assertIsNone(initial["previous"])
        validator.validate(initial)
        released = fixture("records/receipt__identity_release.json")["extensions"]["example:released-separation"]["value"]
        self.assertEqual("released", released["status"])
        self.assertEqual(1, released["previous"]["revision"])
        validator.validate(released)
        protected_again = deepcopy(released)
        protected_again["status"] = "protected"
        protected_again["previous"]["revision"] = 2
        validator.validate(protected_again)
        for base in (initial, released, protected_again):
            value = deepcopy(base)
            value.pop("previous")
            self.assertFalse(validator.is_valid(value))
        value = deepcopy(released)
        value["previous"].pop("revision")
        self.assertFalse(validator.is_valid(value))
        value = deepcopy(released)
        value["previous"]["record_type"] = "matter"
        self.assertFalse(validator.is_valid(value))

    def test_release_private_manifest_requires_closed_pinned_before_after_steps(self):
        validator = self.private_validator("identity-release")
        base = self.private_domains()["identity-release"]["value"]
        for field in ("separations", "changes", "basis"):
            value = deepcopy(base)
            value[field] = []
            self.assertFalse(validator.is_valid(value))
        for field in ("before", "after", "members", "protected_by"):
            value = deepcopy(base)
            value["separations"][0].pop(field)
            self.assertFalse(validator.is_valid(value))
        value = deepcopy(base)
        value["separations"][0]["after"].pop("revision")
        self.assertFalse(validator.is_valid(value))
        value = deepcopy(base)
        value["separations"][0]["protected_by"].pop("digest")
        self.assertFalse(validator.is_valid(value))
        value = deepcopy(base)
        value["separations"][0]["members"].pop()
        self.assertFalse(validator.is_valid(value))
        value = deepcopy(base)
        value["separations"][0]["merge_members"] = []
        self.assertFalse(validator.is_valid(value))

    def test_registered_derivative_dependencies_and_typed_link_rules_keep_exact_fields(self):
        dependency = self.private_domains()["identity-dependency"]["value"]
        dependency["dependencies"][0].pop("revision")
        self.assertFalse(self.private_validator("identity-dependency").is_valid(dependency))
        dependency = self.private_domains()["identity-dependency"]["value"]
        dependency["original_matters"][0]["revision"] = 1
        self.assertFalse(self.private_validator("identity-dependency").is_valid(dependency))
        link = self.private_domains()["matter-link-index"]["value"]
        validator = self.private_validator("matter-link-index")
        for field in ("kind", "namespace", "id", "version", "directed", "allow_self", "acyclic"):
            value = deepcopy(link)
            value["rule"].pop(field)
            self.assertFalse(validator.is_valid(value))
        value = deepcopy(link)
        value["rule"]["implies_equivalence"] = True
        self.assertFalse(validator.is_valid(value))
        link["relation"]["record_type"] = "accepted_association"
        self.assertFalse(validator.is_valid(link))

    def test_private_projection_domains_do_not_add_core_kinds_or_operation_conclusions(self):
        for path in ("records/receipt__identity_decision.json", "records/receipt__identity_projection_domains.json",
                     "records/receipt__identity_release.json"):
            value = fixture(path)
            self.assertEqual(value, validate_record(value))
            self.assertEqual("receipt", value["record_type"])
        manifest = fixture("manifest.json")["fixtures"]
        records, operations, outcomes = set(), set(), set()
        for item in manifest:
            if not item["valid"]:
                continue
            value = fixture(item["path"])
            if item["schema"] == "record":
                records.add(value["record_type"])
            elif item["schema"] == "command":
                operations.add(value["operation"])
            elif value["status"] == "success":
                outcomes.add((value["operation"], value["outcome"]))
        self.assertEqual((12, 24, 45, 19), (len(records), len(operations), len(outcomes), len(ERROR_CODES)))
        self.assertEqual(set(SUCCESS_OUTCOMES), operations)
        inventory = fixture("inventory.json")
        self.assertEqual(records, set(inventory["record_kinds"]))
        self.assertEqual(operations, set(inventory["operations"]))
        self.assertEqual(outcomes, {(operation, outcome) for operation, values in inventory["success_outcomes"].items()
                                    for outcome in values})
        self.assertEqual(ERROR_CODES, set(inventory["error_codes"]))


if __name__ == "__main__":
    unittest.main()
