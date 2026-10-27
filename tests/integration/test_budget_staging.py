"""MAT-021 composes the actual MAT-020 ledger inside one host transaction."""

from copy import deepcopy
import unittest

from matter.budgets import REQUEST_EXTENSION, budget_ref
from matter.storage import StorageError, entity_ref, pin
from integration.helpers import create_command
from integration import test_timers_and_budgets as fixtures


class BudgetStagingTests(unittest.TestCase):
    def setUp(self):
        self.helper = fixtures.TimerBudgetTests(methodName="runTest")
        self.helper.setUp()
        self.addCleanup(self.helper.doCleanups)
        self.f = self.helper.f

    def outer(self, inner, identity):
        command = create_command(identity, "synthetic-" + identity, scope_id=self.f.storage.scope_id)
        command.update(actor=self.f.actor, authority=entity_ref(self.f.authority),
                       expected_revisions=deepcopy(inner["expected_revisions"]))
        return command

    def assert_absent(self, reference):
        with self.assertRaises(StorageError) as caught:
            self.f.storage.get(reference)
        self.assertEqual(caught.exception.code, "E_NOT_FOUND")

    def test_charge_shares_outer_receipt_and_exact_retry(self):
        held, reserve, reserved = self.helper.reserve("staged-charge")
        settle = self.helper.command("settle_budget", {"reservation": pin(held), "action": "commit"})
        token = reserve["extensions"][REQUEST_EXTENSION]["value"]["token"]["value"]
        settle = self.helper.budgets.prepare(settle, token=token)
        command = self.outer(settle, "staged-budget-success")
        observed = []

        def handler(tx):
            matter = tx.insert(command["body"]["matter"])
            charged = self.helper.budgets.stage(tx, settle)
            self.assertEqual(charged["outcome"], "committed")
            observed.append(charged["body"]["reservation"])
            return tx.success("created", {"matter": pin(matter)})

        result = self.f.storage.execute(command, handler)
        self.assertEqual(result["status"], "success", result)
        allocation = self.f.storage.get(observed[0])
        self.assertEqual(allocation["creation_receipt"], reserved["receipt"])
        self.assertEqual(entity_ref(self.f.storage.receipt_for(observed[0])), result["receipt"])
        self.assertEqual(allocation["value"]["value"]["status"], "committed")
        account = self.f.storage.get(budget_ref(self.f.storage.scope_id, self.helper.resource))["value"]["value"]
        self.assertEqual(account["charged"]["calls"], 1)
        self.assertEqual(account["held"]["calls"], 0)

        def must_not_execute(tx):
            self.fail("An exact outer retry re-entered budget staging.")

        self.assertEqual(self.f.storage.execute(command, must_not_execute), result)
        self.assertEqual(len(observed), 1)

    def test_later_failure_rolls_back_budget_and_other_outer_writes(self):
        reserve = self.helper.reserve_command("staged-rollback")
        command = self.outer(reserve, "staged-budget-failure")

        def handler(tx):
            tx.insert(command["body"]["matter"])
            self.assertEqual(self.helper.budgets.stage(tx, reserve)["outcome"], "reserved")
            raise StorageError("E_EVIDENCE_INVALID")

        result = self.f.storage.execute(command, handler)
        self.assertEqual(result["error"]["code"], "E_EVIDENCE_INVALID")
        self.assert_absent(entity_ref(command["body"]["matter"]))
        self.assert_absent(budget_ref(self.f.storage.scope_id, self.helper.resource))

    def test_another_outer_actor_cannot_borrow_original_budget_token(self):
        reserve = self.helper.reserve_command("staged-actor")
        command = self.outer(reserve, "staged-budget-wrong-actor")
        command["actor"] = {**command["actor"], "id": "another-actor"}

        def handler(tx):
            tx.insert(command["body"]["matter"])
            self.helper.budgets.stage(tx, reserve)
            self.fail("Another outer actor staged the original allocation.")

        result = self.f.storage.execute(command, handler)
        self.assertEqual(result["error"]["code"], "E_AUTHORITY_REQUIRED")
        self.assert_absent(budget_ref(self.f.storage.scope_id, self.helper.resource))
        self.assert_absent(entity_ref(command["body"]["matter"]))

    def test_refreshing_outer_reads_does_not_refresh_inner_budget_preparation(self):
        seed, original, _ = self.helper.reserve("staged-seed")
        _, released = self.helper.settle(seed, original, "release")
        self.assertEqual(released["outcome"], "released")
        stale = self.helper.reserve_command("staged-old-preparation")
        self.helper.reserve("staged-competing-worker")
        before = self.f.storage.get(budget_ref(self.f.storage.scope_id, self.helper.resource))
        command = self.outer(stale, "staged-budget-stale")
        command["expected_revisions"] = [pin(self.f.storage.get(entity_ref(ref)))
                                         for ref in command["expected_revisions"]]

        def handler(tx):
            tx.insert(command["body"]["matter"])
            self.helper.budgets.stage(tx, stale)
            self.fail("A new outer read set renewed old budget preparation.")

        result = self.f.storage.execute(command, handler)
        self.assertEqual(result["error"]["code"], "E_DEPENDENCY_STALE")
        self.assertEqual(self.f.storage.get(entity_ref(before)), before)
        self.assert_absent(entity_ref(command["body"]["matter"]))
