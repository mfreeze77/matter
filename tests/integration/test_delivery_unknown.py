"""MAT-021 honest ambiguous external outcomes and lookup-only reconciliation."""
from copy import deepcopy

from integration.delivery_helpers import DeliveryFixture, SyntheticTransport
from matter.contracts import ContractError
from matter.delivery import add_milliseconds
from matter.outbox import TransportResult, RESULT_EXTENSION
from matter.storage import StorageError, pin
from rule_helpers import component

UNKNOWN = {"status": "delivery_unknown", "receipt_id": None, "at": {"state": "unknown", "reason": "not_reported"},
    "milestone": None, "reason": "transport:timeout"}

class DeliveryUnknown(DeliveryFixture):
    def _unknown_caps(self, idempotent, lookup):
        from matter.outbox import DestinationDefinition
        transport = SyntheticTransport(idempotency={"scope": component("key-scope"), "retention_ms": 1000} if idempotent else None,
            lookup={"scope": component("lookup-scope"), "reliable_terminal": True} if lookup else None)
        destination = self.destination.value; destination["transport"] = transport.capabilities.reference
        self.destination = DestinationDefinition(destination); self.transport = transport; self.service = self.make_service()
        _, _, authorization = self.authorize(identity="timeout")
        transport.callback = lambda **kwargs: TransportResult(UNKNOWN)
        with self.assertRaises(StorageError) as unknown: self.service.send(authorization)
        self.assertEqual(unknown.exception.code, "E_DELIVERY_UNKNOWN")
        auth = self.f.storage.command_receipt("auth-timeout")["result"]["body"]["authorization"]
        self.assertEqual(self.service.history(auth)["status"], "delivery_unknown")
        self.assertIsNone(self.a.baseline()["value"]["value"]["delivered"])
        self.f.now = add_milliseconds(self.f.now, 20000)
        # New service instance sees persisted unknown; expired capability window
        # and lease do not constitute a safe retry authorization.
        self.restart_service()
        with self.assertRaises(StorageError): self.service.send(authorization)
        equivalent = self.service.execute(self.prepare("equivalent", content=b"Different synthetic wording"))
        self.assertEqual(equivalent.get("outcome"), "withheld", equivalent)
        self.assertEqual(len(transport.calls), 1)

    def test_timeout_without_idempotency_or_lookup(self): self._unknown_caps(False, False)
    def test_timeout_with_idempotency_only(self): self._unknown_caps(True, False)
    def test_timeout_with_lookup_only(self): self._unknown_caps(False, True)
    def test_timeout_with_idempotency_and_lookup(self): self._unknown_caps(True, True)

    def test_lookup_not_found_after_expired_lease_does_not_fence_resumed_worker_but_positive_lookup_reconciles(self):
        from matter.outbox import DestinationDefinition
        self.transport = SyntheticTransport(lookup={"scope": component("lookup"), "reliable_terminal": True})
        d = self.destination.value; d["transport"] = self.transport.capabilities.reference
        self.destination = DestinationDefinition(d); self.service = self.make_service()
        intent, _, prepared = self.authorize(identity="crash")
        def crash(auth): raise SystemExit("synthetic process loss before I/O")
        with self.assertRaises(SystemExit): self.service.send(prepared, before_io=crash)
        auth = self.f.storage.command_receipt("auth-crash")["result"]["body"]["authorization"]
        self.f.now = add_milliseconds(self.f.now, 20000)
        with self.assertRaises(StorageError) as unknown:
            self.service.reconcile(auth, command_id="not-found", idempotency_key="not-found")
        self.assertEqual(unknown.exception.code, "E_DELIVERY_UNKNOWN")
        claim = self.service.prepare_claim(intent, token=self.token, worker="other", lease_ms=10000,
            command_id="resumed-claim", idempotency_key="resumed-claim")
        self.assertEqual(self.service.execute(claim).get("outcome"), "withheld")
        with self.assertRaises(StorageError): self.service.send(prepared)
        self.assertEqual(len(self.transport.calls), 0)
        # The old worker may have been paused after authorization and outside
        # our process. Simulate its eventual external acceptance, not a retry.
        self.transport.seen[self.f.storage.get(auth)["body"]["details"]["value"]["delivery_key"]] = TransportResult({
            "status": "delivered", "receipt_id": "accepted-by-original-worker", "at": deepcopy(self.f.now),
            "milestone": "example:delivered", "reason": "transport:accepted"})
        reconciled = self.service.reconcile(auth, command_id="lookup-positive", idempotency_key="lookup-positive")
        self.assertEqual(reconciled.get("outcome"), "delivered", reconciled)
        self.assertEqual(self.service.history(auth)["status"], "delivered")
        self.assertEqual(self.transport.calls, [])
        self.assertEqual(len(self.transport.lookups), 2)

    def test_crash_after_external_acceptance_before_local_receipt_never_reissues_send(self):
        _, _, prepared = self.authorize(identity="accepted-crash")
        def crash(auth, observed): raise SystemExit("synthetic crash after send")
        with self.assertRaises(SystemExit): self.service.send(prepared, after_io=crash)
        self.assertEqual(len(self.transport.calls), 1)
        self.restart_service()
        auth = self.f.storage.command_receipt("auth-accepted-crash")["result"]["body"]["authorization"]
        self.assertEqual(self.service.history(auth)["status"], "delivery_unknown")
        with self.assertRaises(StorageError) as unknown: self.service.send(prepared)
        self.assertEqual(unknown.exception.code, "E_DELIVERY_UNKNOWN")
        self.assertEqual(len(self.transport.calls), 1)
        self.assertIsNone(self.a.baseline()["value"]["value"]["delivered"])

    def test_definite_failure_is_not_delivered_and_has_no_baseline(self):
        _, _, prepared = self.authorize(identity="rejected")
        self.transport.callback = lambda **kw: TransportResult({**UNKNOWN, "status": "failed", "reason": "transport:rejected"})
        recorded = self.service.send(prepared)
        self.assertEqual(recorded.get("outcome"), "recorded", recorded)
        auth = self.f.storage.command_receipt("auth-rejected")["result"]["body"]["authorization"]
        self.assertEqual(self.service.history(auth)["status"], "failed")
        self.assertIsNone(self.a.baseline()["value"]["value"]["delivered"])
        self.assertEqual(len(self.transport.calls), 1)

    def test_cancellation_during_send_retains_success_history_without_renewing_token(self):
        _, _, prepared = self.authorize(identity="late-cancel")
        def after(auth, observed): self.control("cancel-after-acceptance")
        sent = self.service.send(prepared, after_io=after)
        self.assertEqual(sent.get("outcome"), "delivered", sent)
        auth = self.f.storage.command_receipt("auth-late-cancel")["result"]["body"]["authorization"]
        self.assertEqual(self.service.history(auth)["status"], "delivered")
        self.service.send(prepared)
        self.assertEqual(len(self.transport.calls), 1)

    def test_read_denial_during_send_preserves_fact_but_blocks_disclosure_and_replay(self):
        _, _, prepared = self.authorize(identity="late-deny")
        def after(auth, observed): self.control("deny-after-acceptance", target=self.source, action="deny", capabilities=["read"])
        with self.assertRaises(ContractError): self.service.send(prepared, after_io=after)
        auth = self.f.storage.command_receipt("auth-late-deny")["result"]["body"]["authorization"]
        # Trusted storage inspection is evidence of retention, not public API.
        status = self.f.storage.get(self.service._attempt_ref(auth))["value"]["value"]
        self.assertEqual(status["status"], "delivered")
        self.assertEqual(len(status["observations"]), 1)
        with self.assertRaises(ContractError): self.service.history(auth)
        replay = self.service.send(prepared)
        self.assertEqual(replay["status"], "failure")
        self.assertEqual(replay["error"]["code"], "E_AUTHORITY_REQUIRED")
        self.assertEqual(len(self.transport.calls), 1)

    def test_late_and_unordered_success_cannot_overwrite_newer_baseline(self):
        from matter.outbox import authorization_value
        _, _, prepared = self.authorize(identity="late")
        authorized = self.service.execute(prepared)
        self.assertEqual(authorized.get("outcome"), "authorized", authorized)
        auth = authorized["body"]["authorization"]
        original_time = deepcopy(self.f.now)
        self.f.now = add_milliseconds(self.f.now, 2000)
        newer = self.a.milestone(self.decision, at=self.f.now)
        self.a.deliver(self.assessment, newer)
        baseline = self.a.baseline()
        for name, at in (("older", original_time), ("unordered", {"state": "unknown", "reason": "not_reported"})):
            observed = TransportResult({"status": "delivered", "receipt_id": name, "at": at,
                "milestone": "example:delivered", "reason": "transport:accepted"})
            command = self.service.prepare_observation(auth, observed, command_id=name, idempotency_key=name)
            result = self.service.execute(command)
            self.assertEqual(result.get("outcome"), "delivered", result)
            self.assertEqual(self.a.baseline(), baseline)
        self.assertEqual(len(self.service.history(auth)["observations"]), 2)
        self.assertEqual(self.transport.calls, [])

    def test_later_outcomes_require_separate_actual_host_receipts_and_do_not_advance_baseline(self):
        from integration.helpers import create_command, record_input, domain_value
        from matter.storage import entity_ref
        _, _, prepared = self.authorize(identity="outcomes")
        result = self.service.send(prepared)
        self.assertEqual(result.get("outcome"), "delivered", result)
        auth = self.f.storage.command_receipt("auth-outcomes")["result"]["body"]["authorization"]
        self.assertEqual([r["body"]["stage"] for r in self.service.history(auth)["observations"]], ["delivered"])
        baseline = self.a.baseline()
        for stage in ("consumed", "acted_on", "outcome_verified", "useful"):
            bootstrap = create_command("bootstrap-" + stage, "host-" + stage, scope_id=self.f.storage.scope_id)
            evidence = record_input("receipt", "independent-" + stage, scope_id=self.f.storage.scope_id)
            evidence["namespace"] = "synthetic:outcomes"
            evidence["provenance"].update(origin="host", producer=self.transport.capabilities.value["producer"], recorded_at=self.f.now, parents=[auth])
            evidence["body"].update(stage=stage, operation_id=bootstrap["command_id"], recorded_at=self.f.now,
                outcome="synthetic:" + stage, evidence=[auth], details=domain_value({"declared_observation": stage}))
            def insert(tx):
                matter = tx.insert(tx.command["body"]["matter"]); tx.insert(evidence)
                return tx.success("created", {"matter": pin(matter)})
            self.assertEqual(self.f.storage.execute(bootstrap, insert)["status"], "success")
            source = self.f.storage.get(entity_ref(evidence))
            command = self.service.prepare_outcome(auth, pin(source), command_id="record-" + stage, idempotency_key="record-" + stage)
            recorded = self.service.execute(command)
            self.assertEqual(recorded.get("outcome"), "recorded", recorded)
            self.assertEqual(recorded["body"]["status"], stage)
            self.assertEqual(self.a.baseline(), baseline)
        history = self.service.history(auth)
        self.assertEqual(history["status"], "delivered")
        self.assertEqual([r["body"]["stage"] for r in history["observations"]], ["delivered", "consumed", "acted_on", "outcome_verified", "useful"])
        self.assertEqual(len(self.transport.calls), 1)
