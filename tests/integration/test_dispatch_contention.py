"""MAT-083 controlled contention; real lock expiry remains a storage failure."""

from concurrent.futures import ThreadPoolExecutor
from copy import copy
from threading import Event

from integration.delivery_helpers import DeliveryFixture
from matter.budgets import BudgetService
from matter.contracts import ContractError
from matter.controls import ControlService
from matter.outbox import REQUEST_EXTENSION
from matter.storage import SQLiteStore, entity_ref


class DispatchContention(DeliveryFixture):
    def compete(self, *, expire_wait):
        second = SQLiteStore(self.f.database, scope_id=self.f.storage.scope_id,
                             timeout=0.05 if expire_wait else 5.0)
        self.addCleanup(second.close)
        controls = ControlService(second, policy=self.f.controls.policy, clock=lambda: self.f.now)
        attention = copy(self.a.service)
        attention.storage, attention.controls = second, controls
        budgets = BudgetService(second, definitions=[self.definition], controls=controls,
                                clock=lambda: self.f.now)
        other = self.make_service(storage=second, attention=attention, budgets=budgets, controls=controls)
        first = self.prepare("controlled-winner")
        competing = self.prepare("controlled-loser", service=other)
        self.assertEqual(first["body"]["delivery_key"], competing["body"]["delivery_key"])

        writer_locked, waiter_begin, release = Event(), Event(), Event()
        original_open = second._open

        def opened(**kwargs):
            db = original_open(**kwargs)
            # Trace is invoked before SQLite attempts the writer lock. No SQL
            # values are retained, and ordering does not depend on a sleep.
            db.set_trace_callback(lambda sql: waiter_begin.set() if sql == "BEGIN IMMEDIATE" else None)
            return db

        def hold(stage):
            if stage == "before_commit":
                writer_locked.set()
                if not release.wait(10):
                    raise RuntimeError("Controlled writer release was not signalled.")

        second._open = opened
        self.f.storage._fault_hook = hold
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                winner = pool.submit(self.service.execute, first)
                try:
                    self.assertTrue(writer_locked.wait(10), "Winner did not hold its transaction.")
                    loser = pool.submit(other.execute, competing)
                    self.assertTrue(waiter_begin.wait(10), "Loser did not attempt BEGIN IMMEDIATE.")
                    if expire_wait:
                        unavailable = loser.result(timeout=10)
                        self.assertEqual(unavailable.get("error", {}).get("code"), "E_STORAGE_UNAVAILABLE", unavailable)
                        self.assertTrue(unavailable["error"]["retriable"])
                    release.set()
                    ready, refused = winner.result(timeout=10), loser.result(timeout=10)
                finally:
                    release.set()
        finally:
            self.f.storage._fault_hook = None
            second._open = original_open

        self.assertEqual(ready.get("outcome"), "ready", ready)
        if expire_wait:
            # BEGIN failed before a durable command existed. Recover using the
            # exact original command, never a new token or a transport retry.
            with self.assertRaises(ContractError) as absent:
                second.command_receipt(competing["idempotency_key"])
            self.assertEqual(absent.exception.code, "E_NOT_FOUND")
            refused = other.execute(competing)
        self.assertEqual(refused.get("error", {}).get("code"), "E_DEPENDENCY_STALE", refused)
        self.assertEqual(other.execute(competing), refused)
        self.assertEqual(self.service.execute(first), ready)
        self.assertEqual(self.transport.calls, [])

        _, _, authorization = self.authorize(ready["body"]["intent"], identity="controlled-winner")
        delivered = self.service.send(authorization)
        self.assertEqual(delivered.get("outcome"), "delivered", delivered)
        self.assertEqual(self.service.send(authorization), delivered)
        self.assertEqual(len(self.transport.calls), 1)
        self.assertIsNotNone(self.a.baseline()["value"]["value"]["delivered"])
        # Only the winner reserved and charged the attention budget.
        reservation = authorization["extensions"][REQUEST_EXTENSION]["value"]["budget_command"]["value"]["body"]["reservation"]
        allocation = self.f.storage.get(entity_ref(reservation))
        account = self.f.storage.get(entity_ref(allocation["value"]["value"]["account"]))
        self.assertEqual(account["value"]["value"]["charged"]["deliveries"], 1)
        self.assertEqual(account["value"]["value"]["held"]["deliveries"], 0)

    def test_waiter_rechecks_stale_pins_after_winner_commits(self):
        self.compete(expire_wait=False)

    def test_actual_writer_lock_timeout_stays_unavailable_then_exact_command_recovers(self):
        self.compete(expire_wait=True)
