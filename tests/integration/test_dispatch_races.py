"""MAT-021 actual scoped outbox/control/transport races (synthetic)."""
from integration.delivery_helpers import DeliveryFixture

class DispatchRaces(DeliveryFixture):
    def test_queue_is_durable_and_exact_replay_makes_no_transport_call(self):
        intent, command, result = self.enqueue()
        self.assertEqual(self.service.execute(command), result)
        self.assertEqual(self.transport.calls, [])

    def test_delivery_claims_authorizes_sends_and_advances_only_observed_baseline(self):
        from matter.outbox import RESULT_EXTENSION
        intent, _, _ = self.enqueue()
        claim = self.service.prepare_claim(intent, token=self.token, worker="worker-a", lease_ms=10000,
            command_id="claim-a", idempotency_key="claim-a")
        leased = self.service.execute(claim)
        self.assertEqual(leased.get("outcome"), "leased", leased)
        lease = leased["extensions"][RESULT_EXTENSION]["value"]["lease"]
        authorization = self.service.prepare_authorize(intent, token=self.token, lease=lease, attempt_id="attempt-a",
            command_id="authorize-a", idempotency_key="authorize-a")
        sent = self.service.send(authorization)
        self.assertEqual(sent.get("outcome"), "delivered", sent)
        self.assertEqual(len(self.transport.calls), 1)
        self.assertIsNotNone(self.a.baseline()["value"]["value"]["delivered"])
        self.service.transports = ()
        self.assertEqual(self.service.send(authorization), sent)
        self.assertEqual(len(self.transport.calls), 1)

    def test_clock_crossing_during_budget_commit_rolls_back_authorization_and_charge(self):
        from copy import deepcopy
        from matter.identity_dependencies import _value
        from matter.outbox import REQUEST_EXTENSION
        intent, lease, command = self.authorize(identity="clock", lease_ms=5000)
        inner = _value("operation-command", command["extensions"][REQUEST_EXTENSION]["value"]["budget_command"])
        reservation = inner["body"]["reservation"]
        from matter.storage import entity_ref
        before = self.f.storage.get(entity_ref(reservation))
        original = self.budgets.stage
        def advance(tx, prepared):
            result = original(tx, prepared)
            self.f.now = deepcopy(lease["expires_at"])
            return result
        self.budgets.stage = advance
        result = self.service.execute(command)
        self.assertEqual(result["status"], "failure", result)
        self.assertEqual(result["error"]["code"], "E_DEPENDENCY_STALE")
        self.assertEqual(self.f.storage.get(entity_ref(reservation)), before)
        self.assertEqual(self.transport.calls, [])

    def test_cancellation_before_authorization_prevents_any_send_or_budget_commit(self):
        _, _, command = self.authorize(identity="cancel")
        self.control("before-authorization")
        result = self.service.send(command)
        self.assertEqual(result["status"], "failure", result)
        self.assertIn(result["error"]["code"], {"E_CANCELLED", "E_DEPENDENCY_STALE"})
        self.assertEqual(self.transport.calls, [])
        self.assertIsNone(self.a.baseline()["value"]["value"]["delivered"])

    def test_recovery_assessment_before_authorization_prevents_queued_advice(self):
        _, _, command = self.authorize(identity="recovery")
        corrected, _, _, _ = self.a.assess("recovered-fact", signal="recovered")
        self.a.evaluate(corrected)
        result = self.service.send(command)
        self.assertEqual(result["status"], "failure", result)
        self.assertEqual(result["error"]["code"], "E_DEPENDENCY_STALE")
        self.assertEqual(self.transport.calls, [])

    def test_audience_revision_and_destination_permission_are_actual_gates(self):
        from matter.storage import entity_ref, pin
        from matter.contracts import ContractError
        # All evidence is covered, but destination is independently absent.
        self.token = self.f.controls.capture(actor=self.f.actor, authority=entity_ref(self.f.authority), capability="delivery",
            targets=self.a.targets(self.assessment))
        with self.assertRaises(ContractError) as denied: self.prepare("missing-destination-grant")
        self.assertEqual(denied.exception.code, "E_AUTHORITY_REQUIRED")
        self.token = self.f.controls.capture(actor=self.f.actor, authority=entity_ref(self.f.authority), capability="delivery",
            targets=[*self.a.targets(self.assessment), entity_ref(self.destination_permission)])
        _, _, command = self.authorize(identity="audience")
        helper = self.a.contexts
        helper.publish(helper.definition("audience", "human", version="2.0"), previous=pin(self.a.audience))
        result = self.service.send(command)
        self.assertEqual(result["status"], "failure", result)
        self.assertEqual(result["error"]["code"], "E_DEPENDENCY_STALE")
        self.assertEqual(self.transport.calls, [])

    def test_expired_pre_authorization_lease_fences_old_worker_without_new_hold(self):
        from matter.delivery import add_milliseconds
        from matter.outbox import RESULT_EXTENSION, REQUEST_EXTENSION
        intent, lease, old = self.authorize(identity="old", lease_ms=1000)
        hold = old["extensions"][REQUEST_EXTENSION]["value"]["budget_command"]["value"]["body"]["reservation"]
        self.f.now = add_milliseconds(self.f.now, 1001)
        claim = self.service.prepare_claim(intent, token=self.token, worker="new", lease_ms=10000,
            command_id="claim-new", idempotency_key="claim-new")
        result = self.service.execute(claim)
        self.assertEqual(result.get("outcome"), "leased", result)
        newlease = result["extensions"][RESULT_EXTENSION]["value"]["lease"]
        self.assertGreater(newlease["fence"], lease["fence"])
        refused = self.service.send(old)
        self.assertEqual(refused["status"], "failure", refused)
        fresh = self.service.prepare_authorize(intent, token=self.token, lease=newlease, attempt_id="new",
            command_id="auth-new", idempotency_key="auth-new")
        self.assertEqual(fresh["extensions"][REQUEST_EXTENSION]["value"]["budget_command"]["value"]["body"]["reservation"], hold)
        self.assertEqual(self.service.send(fresh).get("outcome"), "delivered")
        self.assertEqual(len(self.transport.calls), 1)

    def test_distinct_equivalent_intents_compete_across_real_sqlite_handles(self):
        from copy import copy
        from concurrent.futures import ThreadPoolExecutor
        from matter.budgets import BudgetService
        from matter.controls import ControlService
        from matter.storage import SQLiteStore
        second = SQLiteStore(self.f.database, scope_id=self.f.storage.scope_id)
        self.addCleanup(second.close)
        controls = ControlService(second, policy=self.f.controls.policy, clock=lambda: self.f.now)
        attention = copy(self.a.service); attention.storage = second; attention.controls = controls
        budgets = BudgetService(second, definitions=[self.definition], controls=controls, clock=lambda: self.f.now)
        other = self.make_service(storage=second, attention=attention, budgets=budgets, controls=controls)
        first = self.prepare("intent-a", content=b"Synthetic repeated agenda item")
        competing = self.prepare("intent-b", service=other, content=b"Equivalent paraphrased agenda item")
        self.assertEqual(first["body"]["delivery_key"], competing["body"]["delivery_key"])
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda pair: pair[0].execute(pair[1]), ((self.service, first), (other, competing))))
        winners = [r for r in results if r.get("outcome") == "ready"]
        self.assertEqual(len(winners), 1, results)
        losers = [r for r in results if r.get("outcome") != "ready"]
        self.assertEqual(len(losers), 1)
        self.assertTrue(losers[0].get("outcome") == "withheld" or losers[0].get("error", {}).get("code") == "E_DEPENDENCY_STALE", losers)
        _, _, command = self.authorize(winners[0]["body"]["intent"], identity="winner")
        self.assertEqual(self.service.send(command).get("outcome"), "delivered")
        self.assertEqual(len(self.transport.calls), 1)

    def test_destination_only_delivery_denial_after_queue_blocks_send(self):
        _, _, command = self.authorize(identity="destination-denial")
        self.control("deny-destination", target=self.destination_permission, action="deny", capabilities=["delivery"])
        result = self.service.send(command)
        self.assertEqual(result["status"], "failure", result)
        self.assertIn(result["error"]["code"], {"E_AUTHORITY_REQUIRED", "E_DEPENDENCY_STALE"})
        self.assertEqual(self.transport.calls, [])

    def test_missing_transport_refuses_before_durable_queue_or_charge(self):
        from matter.contracts import ContractError
        self.service.transports = ()
        with self.assertRaises(ContractError) as missing: self.prepare("missing-transport")
        self.assertEqual(missing.exception.code, "E_POLICY_INVALID")
        self.assertEqual(self.transport.calls, [])
        with self.assertRaises(ContractError) as journal:
            self.f.storage.command_receipt("queue-missing-transport")
        self.assertEqual(journal.exception.code, "E_NOT_FOUND")
        self.assertIsNone(self.a.baseline()["value"]["value"]["delivered"])

    def test_duplicate_queue_does_not_disclose_original_intent_to_changed_caller(self):
        from matter.outbox import RESULT_EXTENSION
        intent, _, _ = self.enqueue()
        changed = self.prepare("foreign-actor-duplicate")
        changed["actor"] = {**self.f.actor, "id": "unadmitted-actor"}
        result = self.service.execute(changed)
        self.assertEqual(result["status"], "failure", result)
        self.assertEqual(result["error"]["code"], "E_AUTHORITY_REQUIRED")
        self.assertNotIn(RESULT_EXTENSION, result.get("extensions", {}))
        self.assertEqual(self.transport.calls, [])

    def test_queue_rejects_undercharged_reserve_and_zero_delivery_declaration_atomically(self):
        from matter.budgets import budget_ref
        from matter.contracts import ContractError
        from matter.outbox import REQUEST_EXTENSION
        for both, code in ((False, "E_EVIDENCE_INVALID"), (True, "E_POLICY_INVALID")):
            with self.subTest(changed_declaration=both):
                changed = self.prepare("undercharge-" + str(both))
                request = changed["extensions"][REQUEST_EXTENSION]["value"]
                request["budget_command"]["value"]["body"]["amounts"]["deliveries"] = 0
                if both: request["intent_payload"]["value"]["amounts"]["deliveries"] = 0
                result = self.service.execute(changed)
                self.assertEqual(result["status"], "failure", result)
                self.assertEqual(result["error"]["code"], code)
                with self.assertRaises(ContractError) as absent:
                    self.f.storage.get(budget_ref(self.f.storage.scope_id, self.definition))
                self.assertEqual(absent.exception.code, "E_NOT_FOUND")
                self.assertEqual(self.transport.calls, [])

    def test_authorization_cannot_charge_another_identical_held_reservation(self):
        from copy import deepcopy
        from matter._rule_values import domain
        from matter.outbox import REQUEST_EXTENSION
        from matter.storage import entity_ref
        from rule_helpers import LATE
        intent, _, _ = self.enqueue()
        reserve = self.service._header("reserve_budget", "other-hold", "other-hold", self.token,
            {"budget": self.definition.reference, "reservation_id": "other-hold", "amounts": {"deliveries": 1, "interruption_units": 1},
                "expires_at": LATE, "targets": self.token["targets"]})
        held = self.budgets.execute(self.budgets.prepare(reserve, token=self.token))
        self.assertEqual(held.get("outcome"), "reserved", held)
        other = held["body"]["reservation"]
        _, _, prepared = self.authorize(intent, identity="own-allocation")
        own = prepared["extensions"][REQUEST_EXTENSION]["value"]["budget_command"]["value"]["body"]["reservation"]
        settle = self.service._header("settle_budget", "other-commit", "other-commit", self.token, {"reservation": other, "action": "commit"})
        settle = self.budgets.prepare(settle, token=self.token)
        changed = deepcopy(prepared)
        changed["command_id"] = changed["idempotency_key"] = "swapped-allocation"
        changed["extensions"][REQUEST_EXTENSION]["value"]["budget_command"] = domain("operation-command", settle)
        before = {"own": self.f.storage.get(entity_ref(own)), "other": self.f.storage.get(entity_ref(other))}
        account = before["own"]["value"]["value"]["account"]
        account_before = self.f.storage.get(entity_ref(account))
        result = self.service.execute(changed)
        self.assertEqual(result["status"], "failure", result)
        self.assertEqual(result["error"]["code"], "E_EVIDENCE_INVALID")
        self.assertEqual(self.f.storage.get(entity_ref(own)), before["own"])
        self.assertEqual(self.f.storage.get(entity_ref(other)), before["other"])
        self.assertEqual(self.f.storage.get(entity_ref(account)), account_before)
        self.assertEqual(self.transport.calls, [])
        self.assertEqual(self.service.send(prepared).get("outcome"), "delivered")
        self.assertEqual(len(self.transport.calls), 1)

    def test_cancelled_never_authorized_work_can_be_withdrawn_then_replaced_without_renewing_old_token(self):
        from copy import deepcopy
        from control_helpers import control_command
        from integration.helpers import _in_scope
        from matter.contracts import ContractError
        from matter.outbox import REQUEST_EXTENSION, RESULT_EXTENSION
        from matter.storage import entity_ref
        intent, _, old_authorization = self.authorize(identity="withdraw-old")
        original_token = deepcopy(self.token)
        cancellation = self.control("withdraw-cancel")
        resume = _in_scope(control_command("withdraw-resume", self.f.authority, targets=[self.f.subject], action="resume",
            supersedes=[cancellation["body"]["control"]], now=self.f.now), self.f.storage.scope_id)
        resume["actor"] = deepcopy(self.f.actor); resume["body"]["control"]["body"]["actor"] = deepcopy(self.f.actor)
        self.assertEqual(self.f.controls.apply(self.f.controls.prepare(resume))["status"], "success")
        self.assessment, self.claim, self.source, self.occurrence = self.a.assess("same-material-after-resume",
            source=self.source, occurrence=self.occurrence)
        self.decision_value, self.decision, self.attention_command, _ = self.a.evaluate(self.assessment)
        self.token = self.f.controls.capture(actor=self.f.actor, authority=entity_ref(self.f.authority), capability="delivery",
            targets=[*self.a.targets(self.assessment), entity_ref(self.destination_permission)])
        blocked = self.service.execute(self.prepare("new-before-withdrawal"))
        self.assertEqual(blocked.get("outcome"), "withheld", blocked)
        withdraw = self.service.prepare_withhold(intent, token=original_token, reason="cancelled",
            command_id="withdraw-old", idempotency_key="withdraw-old")
        released = self.service.execute(withdraw)
        self.assertEqual(released.get("outcome"), "withheld", released)
        slot = self.f.storage.get(entity_ref(released["extensions"][RESULT_EXTENSION]["value"]["slot"]))
        self.assertEqual(slot["value"]["value"]["state"], "withheld")
        self.assertIsNone(slot["value"]["value"]["authorization"])
        allocation = self.f.storage.get(entity_ref(slot["value"]["value"]["reservation"]))
        self.assertEqual(allocation["value"]["value"]["status"], "released")
        self.assertEqual(allocation["value"]["value"]["token"]["value"], original_token)
        refused = self.service.send(old_authorization)
        self.assertEqual(refused["status"], "failure", refused)
        self.assertEqual(self.transport.calls, [])
        fresh, _, _ = self.enqueue(identity="new-after-withdrawal")
        account = self.f.storage.get(entity_ref(allocation["value"]["value"]["account"]))
        self.assertEqual(account["value"]["value"]["charged"]["deliveries"], 0)
        self.assertEqual(account["value"]["value"]["held"]["deliveries"], 1)
        self.assertEqual(self.service.execute(withdraw), released)
        self.assertEqual(self.f.storage.get(entity_ref(account)), account)
        _, _, prepared = self.authorize(fresh, identity="withdraw-new")
        self.assertEqual(self.service.send(prepared).get("outcome"), "delivered")
        self.assertEqual(len(self.transport.calls), 1)

    def test_authorized_and_unknown_attempts_cannot_withdraw_or_refund(self):
        from matter.contracts import ContractError
        from matter.outbox import TransportResult
        from matter.storage import entity_ref
        intent, _, prepared = self.authorize(identity="no-refund")
        result = self.service.execute(prepared)
        self.assertEqual(result.get("outcome"), "authorized", result)
        auth = result["body"]["authorization"]
        allocation = self.f.storage.get(entity_ref(result["body"]["attention_budget"]))
        account = self.f.storage.get(entity_ref(allocation["value"]["value"]["account"]))
        for status in ("authorized", "delivery_unknown"):
            if status == "delivery_unknown":
                command = self.service.prepare_observation(auth, TransportResult({"status": "delivery_unknown", "receipt_id": None,
                    "at": {"state": "unknown", "reason": "not_reported"}, "milestone": None, "reason": "transport:timeout"}),
                    command_id="unknown-no-refund", idempotency_key="unknown-no-refund")
                self.assertEqual(self.service.execute(command).get("outcome"), "recorded")
            with self.assertRaises(ContractError) as refused:
                self.service.prepare_withhold(intent, token=self.token, reason="cancelled",
                    command_id="withdraw-" + status, idempotency_key="withdraw-" + status)
            self.assertEqual(refused.exception.code, "E_DELIVERY_UNKNOWN")
            self.assertEqual(self.f.storage.get(entity_ref(allocation)), allocation)
            self.assertEqual(self.f.storage.get(entity_ref(account)), account)
        self.assertEqual(self.transport.calls, [])
