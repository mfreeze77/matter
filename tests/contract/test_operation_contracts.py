"""Operation admission and explicit-failure conformance for MAT-002.

No operation is executed here. Tests cover portable command/result structure
and prevent failed execution from masquerading as a successful conclusion.
"""

from copy import deepcopy
import json
from pathlib import Path
import unittest

from matter.contracts import (
    ContractError,
    ERROR_CODES,
    decode_command,
    decode_result,
    error_result,
    validate_command,
    validate_result,
)


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "contracts"
SUCCESS_OUTCOMES = {
    "ingest_observation": {"committed", "duplicate"},
    "create_matter": {"created", "existing"},
    "propose_association": {"proposal", "no_match", "ambiguous", "insufficient_evidence"},
    "accept_association": {"accepted"},
    "append_claim": {"appended", "duplicate"},
    "relate_evidence": {"appended", "duplicate"},
    "link_matters": {"linked"},
    "merge_matters": {"committed"},
    "correct_merge": {"committed"},
    "record_control": {"applied", "duplicate"},
    "commit_assessment": {"committed"},
    "invalidate_dependents": {"affected", "no_op"},
    "request_transition": {"applied", "already_applied", "held_for_evidence", "held_for_conflict"},
    "prepare_delivery": {"ready", "withheld"},
    "dispatch": {"delivered", "withheld"},
    "assess": {"assessed", "incomplete"},
}
COMMAND_BODY_REQUIRED = {
    "ingest_observation": ("observation",),
    "create_matter": ("matter", "identity_policy"),
    "propose_association": ("subject", "candidates", "matching_rule", "evidence", "assessed_as_of"),
    "accept_association": ("proposal", "candidates", "acceptance_policy"),
    "append_claim": ("claim",),
    "relate_evidence": ("relation",),
    "link_matters": ("from_matter", "to_matter", "relation_kind", "relationship_schema", "basis"),
    "merge_matters": ("survivor", "merged", "equivalence_basis", "merge_policy"),
    "correct_merge": ("merge_receipt", "correction_kind", "partitions", "basis"),
    "record_control": ("control",),
    "commit_assessment": ("assessment",),
    "invalidate_dependents": ("changed_references", "changed_negative_scopes", "cause"),
    "request_transition": (
        "matter", "lifecycle_revision", "profile_edge", "evidence", "assessment", "effective_at",
    ),
    "prepare_delivery": (
        "assessment", "audience", "purpose", "baseline", "control_epoch", "treatment",
        "content_digest", "dependency_manifest_digest", "delivery_key",
    ),
    "dispatch": ("intent", "lease_token", "control_epoch", "delivery_key", "audience", "baseline"),
    "assess": ("matter", "profile", "purpose", "evidence", "assessed_as_of", "budget", "control_epoch"),
}
REQUIRED_ERRORS = {
    "E_SCHEMA_INVALID", "E_VERSION_UNSUPPORTED", "E_SCOPE_FORBIDDEN", "E_NOT_FOUND",
    "E_IDEMPOTENCY_CONFLICT", "E_SOURCE_IDENTITY_CONFLICT", "E_REVISION_CONFLICT",
    "E_ASSOCIATION_CONFLICT", "E_MERGE_CONFLICT", "E_EVIDENCE_INVALID",
    "E_EVIDENCE_UNAVAILABLE", "E_DEPENDENCY_STALE", "E_POLICY_INVALID", "E_RULE_CONFLICT",
    "E_AUTHORITY_REQUIRED", "E_BUDGET_EXHAUSTED", "E_CANCELLED", "E_STORAGE_UNAVAILABLE",
    "E_DELIVERY_UNKNOWN",
}


def fixture(relative):
    return json.loads((FIXTURES / relative).read_text(encoding="utf-8"))


def command(operation):
    return fixture(f"commands/{operation}.json")


def success(operation, outcome):
    return fixture(f"results/{operation}__{outcome}.json")


class OperationContractTests(unittest.TestCase):
    def assert_invalid(self, value, *, kind="result", code="E_SCHEMA_INVALID"):
        validator = validate_command if kind == "command" else validate_result
        before = deepcopy(value)
        with self.assertRaises(ContractError) as error:
            validator(value)
        self.assertEqual(error.exception.code, code)
        self.assertEqual(value, before)

    def test_fixture_inventory_covers_every_operation_and_success_outcome(self):
        commands = {
            json.loads(path.read_text(encoding="utf-8"))["operation"]
            for path in (FIXTURES / "commands").glob("*.json")
        }
        self.assertEqual(commands, set(SUCCESS_OUTCOMES))
        pairs = set()
        for path in (FIXTURES / "results").glob("*.json"):
            value = json.loads(path.read_text(encoding="utf-8"))
            if value["status"] == "success":
                pairs.add((value["operation"], value["outcome"]))
        expected = {(op, outcome) for op, outcomes in SUCCESS_OUTCOMES.items() for outcome in outcomes}
        self.assertEqual(pairs, expected)

    def test_every_command_requires_mutation_identity_authority_and_body(self):
        fields = (
            "schema_version", "operation", "command_id", "idempotency_key", "scope_id",
            "actor", "authority", "expected_revisions", "body",
        )
        for operation in SUCCESS_OUTCOMES:
            for field in fields:
                with self.subTest(operation=operation, missing=field):
                    value = command(operation)
                    del value[field]
                    self.assert_invalid(value, kind="command")
            for field in COMMAND_BODY_REQUIRED[operation]:
                with self.subTest(operation=operation, missing_body_field=field):
                    value = command(operation)
                    del value["body"][field]
                    self.assert_invalid(value, kind="command")

    def test_every_command_and_result_rejects_unsupported_versions(self):
        for operation, outcomes in SUCCESS_OUTCOMES.items():
            for version in ("1.1", "2.0"):
                with self.subTest(operation=operation, version=version):
                    self.assert_invalid(command(operation) | {"schema_version": version},
                                        kind="command", code="E_VERSION_UNSUPPORTED")
                    for outcome in outcomes:
                        self.assert_invalid(success(operation, outcome) | {"schema_version": version},
                                            code="E_VERSION_UNSUPPORTED")

    def test_success_results_require_a_receipt_and_operation_specific_body(self):
        fields = ("schema_version", "operation", "operation_id", "status", "outcome", "receipt", "body")
        for operation, outcomes in SUCCESS_OUTCOMES.items():
            for outcome in outcomes:
                for field in fields:
                    with self.subTest(operation=operation, outcome=outcome, missing=field):
                        value = success(operation, outcome)
                        del value[field]
                        self.assert_invalid(value)
                value = success(operation, outcome)
                value["body"] = {}
                self.assert_invalid(value)

    def test_success_outcomes_are_constrained_by_operation(self):
        all_outcomes = set().union(*SUCCESS_OUTCOMES.values())
        for operation, allowed in SUCCESS_OUTCOMES.items():
            base = success(operation, sorted(allowed)[0])
            for outcome in (all_outcomes - allowed) | {"unknown_operation_outcome"}:
                with self.subTest(operation=operation, incompatible=outcome):
                    self.assert_invalid(base | {"outcome": outcome})

    def test_ingest_results_preserve_both_receipt_roles_and_accept_earlier_bodies(self):
        for outcome in ("committed", "duplicate"):
            with self.subTest(outcome=outcome):
                value = success("ingest_observation", outcome)
                self.assertNotIn("observation_receipt", value["body"])
                self.assertEqual(validate_result(value), value)
                original_receipt = deepcopy(value["receipt"])
                original_receipt["id"] = "original-observation-receipt"
                value["body"]["observation_receipt"] = original_receipt
                self.assertNotEqual(value["receipt"], original_receipt)
                self.assertEqual(validate_result(value), value)
                self.assertEqual(decode_result(json.dumps(value)), value)
                del value["receipt"]
                self.assert_invalid(value)

    def test_ingest_observation_receipt_is_a_closed_typed_bare_reference(self):
        for outcome in ("committed", "duplicate"):
            valid = success("ingest_observation", outcome)
            receipt = deepcopy(valid["receipt"])
            invalid_refs = [None, "receipt-1", {}, deepcopy(valid["body"]["observation"])]
            invalid_refs.extend(
                {**receipt, "record_type": kind}
                for kind in ("observation", "matter", "judgment")
            )
            invalid_refs.extend(
                {key: value for key, value in receipt.items() if key != field}
                for field in ("scope_id", "namespace", "record_type", "id")
            )
            invalid_refs.extend(({**receipt, "digest": "a" * 64}, {**receipt, "revision": 1}))
            for reference in invalid_refs:
                with self.subTest(outcome=outcome, reference=reference):
                    value = deepcopy(valid)
                    value["body"]["observation_receipt"] = reference
                    self.assert_invalid(value)

    def test_observation_receipt_is_not_an_undeclared_field_on_other_results(self):
        value = success("create_matter", "existing")
        value["body"]["observation_receipt"] = deepcopy(value["receipt"])
        self.assert_invalid(value)
        failure = error_result("ingest_observation", "operation-1", "E_SOURCE_IDENTITY_CONFLICT")
        failure["observation_receipt"] = deepcopy(value["receipt"])
        self.assert_invalid(failure)

    def test_new_operation_names_and_unscoped_fields_are_not_silently_accepted(self):
        self.assert_invalid(command("create_matter") | {"operation": "execute_anything"}, kind="command")
        self.assert_invalid(success("create_matter", "created") | {"operation": "execute_anything"})
        for operation in SUCCESS_OUTCOMES:
            value = command(operation)
            value["body"]["external_action"] = "synthetic"
            self.assert_invalid(value, kind="command")

    def test_host_committed_record_fields_are_not_accepted_as_creation_input(self):
        for operation, field in (
            ("ingest_observation", "observation"), ("create_matter", "matter"),
            ("append_claim", "claim"), ("relate_evidence", "relation"),
            ("record_control", "control"), ("commit_assessment", "assessment"),
        ):
            with self.subTest(operation=operation):
                value = command(operation)
                self.assertEqual(validate_command(value), value)
                value["body"][field]["creation_receipt"] = deepcopy(value["authority"])
                self.assert_invalid(value, kind="command")
                value = command(operation)
                value["body"][field]["revision"] = 1
                self.assert_invalid(value, kind="command")

    def test_revision_read_sets_and_authority_references_are_typed(self):
        value = command("accept_association")
        del value["expected_revisions"][0]["revision"]
        self.assert_invalid(value, kind="command")
        value = command("accept_association")
        value["expected_revisions"][0]["digest"] = "a" * 64
        self.assert_invalid(value, kind="command")
        value = command("accept_association")
        value["authority"]["record_type"] = "judgment"
        self.assert_invalid(value, kind="command")

    def test_association_candidate_references_cannot_be_judgments(self):
        wrong = fixture("records/assessment.json")["body"]["judgments"][0]
        value = command("accept_association")
        value["body"]["candidates"][0] = deepcopy(wrong)
        self.assert_invalid(value, kind="command")
        value = success("propose_association", "ambiguous")
        value["body"]["candidates"][0] = deepcopy(wrong)
        self.assert_invalid(value)
        value = success("propose_association", "no_match")
        value["body"]["candidates"] = [deepcopy(wrong)]
        self.assert_invalid(value)

    def test_budget_cost_ceiling_rejects_negative_values_and_terminal_newlines(self):
        for cost in ("-1.00", "-0.0", "0.00\n"):
            with self.subTest(cost=cost):
                value = command("assess")
                value["body"]["budget"]["max_cost"] = cost
                self.assert_invalid(value, kind="command")

    def test_record_control_input_requires_host_provenance(self):
        for origin in ("source", "evaluator"):
            with self.subTest(origin=origin):
                value = command("record_control")
                value["body"]["control"]["provenance"]["origin"] = origin
                self.assert_invalid(value, kind="command")

    def test_all_required_error_codes_have_typed_failure_envelopes(self):
        self.assertEqual(ERROR_CODES, REQUIRED_ERRORS)
        for code in sorted(REQUIRED_ERRORS):
            with self.subTest(code=code):
                operation = "dispatch" if code == "E_DELIVERY_UNKNOWN" else "propose_association"
                value = error_result(operation, "operation-1", code,
                                     retriable=code == "E_STORAGE_UNAVAILABLE")
                self.assertEqual(validate_result(value), value)
                self.assertEqual(value["status"], "failure")
                self.assertEqual(value["error"]["code"], code)
                self.assertIsInstance(value["error"]["retriable"], bool)
                self.assertEqual(value["error"]["affected_references"], [])
                self.assertTrue(value["error"]["detail"])
                self.assertFalse({"outcome", "body", "receipt"} & value.keys())

    def test_failure_envelopes_require_the_full_safe_error_contract(self):
        value = error_result("ingest_observation", "operation-1", "E_STORAGE_UNAVAILABLE", retriable=True)
        for field in ("code", "operation_id", "retriable", "affected_references", "detail"):
            with self.subTest(missing_error_field=field):
                invalid = deepcopy(value)
                del invalid["error"][field]
                self.assert_invalid(invalid)
        for field in ("schema_version", "operation", "operation_id", "status", "error"):
            with self.subTest(missing_failure_envelope=field):
                invalid = deepcopy(value)
                del invalid[field]
                self.assert_invalid(invalid)
        for retriable in ("true", "false", 0, 1, None):
            invalid = deepcopy(value)
            invalid["error"]["retriable"] = retriable
            self.assert_invalid(invalid)
        invalid = deepcopy(value)
        invalid["error"]["code"] = "E_NOTHING_FOUND"
        self.assert_invalid(invalid)
        invalid = deepcopy(value)
        invalid["error"]["operation_id"] = "some-other-operation"
        self.assert_invalid(invalid)

    def test_errors_and_success_conclusions_cannot_share_an_envelope(self):
        for code in ("E_STORAGE_UNAVAILABLE", "E_SCOPE_FORBIDDEN", "E_EVIDENCE_UNAVAILABLE"):
            failure = error_result("propose_association", "operation-1", code)
            no_match = success("propose_association", "no_match")
            for forbidden in ("outcome", "receipt", "body"):
                with self.subTest(code=code, forbidden_success_field=forbidden):
                    self.assert_invalid(failure | {forbidden: deepcopy(no_match[forbidden])})
            self.assert_invalid(no_match | {"error": failure["error"]})
            self.assert_invalid(no_match | {"status": "failure", "error": failure["error"]})
            self.assert_invalid(failure | {"status": "success"})

    def test_no_match_requires_adequate_coverage_and_cannot_conceal_failed_execution(self):
        for state in ("partial", "failed", "unavailable", "not_expected_yet", "unknown"):
            with self.subTest(coverage=state):
                value = success("propose_association", "no_match")
                value["body"]["coverage"]["status"] = state
                value["body"]["coverage"]["reason"] = "Synthetic incomplete collection."
                self.assert_invalid(value)
        for forbidden, content in (("execution_status", "failed"), ("error", {"code": "E_STORAGE_UNAVAILABLE"})):
            value = success("propose_association", "no_match")
            value["body"][forbidden] = content
            self.assert_invalid(value)
        value = success("propose_association", "no_match")
        value["body"]["selected"] = [deepcopy(value["body"]["evidence"][0])]
        self.assert_invalid(value)

    def test_ambiguity_and_insufficient_evidence_are_explicit_success_results(self):
        for outcome in ("ambiguous", "insufficient_evidence", "no_match"):
            value = success("propose_association", outcome)
            self.assertEqual(validate_result(value), value)
            self.assertEqual(value["status"], "success")
            self.assertNotIn("error", value)
        value = success("propose_association", "ambiguous")
        value["body"]["candidates"] = value["body"]["candidates"][:1]
        self.assert_invalid(value)

    def test_delivery_uncertainty_is_a_failure_and_does_not_claim_consumption(self):
        unknown = error_result("dispatch", "operation-1", "E_DELIVERY_UNKNOWN")
        self.assertEqual(unknown["status"], "failure")
        self.assertNotIn("outcome", unknown)
        delivered = success("dispatch", "delivered")
        for outcome in ("consumed", "acted_on", "useful", "verified"):
            self.assert_invalid(delivered | {"outcome": outcome})

    def test_result_and_command_copies_do_not_mutate_callers(self):
        value = command("create_matter")
        before = deepcopy(value)
        output = validate_command(value)
        output["body"]["matter"]["body"].clear()
        self.assertEqual(value, before)
        value = success("create_matter", "created")
        before = deepcopy(value)
        output = validate_result(value)
        output["body"]["matter"].clear()
        self.assertEqual(value, before)
        references = [deepcopy(command("accept_association")["authority"])]
        output = error_result("accept_association", "operation-1", "E_AUTHORITY_REQUIRED",
                              affected_references=references)
        output["error"]["affected_references"][0]["id"] = "changed"
        self.assertEqual(references[0]["id"], "authority-1")

    def test_strict_decoders_reject_duplicate_keys_before_schema_interpretation(self):
        cases = (
            (decode_command, command("create_matter")),
            (decode_result, success("propose_association", "no_match")),
        )
        for decoder, value in cases:
            with self.subTest(decoder=decoder.__name__):
                source = json.dumps(value)
                self.assertEqual(decoder(source.encode("utf-8")), value)
                source = source.replace('"schema_version": "1.0"',
                                        '"schema_version": "2.0", "schema_version": "1.0"', 1)
                with self.assertRaises(ContractError) as error:
                    decoder(source)
                self.assertEqual(error.exception.code, "E_SCHEMA_INVALID")


if __name__ == "__main__":
    unittest.main()
