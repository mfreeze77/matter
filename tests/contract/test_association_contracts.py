"""Portable association wire admission, independent of service authorization."""

from copy import deepcopy
from importlib.resources import files
import json
import unittest

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from matter.contracts import (
    ContractError, _FORMAT_CHECKER, validate_command, validate_record, validate_result,
)
from tests.contract.test_operation_contracts import fixture


class AssociationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schemas = {
            path.name: json.loads(path.read_text(encoding="utf-8"))
            for path in files("matter._schemas").iterdir()
            if path.name.endswith(".schema.json")
        }
        cls.registry = Registry().with_resources(
            (schema["$id"], Resource.from_contents(schema))
            for schema in cls.schemas.values()
        )
        for name in (
            "candidate-set", "association-evaluation", "association-decision",
            "association-disposition", "association-membership",
        ):
            Draft202012Validator.check_schema(cls.schemas[name + ".schema.json"])

    def invalid(self, value, validator=validate_command):
        with self.assertRaises(ContractError) as error:
            validator(value)
        self.assertEqual(error.exception.code, "E_SCHEMA_INVALID")

    def private_validator(self, name):
        return Draft202012Validator(
            self.schemas[name + ".schema.json"], registry=self.registry,
            format_checker=_FORMAT_CHECKER,
        )

    def private_values(self):
        publish = fixture("commands/publish_association_candidates.json")
        proposed = fixture("commands/propose_association__catalog.json")
        decide = fixture("commands/decide_association.json")
        applied = fixture("results/decide_association__applied.json")
        accepted = fixture("records/accepted_association__decision.json")
        p, d = publish["body"], decide["body"]
        bare = lambda pin: {k: v for k, v in pin.items() if k not in ("revision", "digest")}
        catalog = {
            "scope_id": publish["scope_id"], "query": p["query"],
            "subject": proposed["body"]["subject"], "entries": p["entries"],
            "coverage": p["coverage"], "evidence": p["evidence"], "as_of": p["as_of"],
            "policy": d["acceptance_policy"], "authority": publish["authority"],
        }
        evaluation = {
            "scope_id": proposed["scope_id"], **proposed["body"], "mode": "exact_keys",
            "coverage": p["coverage"], "outcome": "matched",
            "selected": proposed["body"]["evaluation"]["selected"],
        }
        common = {
            "scope_id": decide["scope_id"], "subject": bare(d["subject"]),
            "target": bare(d["target"]), "relation": d["relation"], "capability": d["capability"],
        }
        decision = {
            **common, "decision": d["decision"], "reason": d["reason"],
            "authority": decide["authority"], "policy": d["acceptance_policy"],
            "previous": None, "proposal": None, "as_of": d["as_of"],
        }
        disposition = {
            **common, "status": "blocked", "kind": d["decision"], "reason": d["reason"],
            "authority": decide["authority"], "policy": d["acceptance_policy"],
            "decision": applied["body"]["decision"], "previous": None, "as_of": d["as_of"],
        }
        association = fixture("results/accept_association__accepted.json")["body"]["association"]
        membership = {**common, "association": association}
        return {
            "candidate-set": catalog, "association-evaluation": evaluation,
            "association-decision": decision, "association-disposition": disposition,
            "association-membership": membership,
        }

    def test_catalog_query_modes_have_distinct_key_requirements(self):
        exact = fixture("commands/publish_association_candidates.json")
        semantic = fixture("commands/publish_association_candidates__semantic.json")
        for value in (exact, semantic):
            self.assertEqual(validate_command(value), value)
        value = deepcopy(exact)
        del value["body"]["query"]["keys"]
        self.invalid(value)
        value["body"]["query"]["keys"] = []
        self.invalid(value)
        value = deepcopy(semantic)
        value["body"]["query"]["keys"] = []
        self.assertEqual(validate_command(value), value)
        value["body"]["query"]["keys"] = exact["body"]["query"]["keys"]
        self.invalid(value)
        for change in ({"revision": 1}, {"record_type": "claim"}):
            value = deepcopy(exact)
            value["body"]["query"]["subject"].update(change)
            self.invalid(value)

    def test_candidate_entries_keep_keys_and_evidence_typed_without_authority(self):
        base = fixture("commands/publish_association_candidates.json")
        for field in ("candidate", "keys", "basis"):
            value = deepcopy(base)
            del value["body"]["entries"][0][field]
            self.invalid(value)
        for field, content in (("authority", base["authority"]), ("score", 1)):
            value = deepcopy(base)
            value["body"]["entries"][0][field] = content
            self.invalid(value)
        value = deepcopy(base)
        value["body"]["entries"][0]["candidate"]["record_type"] = "receipt"
        self.invalid(value)
        value = deepcopy(base)
        del value["body"]["entries"][0]["basis"][0]["digest"]
        self.invalid(value)

    def test_frozen_evaluation_outcomes_and_selection_remain_distinct(self):
        base = fixture("commands/propose_association__catalog.json")
        for outcome in ("no_match", "ambiguous", "insufficient_evidence", "evaluation_failed"):
            value = deepcopy(base)
            evaluation = value["body"]["evaluation"]
            evaluation.update({"outcome": outcome, "selected": []})
            if outcome == "insufficient_evidence":
                evaluation["missing_evidence"] = ["Synthetic missing key evidence."]
            self.assertEqual(validate_command(value), value)
            evaluation["selected"] = base["body"]["evaluation"]["selected"]
            self.invalid(value)
        value = deepcopy(base)
        value["body"]["evaluation"]["selected"] = []
        self.invalid(value)
        value = deepcopy(base)
        value["body"]["evaluation"]["authority"] = base["authority"]
        self.invalid(value)
        value = deepcopy(base)
        value["body"]["evaluation"]["qualification"] = {"status": "qualified"}
        self.invalid(value)

    def test_old_shapes_remain_valid_while_optional_dependencies_are_typed(self):
        for path, validator in (
            ("commands/propose_association.json", validate_command),
            ("commands/accept_association.json", validate_command),
            ("records/association_proposal.json", validate_record),
            ("records/accepted_association.json", validate_record),
        ):
            value = fixture(path)
            self.assertEqual(validator(value), value)
        for path, validator in (
            ("commands/propose_association__catalog.json", validate_command),
            ("commands/accept_association__catalog.json", validate_command),
            ("records/association_proposal__catalog.json", validate_record),
            ("records/accepted_association__decision.json", validate_record),
        ):
            base = fixture(path)
            self.assertEqual(validator(base), base)
            for field, content in (("record_type", "matter"), ("revision", None)):
                value = deepcopy(base)
                value["body"]["candidate_set"][field] = content
                self.invalid(value, validator)
        for path, field in (("records/association_proposal__catalog.json", "evaluation"),
                            ("records/accepted_association__decision.json", "decision")):
            value = fixture(path)
            value["body"][field].pop("digest")
            self.invalid(value, validate_record)

    def test_all_semantic_outcomes_can_retain_proposal_and_catalog(self):
        for outcome in ("proposal", "no_match", "ambiguous", "insufficient_evidence", "evaluation_failed"):
            suffix = "" if outcome == "evaluation_failed" else "__catalog"
            value = fixture(f"results/propose_association__{outcome}{suffix}.json")
            self.assertEqual(validate_result(value), value)
            self.assertEqual(value["status"], "success")
            self.assertNotIn("error", value)
            self.assertIn("proposal", value["body"])
            self.assertIn("candidate_set", value["body"])
        value = fixture("results/propose_association__evaluation_failed.json")
        for field in ("proposal", "candidate_set", "reason"):
            invalid = deepcopy(value)
            del invalid["body"][field]
            self.invalid(invalid, validate_result)
        value["body"]["selected"] = []
        self.invalid(value, validate_result)

    def test_publication_and_disposition_results_pin_revisions_and_changes(self):
        for operation, field, changed in (
            ("publish_association_candidates", "candidate_set", "published"),
            ("decide_association", "disposition", "applied"),
        ):
            for outcome in (changed, "unchanged"):
                base = fixture(f"results/{operation}__{outcome}.json")
                self.assertEqual(validate_result(base), base)
                value = deepcopy(base)
                del value["body"][field]["revision"]
                self.invalid(value, validate_result)
            value = fixture(f"results/{operation}__{changed}.json")
            value["body"]["changes"] = []
            self.invalid(value, validate_result)

    def test_merge_can_be_refused_without_being_an_accepted_edge_capability(self):
        value = fixture("commands/decide_association.json")
        value["body"]["capability"] = "merge"
        self.assertEqual(validate_command(value), value)
        value = fixture("commands/accept_association__catalog.json")
        value["body"]["capability"] = "merge"
        self.assertEqual(validate_command(value), value)  # Runtime refuses execution.
        value = fixture("records/accepted_association__decision.json")
        value["body"]["capability"] = "merge"
        self.invalid(value, validate_record)

    def test_private_bodies_are_closed_required_and_resolve_offline(self):
        for name, body in self.private_values().items():
            validator = self.private_validator(name)
            with self.subTest(schema=name):
                validator.validate(body)
                self.assertFalse(validator.is_valid({**body, "external_action": True}))
            for field in body:
                with self.subTest(schema=name, missing=field):
                    value = deepcopy(body)
                    del value[field]
                    self.assertFalse(validator.is_valid(value))

    def test_effective_evaluation_retains_submitted_output_under_partial_coverage(self):
        validator = self.private_validator("association-evaluation")
        body = self.private_values()["association-evaluation"]
        body["coverage"].update({"status": "partial", "reason": "Synthetic incomplete source."})
        body.update({"outcome": "insufficient_evidence", "selected": []})
        validator.validate(body)
        self.assertEqual(body["evaluation"]["outcome"], "matched")
        body["selected"] = body["evaluation"]["selected"]
        self.assertFalse(validator.is_valid(body))
        body.update({"outcome": "matched", "selected": body["evaluation"]["selected"] * 2})
        self.assertFalse(validator.is_valid(body))
        body.update({"outcome": "ambiguous", "selected": []})
        self.assertFalse(validator.is_valid(body))  # Only one considered candidate.

    def test_disposition_status_cannot_contradict_the_declared_decision(self):
        validator = self.private_validator("association-disposition")
        body = self.private_values()["association-disposition"]
        body["status"] = "released"
        self.assertFalse(validator.is_valid(body))
        body["kind"] = "release"
        validator.validate(body)
        body["status"] = "blocked"
        self.assertFalse(validator.is_valid(body))
        body = self.private_values()["association-disposition"]
        body["authority"]["record_type"] = "judgment"
        self.assertFalse(validator.is_valid(body))

    def test_private_membership_and_receipt_types_do_not_grant_merge_authority(self):
        body = self.private_values()["association-membership"]
        validator = self.private_validator("association-membership")
        body["capability"] = "merge"
        self.assertFalse(validator.is_valid(body))
        body = self.private_values()["association-decision"]
        validator = self.private_validator("association-decision")
        body["decision"] = "accept"
        body["proposal"] = fixture("results/propose_association__proposal.json")["body"]["proposal"]
        validator.validate(body)
        body["proposal"].pop("digest")
        self.assertFalse(validator.is_valid(body))


if __name__ == "__main__":
    unittest.main()
