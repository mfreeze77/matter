"""Behavioral admission checks for MAT-002's neutral record contracts.

These tests establish wire structure, never persisted identity, authenticated
authority, live evidence availability, or evaluator qualification quality.
"""

from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from matter.contracts import (
    ContractError,
    decode_record,
    schema_for,
    validate_command,
    validate_record,
    validate_result,
)


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "contracts"
RECORD_KINDS = {
    "observation", "occurrence", "matter", "claim", "evidence_relation",
    "association_proposal", "accepted_association", "matter_relation",
    "judgment", "assessment", "control", "receipt",
}
MUTABLE_KINDS = {
    "occurrence", "matter", "evidence_relation", "accepted_association",
    "matter_relation",
}
COMMON_REQUIRED = (
    "schema_version", "record_type", "scope_id", "namespace", "id",
    "creation_receipt", "provenance", "body",
)
# Explicit conformance expectations, deliberately not read from the schemas.
BODY_REQUIRED = {
    "observation": (
        "source_identity", "content", "occurred_at", "source_published_at",
        "available_at", "ingested_at", "extraction",
    ),
    "occurrence": (
        "kind", "identity_keys", "observations", "occurred_at", "provenance_groups",
    ),
    "matter": ("domain_kind", "identity_keys"),
    "claim": (
        "subject", "predicate", "value", "qualifiers", "applicability",
        "attribution", "proposition_version",
    ),
    "evidence_relation": (
        "claim", "evidence", "relation", "target", "locator", "applicability",
        "acceptance",
    ),
    "association_proposal": (
        "subject", "outcome", "candidates", "selected", "matching_rule",
        "evidence", "evaluator_receipt", "uncertainty", "qualification",
    ),
    "accepted_association": ("proposal", "members", "relation", "status", "authority"),
    "matter_relation": (
        "from_matter", "to_matter", "relation_kind", "relationship_schema",
        "basis", "authority", "status",
    ),
    "judgment": (
        "rule", "input_digest", "input_artifact", "evaluator", "execution_status", "evaluation_status",
        "semantic_output", "qualification", "used_evidence", "limitations",
        "dependency_manifest", "attempt_receipts", "proposed_consequences", "raw_result",
        "execution_interval",
    ),
    "assessment": (
        "matter", "profile", "purpose", "assessed_as_of", "dependency_manifest",
        "judgments", "propositions", "causes", "evaluation_state", "proposals",
        "limitations", "input_artifact", "evidence_selection", "resource_use", "stop_reason",
        "consequences", "material_changes", "evidence_gaps",
    ),
    "control": (
        "control_kind", "actor", "authority", "scope", "control_epoch",
        "effective_from", "effective_until", "effect",
    ),
    "receipt": ("stage", "operation_id", "recorded_at", "outcome", "evidence", "details"),
}


def fixture(relative):
    return json.loads((FIXTURES / relative).read_text(encoding="utf-8"))


def record(kind):
    return fixture(f"records/{kind}.json")


class CoreSchemaTests(unittest.TestCase):
    def assert_invalid(self, value, code="E_SCHEMA_INVALID"):
        before = deepcopy(value)
        with self.assertRaises(ContractError) as error:
            validate_record(value)
        self.assertEqual(error.exception.code, code)
        self.assertEqual(value, before, "Rejected input must not be mutated.")

    def test_standalone_vectors_cover_every_declared_record_kind(self):
        entries = fixture("manifest.json")["fixtures"]
        kinds = set()
        for entry in entries:
            if entry["schema"] == "record" and entry["valid"]:
                value = fixture(entry["path"])
                with self.subTest(vector=entry["path"]):
                    self.assertEqual(validate_record(value), value)
                kinds.add(value["record_type"])
        self.assertEqual(kinds, RECORD_KINDS)

    def test_all_published_positive_and_negative_vectors_match_their_contracts(self):
        validators = {
            "record": validate_record, "command": validate_command, "result": validate_result,
        }
        for entry in fixture("manifest.json")["fixtures"]:
            with self.subTest(vector=entry["path"]):
                value = fixture(entry["path"])
                if entry["valid"]:
                    self.assertEqual(validators[entry["schema"]](value), value)
                else:
                    with self.assertRaises(ContractError):
                        validators[entry["schema"]](value)

    def test_raw_schema_vectors_resolve_cross_references_without_network(self):
        schemas = {kind: schema_for(kind) for kind in ("record", "command", "result")}

        def refuse_retrieval(uri):
            self.fail(f"An unregistered schema was requested: {uri}")

        registry = Registry(retrieve=refuse_retrieval).with_resources(
            (value["$id"], Resource.from_contents(value)) for value in schemas.values()
        )
        validators = {}
        for kind, schema in schemas.items():
            Draft202012Validator.check_schema(schema)
            validators[kind] = Draft202012Validator(schema, registry=registry)
        with patch("socket.create_connection", side_effect=AssertionError("Network access")):
            for entry in fixture("manifest.json")["fixtures"]:
                with self.subTest(vector=entry["path"]):
                    valid = validators[entry["schema"]].is_valid(fixture(entry["path"]))
                    self.assertEqual(valid, entry["valid"])

    def test_every_record_requires_its_common_envelope_and_kind_specific_fields(self):
        for kind in sorted(RECORD_KINDS):
            for field in COMMON_REQUIRED:
                with self.subTest(kind=kind, missing=field):
                    value = record(kind)
                    del value[field]
                    self.assert_invalid(value)
            for field in BODY_REQUIRED[kind]:
                with self.subTest(kind=kind, missing_body_field=field):
                    value = record(kind)
                    del value["body"][field]
                    self.assert_invalid(value)

    def test_every_record_rejects_unsupported_versions_and_unknown_fields(self):
        for kind in sorted(RECORD_KINDS):
            for version in ("0.9", "1.1", "2.0"):
                with self.subTest(kind=kind, version=version):
                    self.assert_invalid(record(kind) | {"schema_version": version},
                                        "E_VERSION_UNSUPPORTED")
            for location in ("envelope", "body"):
                with self.subTest(kind=kind, unknown_field=location):
                    value = record(kind)
                    target = value if location == "envelope" else value["body"]
                    target["undeclared_domain_field"] = "synthetic"
                    self.assert_invalid(value)
        self.assert_invalid(record("matter") | {"record_type": "new_record_kind"})

    def test_only_mutable_records_have_positive_integer_revisions(self):
        for kind in sorted(RECORD_KINDS):
            value = record(kind)
            if kind in MUTABLE_KINDS:
                del value["revision"]
                self.assert_invalid(value)
                for revision in (0, -1, True, False, 1.0, "1", 2**53):
                    with self.subTest(kind=kind, revision=repr(revision)):
                        self.assert_invalid(record(kind) | {"revision": revision})
            else:
                with self.subTest(immutable_kind=kind):
                    self.assert_invalid(value | {"revision": 1})

    def test_references_require_scope_namespace_kind_and_identity(self):
        for field in ("scope_id", "namespace", "record_type", "id"):
            value = record("observation")
            del value["creation_receipt"][field]
            with self.subTest(missing_reference_field=field):
                self.assert_invalid(value)
        value = record("observation")
        value["creation_receipt"]["record_type"] = "observation"
        self.assert_invalid(value)

    def test_dependency_pins_require_exactly_one_revision_or_immutable_digest(self):
        value = record("assessment")
        dependency = value["body"]["dependency_manifest"]["positive"][0]
        del dependency["digest"]
        self.assert_invalid(value)
        value = record("assessment")
        value["body"]["dependency_manifest"]["positive"][0]["revision"] = 1
        self.assert_invalid(value)
        value = record("assessment")
        del value["body"]["matter"]["revision"]
        self.assert_invalid(value)
        value["body"]["matter"]["digest"] = "a" * 64
        self.assertEqual(validate_record(value), value)
        value["body"]["matter"]["record_type"] = "observation"
        self.assert_invalid(value)

    def test_immutable_dependencies_cannot_use_mutable_revision_pins(self):
        for kind in ("observation", "claim", "judgment", "assessment", "receipt", "control"):
            with self.subTest(immutable_kind=kind):
                value = record("assessment")
                dependency = value["body"]["dependency_manifest"]["positive"][0]
                dependency["record_type"] = kind
                del dependency["digest"]
                dependency["revision"] = 1
                self.assert_invalid(value)

    def test_derived_sources_require_parent_provenance(self):
        value = record("observation")
        value["provenance"]["origin"] = "derived"
        self.assert_invalid(value)
        value["provenance"]["parents"] = deepcopy(
            record("assessment")["body"]["dependency_manifest"]["positive"]
        )
        self.assertEqual(validate_record(value), value)

    def test_observation_content_and_source_identity_cannot_be_invented_by_defaults(self):
        for field in ("digest", "locator", "media_type", "availability"):
            with self.subTest(missing_content=field):
                value = record("observation")
                del value["body"]["content"][field]
                self.assert_invalid(value)
        for field in ("namespace", "event_id"):
            with self.subTest(missing_source_identity=field):
                value = record("observation")
                del value["body"]["source_identity"][field]
                self.assert_invalid(value)

    def test_available_content_cannot_have_an_unavailable_locator(self):
        value = record("observation")
        value["body"]["content"]["locator"] = {
            "kind": "unavailable", "reason": "No original source is available.",
        }
        self.assert_invalid(value)

    def test_host_controls_cannot_claim_source_or_evaluator_provenance(self):
        for origin in ("source", "evaluator", "derived", "adapter", "system"):
            with self.subTest(origin=origin):
                value = record("control")
                value["provenance"]["origin"] = origin
                self.assert_invalid(value)

    def test_unknown_event_time_remains_unknown_after_validation_and_decoding(self):
        value = record("observation_unknown_time")
        unknown = {"state": "unknown", "reason": "not_reported"}
        for output in (validate_record(value), decode_record(json.dumps(value)),
                       decode_record(json.dumps(value).encode("utf-8"))):
            self.assertEqual(output["body"]["occurred_at"], unknown)
            self.assertNotIn("value", output["body"]["occurred_at"])
            self.assertEqual(output["body"]["ingested_at"], value["body"]["ingested_at"])

    def test_unknown_time_requires_reason_and_forbids_timestamp_or_precision(self):
        for reason in ("not_reported", "not_observed", "source_unavailable",
                       "conflicting_evidence", "not_applicable"):
            value = record("observation")
            value["body"]["occurred_at"] = {"state": "unknown", "reason": reason}
            self.assertEqual(validate_record(value), value)
        for timestamp in (
            {"state": "unknown"},
            {"state": "unknown", "reason": "guessed"},
            {"state": "unknown", "reason": "not_reported", "value": "2026-10-08T15:00:00Z"},
            {"state": "unknown", "reason": "not_reported", "precision": "second"},
        ):
            with self.subTest(timestamp=timestamp):
                value = record("observation")
                value["body"]["occurred_at"] = timestamp
                self.assert_invalid(value)

    def test_known_time_preserves_declared_fractional_precision(self):
        for precision, fraction in (("second", ""), ("millisecond", ".123"),
                                    ("microsecond", ".123456"), ("nanosecond", ".123456789")):
            with self.subTest(precision=precision):
                value = record("observation")
                value["body"]["occurred_at"] = {
                    "state": "known", "value": f"2026-10-08T15:00:00{fraction}Z",
                    "precision": precision,
                }
                self.assertEqual(validate_record(value), value)

    def test_calendar_errors_non_utc_forms_and_precision_mismatches_are_rejected(self):
        invalid_times = (
            "2026-02-29T15:00:00Z", "2026-04-31T15:00:00Z", "0000-01-01T00:00:00Z",
            "2026-10-08T25:00:00Z", "2026-10-08T15:00:00+00:00", "2026-10-08T15:00:00",
            "2026-10-08t15:00:00z", "2026-10-08T15:00:00.123Z",
        )
        for timestamp in invalid_times:
            with self.subTest(timestamp=timestamp):
                value = record("observation")
                value["body"]["occurred_at"]["value"] = timestamp
                self.assert_invalid(value)

    def test_event_instant_and_interval_are_alternatives(self):
        value = record("observation")
        value["body"]["occurred_interval"] = deepcopy(record("claim")["body"]["applicability"])
        self.assert_invalid(value)
        del value["body"]["occurred_at"]
        self.assertEqual(validate_record(value), value)

    def test_accepted_evidence_requires_authority_and_component_locators_are_explicit(self):
        value = record("evidence_relation")
        del value["body"]["acceptance"]["authority"]
        self.assert_invalid(value)
        value["body"]["acceptance"]["status"] = "proposed"
        self.assertEqual(validate_record(value), value)
        value = record("evidence_relation")
        value["body"]["target"] = {"kind": "component"}
        self.assert_invalid(value)
        value["body"]["target"]["component"] = "example:component-a"
        self.assertEqual(validate_record(value), value)
        value["body"]["locator"]["kind"] = "selected_span"
        self.assert_invalid(value)

    def test_proposal_outcomes_do_not_erase_candidate_ambiguity(self):
        value = record("association_proposal")
        value["body"]["selected"] = []
        self.assert_invalid(value)
        value["body"]["outcome"] = "ambiguous"
        self.assert_invalid(value)
        other = deepcopy(value["body"]["candidates"][0])
        other["candidate"]["id"] = "matter-2"
        value["body"]["candidates"].append(other)
        self.assertEqual(validate_record(value), value)
        value["body"]["selected"] = [deepcopy(other["candidate"])]
        self.assert_invalid(value)

    def test_association_members_cannot_be_arbitrary_core_record_kinds(self):
        wrong_member = deepcopy(record("assessment")["body"]["judgments"][0])
        for field in ("subject", "candidate", "selected"):
            value = record("association_proposal")
            if field == "candidate":
                value["body"]["candidates"][0]["candidate"] = deepcopy(wrong_member)
            elif field == "selected":
                value["body"]["selected"] = [deepcopy(wrong_member)]
            else:
                value["body"]["subject"] = deepcopy(wrong_member)
            with self.subTest(field=field):
                self.assert_invalid(value)
        value = record("accepted_association")
        value["body"]["members"][0] = wrong_member
        self.assert_invalid(value)

    def test_qualification_requires_exact_certificate_and_never_defaults_from_confidence(self):
        value = record("judgment_qualified")
        certificate = value["body"]["qualification"].pop("certificate")
        self.assert_invalid(value)
        value["body"]["qualification"]["confidence"] = "1.0"
        self.assert_invalid(value)
        for field in ("namespace", "id", "version", "digest"):
            with self.subTest(missing_certificate_field=field):
                value = record("judgment_qualified")
                del value["body"]["qualification"]["certificate"][field]
                self.assert_invalid(value)
        value = record("judgment")
        value["body"]["qualification"]["certificate"] = certificate
        self.assert_invalid(value)

    def test_incomplete_execution_cannot_claim_semantic_success_or_consequences(self):
        completed = record("judgment")["body"]
        for status in ("failed", "cancelled", "timed_out", "budget_exhausted"):
            value = record("judgment_failed")
            value["body"]["execution_status"] = status
            value["body"]["failure"]["reason"] = status
            self.assertEqual(validate_record(value), value)
            for field in ("evaluation_status", "semantic_output"):
                with self.subTest(execution=status, forbidden=field):
                    invalid = deepcopy(value)
                    invalid["body"][field] = deepcopy(completed[field])
                    self.assert_invalid(invalid)
            invalid = deepcopy(value)
            invalid["body"]["proposed_consequences"] = [deepcopy(completed["semantic_output"])]
            self.assert_invalid(invalid)
            invalid = deepcopy(value)
            invalid["body"]["qualification"] = record("judgment_qualified")["body"]["qualification"]
            self.assert_invalid(invalid)

    def test_completed_unknown_and_inapplicable_results_remain_evaluation_results(self):
        value = record("judgment_unknown")
        output = validate_record(value)
        self.assertEqual(output["body"]["execution_status"], "completed")
        self.assertEqual(output["body"]["semantic_output"]["value"]["status"], "unknown")
        self.assertNotIn("failure", output["body"])
        value["body"]["evaluation_status"] = "not_applicable"
        value["body"]["semantic_output"]["value"] = {"status": "not_applicable"}
        self.assertEqual(validate_record(value), value)
        assessment = validate_record(record("assessment"))
        self.assertEqual(assessment["body"]["propositions"][0]["status"], "unknown")

    def test_namespaced_extensions_preserve_typed_domain_payloads(self):
        extension = deepcopy(record("claim")["body"]["value"])
        extension["value"] = {"probability": "0.125", "labels": ["a", "b"]}
        value = record("matter")
        value["extensions"] = {"example:custom": extension}
        self.assertEqual(validate_record(value), value)
        value["extensions"] = {"custom": extension}
        self.assert_invalid(value)
        value["extensions"] = {"example:custom": {"value": "no declared schema"}}
        self.assert_invalid(value)

    def test_terminal_newlines_do_not_bypass_identifier_namespace_and_digest_patterns(self):
        for field in ("id", "namespace"):
            value = record("observation")
            value[field] += "\n"
            with self.subTest(field=field):
                self.assert_invalid(value)
        value = record("observation")
        value["body"]["content"]["digest"] += "\n"
        self.assert_invalid(value)
        value = record("matter")
        value["body"]["domain_kind"] += "\n"
        self.assert_invalid(value)

    def test_validation_and_schema_access_do_not_expose_shared_mutable_state(self):
        for kind in sorted(RECORD_KINDS):
            value = record(kind)
            before = deepcopy(value)
            result = validate_record(value)
            result["body"].clear()
            result["provenance"]["producer"].clear()
            self.assertEqual(value, before)
        exposed = schema_for("record")
        exposed["$defs"].clear()
        self.assertTrue(schema_for("record")["$defs"])
        self.assertEqual(validate_record(record("matter")), record("matter"))

    def test_decode_rejects_duplicate_keys_before_losing_the_original_token_stream(self):
        source = json.dumps(record("matter"))
        source = source.replace('"schema_version": "1.0"',
                                '"schema_version": "2.0", "schema_version": "1.0"', 1)
        with self.assertRaises(ContractError) as error:
            decode_record(source)
        self.assertEqual(error.exception.code, "E_SCHEMA_INVALID")

    def test_validation_errors_do_not_echo_rejected_source_content(self):
        secret = "synthetic-secret-that-must-not-be-reflected"
        value = record("matter")
        value["undeclared"] = secret
        with self.assertRaises(ContractError) as error:
            validate_record(value)
        self.assertNotIn(secret, str(error.exception))
        self.assertNotIn(secret, error.exception.detail)
        self.assertEqual(error.exception.code, "E_SCHEMA_INVALID")


if __name__ == "__main__":
    unittest.main()
