"""Portable time/coverage declarations, separate from runtime absence proof.

The standalone examples carry synthetic pins and host declarations. Structural
acceptance does not establish source completeness, permission, eligible absence,
or ownership of derived records that a replacement proposes to retire.
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
from tests.contract.test_operation_contracts import SUCCESS_OUTCOMES, fixture


PRIVATE_SCHEMAS = ("observation-predicate", "source-catalog", "coverage-snapshot", "negative-dependency")


class CoverageContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema_bytes = {
            path.name: path.read_bytes() for path in files("matter._schemas").iterdir()
            if path.name.endswith(".schema.json")
        }
        cls.schemas = {name: json.loads(value) for name, value in cls.schema_bytes.items()}

        def refuse_external(uri):
            raise AssertionError("Contract validation attempted external retrieval: " + uri)

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
        return {key.split(":", 1)[1]: value for key, value in
                fixture("records/receipt__coverage_domains.json")["extensions"].items()}

    def test_new_operations_keep_typed_required_closed_command_bodies(self):
        for operation in ("publish_coverage", "register_negative_watch"):
            base = fixture("commands/" + operation + ".json")
            self.assertEqual(base, validate_command(base))
            value = deepcopy(base)
            value["body"]["assume_absence"] = True
            self.invalid(value)
            for field in ("coverage_policy", "previous", "as_of"):
                value = deepcopy(base)
                value["body"].pop(field)
                self.invalid(value)

    def test_coverage_specification_has_explicit_nonempty_bounded_sources(self):
        base = fixture("commands/publish_coverage.json")
        for size in (0, 65):
            value = deepcopy(base)
            value["body"]["specification"]["eligible_sources"] = [
                {"namespace": "example:source", "value": "source-" + str(number)} for number in range(size)
            ]
            self.invalid(value)
        value = deepcopy(base)
        value["body"]["specification"].pop("observed_interval")
        self.invalid(value)
        value = deepcopy(base)
        value["body"]["specification"]["global_scope"] = True
        self.invalid(value)

    def test_owned_members_are_exact_projection_pins_with_explicit_ownership(self):
        base = fixture("commands/publish_coverage.json")
        for owner in ("machine", "operator", "reviewed", "rejected"):
            value = deepcopy(base)
            value["body"]["members"][0]["ownership"] = owner
            self.assertEqual(value, validate_command(value))
        for mutation in (
            lambda member: member.update(ownership="automatic"),
            lambda member: member["reference"].pop("revision"),
            lambda member: member["reference"].update(record_type="matter"),
            lambda member: member.update(retire=True),
        ):
            value = deepcopy(base)
            mutation(value["body"]["members"][0])
            self.invalid(value)
        value = deepcopy(base)
        reference = value["body"]["members"][0]["reference"]
        reference.pop("revision")
        reference["digest"] = "0" * 64
        self.assertEqual(value, validate_command(value))

    def test_baselines_require_explicit_complete_history_and_immutable_observation_pins(self):
        base = fixture("commands/publish_coverage.json")
        observation = fixture("results/ingest_observation__committed.json")["body"]["observation"]
        value = deepcopy(base)
        value["body"]["source_baselines"][0]["observations"] = [observation]
        self.assertEqual(value, validate_command(value))
        for mutation in (
            lambda baseline: baseline.update(history_complete=False),
            lambda baseline: baseline.pop("history_complete"),
            lambda baseline: baseline["observations"][0].pop("digest"),
            lambda baseline: baseline["observations"][0].update(record_type="receipt"),
        ):
            invalid = deepcopy(value)
            mutation(invalid["body"]["source_baselines"][0])
            self.invalid(invalid)

    def test_catalog_and_member_arrays_have_explicit_refusal_bounds(self):
        base = fixture("commands/publish_coverage.json")
        for field, maximum in (("members", 4096), ("source_baselines", 64)):
            value = deepcopy(base)
            value["body"][field] *= maximum + 1
            self.invalid(value)
        value = deepcopy(base)
        observation = fixture("results/ingest_observation__committed.json")["body"]["observation"]
        value["body"]["source_baselines"][0]["observations"] = [observation] * 4097
        self.invalid(value)

    def test_failed_partial_and_not_expected_inputs_remain_explicit_not_absence(self):
        for status in ("partial", "failed", "not_expected_yet"):
            suffix = status + ("_replacement" if status != "not_expected_yet" else "")
            value = fixture("commands/publish_coverage__" + suffix + ".json")
            self.assertEqual(status, value["body"]["coverage"]["status"])
            self.assertEqual([], value["body"]["source_baselines"][0]["observations"])
            self.assertEqual(value, validate_command(value))
            value["body"]["coverage"].pop("reason")
            self.invalid(value)
        value = fixture("results/publish_coverage__failure_storage_unavailable.json")
        self.assertEqual(value, validate_result(value))
        self.assertNotIn("outcome", value)
        value["outcome"] = "adequate_empty"
        self.invalid(value, validate_result)

    def test_new_knowledge_and_expiry_instants_require_known_valid_utc(self):
        for operation, field in (("publish_coverage", "as_of"), ("register_negative_watch", "as_of"),
                                 ("register_negative_watch", "expires_at")):
            for time in (
                {"state": "unknown", "reason": "not_recorded"},
                {"state": "known", "value": "2026-02-30T00:00:00Z", "precision": "second"},
                {"state": "known", "value": "2026-10-08T00:00:00+00:00", "precision": "second"},
            ):
                value = fixture("commands/" + operation + ".json")
                value["body"][field] = time
                self.invalid(value)

    def test_negative_watch_requires_expiry_or_next_check_but_preserves_both(self):
        base = fixture("commands/register_negative_watch.json")
        value = deepcopy(base)
        value["body"]["next_check_at"] = value["body"].pop("expires_at")
        self.assertEqual(value, validate_command(value))
        value["body"]["expires_at"] = deepcopy(value["body"]["next_check_at"])
        self.assertEqual(value, validate_command(value))
        value["body"].pop("expires_at")
        value["body"].pop("next_check_at")
        self.invalid(value)

    def test_additive_negative_knowledge_boundary_keeps_earlier_assessments_valid(self):
        legacy = fixture("records/assessment.json")
        self.assertEqual(legacy, validate_record(legacy))
        value = fixture("records/assessment__dated_negative_watch.json")
        self.assertEqual(value, validate_record(value))
        value["body"]["dependency_manifest"]["negative"][0].pop("assessed_as_of")
        self.assertEqual(value, validate_record(value))
        value["body"]["dependency_manifest"]["negative"][0]["assessed_as_of"] = {
            "state": "unknown", "reason": "not_recorded",
        }
        self.invalid(value, validate_record)

    def test_private_domains_bind_exact_schema_bytes_and_closed_required_fields(self):
        for name, domain in self.private_domains().items():
            with self.subTest(schema=name):
                self.assertEqual({"namespace": "matter", "id": name, "version": "1.0",
                                  "digest": hashlib.sha256(self.schema_bytes[name + ".schema.json"]).hexdigest()},
                                 domain["schema"])
                validator = self.private_validator(name)
                validator.validate(domain["value"])
                value = deepcopy(domain["value"])
                value["unknown_field"] = True
                self.assertFalse(validator.is_valid(value))
                for field in self.schemas[name + ".schema.json"]["required"]:
                    value = deepcopy(domain["value"])
                    value.pop(field)
                    self.assertFalse(validator.is_valid(value), (name, field))

    def test_predicate_clauses_are_closed_and_preserve_typed_extension_values(self):
        validator = self.private_validator("observation-predicate")
        value = {"record_type": "observation", "clauses": []}
        validator.validate(value)
        for field in ("record_namespace", "source_event_id", "source_revision_id", "origin", "media_type"):
            validator.validate({**value, "clauses": [{"field": field, "equals": "synthetic"}]})
        descriptor = fixture("commands/publish_coverage.json")["body"]["adapter"]
        clause = {"field": "extension", "key": "example:event", "schema": descriptor,
                  "value": {"flag": True, "count": 1, "detail": [None, "synthetic\ntext"]}}
        validator.validate({**value, "clauses": [clause]})
        for invalid in (
            {"field": "content_regex", "equals": "arbitrary program"},
            {"field": "origin", "equals": "source", "execute": True},
            {key: item for key, item in clause.items() if key != "schema"},
            {**clause, "key": "unnamespaced"},
        ):
            self.assertFalse(validator.is_valid({**value, "clauses": [invalid]}))
        self.assertFalse(validator.is_valid({**value, "clauses": [clause] * 65}))

    def test_source_catalog_distinguishes_missing_baseline_from_declared_history(self):
        value = self.private_domains()["source-catalog"]["value"]
        validator = self.private_validator("source-catalog")
        validator.validate(value)
        unknown = deepcopy(value)
        unknown["baseline"] = None
        validator.validate(unknown)
        for field in ("declared_at", "adapter", "authority", "catalog_revision"):
            invalid = deepcopy(value)
            invalid["baseline"].pop(field)
            self.assertFalse(validator.is_valid(invalid))
        value["baseline"]["authority"].pop("digest")
        self.assertFalse(validator.is_valid(value))

    def test_catalog_admission_history_requires_exact_observation_and_positive_revision(self):
        base = self.private_domains()["source-catalog"]["value"]
        observation = fixture("results/ingest_observation__committed.json")["body"]["observation"]
        base["observations"] = [observation]
        base["admissions"] = [{"observation": observation, "catalog_revision": 2}]
        validator = self.private_validator("source-catalog")
        validator.validate(base)
        for mutation in (
            lambda item: item.pop("catalog_revision"),
            lambda item: item.update(catalog_revision=0),
            lambda item: item.update(catalog_revision=True),
            lambda item: item["observation"].pop("digest"),
            lambda item: item.update(retired=True),
        ):
            value = deepcopy(base)
            mutation(value["admissions"][0])
            self.assertFalse(validator.is_valid(value))

    def test_coverage_partitions_retain_typed_observations_and_owned_member_status(self):
        base = self.private_domains()["coverage-snapshot"]["value"]
        validator = self.private_validator("coverage-snapshot")
        for field in ("observations", "matches", "indeterminate", "excluded"):
            value = deepcopy(base)
            value[field] = [deepcopy(value["members"][0]["reference"])]
            self.assertFalse(validator.is_valid(value))
        value = deepcopy(base)
        value["result"] = "absence_is_true"
        self.assertFalse(validator.is_valid(value))
        for field in ("reference", "ownership", "status", "review_required"):
            value = deepcopy(base)
            value["members"][0].pop(field)
            self.assertFalse(validator.is_valid(value))
        value = deepcopy(base)
        value["publication_receipt"]["digest"] = "0" * 64
        self.assertFalse(validator.is_valid(value))

    def test_arrival_invalidation_requires_exact_evidence_and_actual_receipt_role(self):
        value = self.private_domains()["negative-dependency"]["value"]
        validator = self.private_validator("negative-dependency")
        value["status"] = "invalidated"
        observation = fixture("results/ingest_observation__committed.json")["body"]["observation"]
        receipt = fixture("results/ingest_observation__committed.json")["receipt"]
        value["invalidation"] = {"observation": observation, "receipt": receipt, "eligibility": "matched"}
        validator.validate(value)
        value["invalidation"]["eligibility"] = "indeterminate"
        validator.validate(value)
        for field in ("observation", "receipt", "eligibility"):
            invalid = deepcopy(value)
            invalid["invalidation"].pop(field)
            self.assertFalse(validator.is_valid(invalid))
        value["invalidation"]["receipt"]["record_type"] = "judgment"
        self.assertFalse(validator.is_valid(value))

    def test_published_and_registered_results_require_nonempty_typed_changes(self):
        for operation, outcome, field in (("publish_coverage", "published", "coverage"),
                                           ("register_negative_watch", "registered", "registration")):
            base = fixture(f"results/{operation}__{outcome}.json")
            self.assertEqual(base, validate_result(base))
            for mutation in (
                lambda body: body.update(changes=[]),
                lambda body: body[field].pop("revision"),
                lambda body: body["changes"][0].update(cause="absence_proven"),
                lambda body: body["changes"][0].pop("after"),
            ):
                value = deepcopy(base)
                mutation(value["body"])
                self.invalid(value, validate_result)

    def test_ingest_notices_are_additive_only_for_new_committed_observations(self):
        for outcome in ("committed", "duplicate"):
            value = fixture(f"results/ingest_observation__{outcome}.json")
            self.assertEqual(value, validate_result(value))
        value = fixture("results/ingest_observation__coverage_changes.json")
        self.assertEqual(value, validate_result(value))
        value["body"]["changes"] = []
        self.assertEqual(value, validate_result(value))
        value["outcome"] = "duplicate"
        self.invalid(value, validate_result)

    def test_fixture_inventory_adds_two_operations_without_core_kinds_or_error_codes(self):
        inventory = fixture("inventory.json")
        self.assertEqual((12, 24, 45, 19), (len(inventory["record_kinds"]), len(inventory["operations"]),
            sum(len(values) for values in inventory["success_outcomes"].values()), len(inventory["error_codes"])))
        self.assertEqual(set(SUCCESS_OUTCOMES), set(inventory["operations"]))
        self.assertEqual(ERROR_CODES, set(inventory["error_codes"]))
        self.assertEqual({"published"}, SUCCESS_OUTCOMES["publish_coverage"])
        self.assertEqual({"registered"}, SUCCESS_OUTCOMES["register_negative_watch"])


if __name__ == "__main__":
    unittest.main()
