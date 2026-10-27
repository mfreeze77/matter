"""MAT-020 additive wire structure, independently declared negative vectors."""

from copy import deepcopy
import unittest

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from matter.budgets import BudgetDefinition
from matter.contracts import ContractError, schema_for, validate_command, validate_result
from matter.scheduler import TimerDefinition
from tests.contract.test_operation_contracts import SUCCESS_OUTCOMES, fixture


OLD_OPERATIONS = {
    "ingest_observation", "create_matter", "update_matter_metadata", "commit_occurrence_grouping",
    "publish_association_candidates", "propose_association", "accept_association", "decide_association",
    "append_claim", "relate_evidence", "revise_evidence_acceptance", "link_matters", "merge_matters",
    "correct_merge", "release_identity_separations", "record_control", "commit_assessment", "invalidate_dependents",
    "request_transition", "prepare_delivery", "dispatch", "assess", "publish_coverage", "register_negative_watch",
}
NEW_OPERATIONS = {"schedule_timer", "fire_timer", "reserve_budget", "settle_budget"}


class TimerBudgetContracts(unittest.TestCase):
    def test_additive_v1_keeps_old_operations_record_kinds_and_success_meanings(self):
        inventory = fixture("inventory.json")
        self.assertEqual(len(OLD_OPERATIONS), 24)
        self.assertEqual(set(inventory["operations"]), OLD_OPERATIONS | NEW_OPERATIONS | {"record_semantic_execution", "admit_semantic_result"})
        self.assertEqual(len(inventory["record_kinds"]), 12)
        self.assertEqual(sum(len(values) for values in SUCCESS_OUTCOMES.values()), 63)
        for operation in OLD_OPERATIONS:
            self.assertEqual(set(inventory["success_outcomes"][operation]), SUCCESS_OUTCOMES[operation])
            self.assertEqual(validate_command(fixture("commands/" + operation + ".json"))["schema_version"], "1.0")

    def test_each_new_success_has_closed_body_and_explicit_operation_outcome(self):
        for operation in NEW_OPERATIONS:
            for outcome in SUCCESS_OUTCOMES[operation]:
                original = fixture("results/" + operation + "__" + outcome + ".json")
                self.assertEqual(validate_result(original), original)
                for key in original["body"]:
                    with self.subTest(operation=operation, outcome=outcome, missing=key):
                        value = deepcopy(original)
                        del value["body"][key]
                        with self.assertRaises(ContractError):
                            validate_result(value)
                edited = deepcopy(original)
                edited["body"]["pretend_execution"] = True
                with self.assertRaises(ContractError):
                    validate_result(edited)

    def test_budget_amounts_require_portable_nonnegative_integer_dimensions(self):
        for amount in (-1, True, 0.5, "1", 2**53):
            with self.subTest(amount=repr(amount)):
                command = fixture("commands/reserve_budget.json")
                command["body"]["amounts"]["calls"] = amount
                with self.assertRaises(ContractError):
                    validate_command(command)
        command = fixture("commands/reserve_budget.json")
        command["body"]["amounts"] = {"inferred_price": 1}
        with self.assertRaises(ContractError):
            validate_command(command)
        command["body"]["amounts"] = {}
        with self.assertRaises(ContractError):
            validate_command(command)

    def test_firing_requires_actual_nonempty_decision_and_positive_bounded_coalescing(self):
        original = fixture("results/fire_timer__fired.json")
        for count in (0, True, 129):
            value = deepcopy(original)
            value["body"]["coalesced_count"] = count
            with self.assertRaises(ContractError):
                validate_result(value)
        value = deepcopy(original)
        value["body"]["attention_decision"] = None
        with self.assertRaises(ContractError):
            validate_result(value)
        value = fixture("results/fire_timer__not_due.json")
        value["body"]["firing"] = original["body"]["firing"]
        with self.assertRaises(ContractError):
            validate_result(value)

    def test_timer_definition_rejects_ambiguous_order_generation_and_expiry(self):
        original = fixture("commands/schedule_timer.json")["body"]["timer"]["value"]
        TimerDefinition(original)
        for change in (lambda value: value.update(generation=0),
                       lambda value: value.update(checkpoints=[]),
                       lambda value: value.update(expires_at=value["checkpoints"][0]["at"]),
                       lambda value: value["dependencies"].clear()):
            value = deepcopy(original)
            change(value)
            with self.assertRaises(ContractError):
                TimerDefinition(value)
        value = deepcopy(original)
        value["checkpoints"] *= 2
        with self.assertRaises(ContractError):
            TimerDefinition(value)

    def test_budget_units_window_and_kind_cannot_silently_change_meaning(self):
        time = fixture("commands/request_transition.json")["body"]["effective_at"]
        value = {"schema_version": "1.0", "namespace": "example", "id": "typed-cost", "semantic_version": "1.0",
            "kind": "resource", "window": {"start": time, "end": {**time, "value": "2026-10-12T00:00:00Z"}, "bounds": "closed_open"},
            "limits": {"cost_units": 100}, "units": {"cost_units": "example:microcredit"}, "description": "Explicit integer unit, no price oracle."}
        original = BudgetDefinition(value)
        value["units"]["cost_units"] = "example:credit"
        self.assertNotEqual(BudgetDefinition(value).reference, original.reference)
        value["kind"] = "attention"
        with self.assertRaises(ContractError):
            BudgetDefinition(value)
        value["kind"] = "resource"
        value["units"] = {}
        with self.assertRaises(ContractError):
            BudgetDefinition(value)

    def test_old_closed_reader_rejects_new_operations_instead_of_guessing(self):
        core = schema_for("record")
        registry = Registry().with_resource(core["$id"], Resource.from_contents(core))
        old = deepcopy(schema_for("command"))
        old["properties"]["operation"]["enum"] = sorted(OLD_OPERATIONS)
        reader = Draft202012Validator(old, registry=registry)
        for operation in NEW_OPERATIONS:
            value = fixture("commands/" + operation + ".json")
            self.assertFalse(reader.is_valid(value))
            self.assertEqual(validate_command(value), value)


if __name__ == "__main__":
    unittest.main()
