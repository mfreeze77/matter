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
        self.assertEqual(self.service.reconcile(auth, command_id="again", idempotency_key="again"), reconciled)
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
        self.assertEqual(self.service.reconcile(auth, command_id="failed-query", idempotency_key="failed-query"), recorded)
        self.assertEqual(self.transport.lookups, [])
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

    def test_independent_outcomes_preserve_behind_and_ahead_producer_clocks_without_ordering_delivery(self):
        from integration.helpers import create_command, record_input, domain_value
        from matter.outbox import OBSERVATION_EXTENSION, REQUEST_EXTENSION
        from matter.storage import entity_ref
        from rule_helpers import EARLY
        _, _, prepared = self.authorize(identity="outcome-clocks")
        result = self.service.send(prepared)
        self.assertEqual(result.get("outcome"), "delivered", result)
        auth = self.f.storage.command_receipt("auth-outcome-clocks")["result"]["body"]["authorization"]
        baseline = self.a.baseline()
        delivery = self.f.storage.get(self.service._attempt_ref(auth))["value"]["value"]["current"]
        for label, stage, reported_at in (("behind", "consumed", EARLY), ("ahead", "useful", add_milliseconds(self.f.now, 5000))):
            with self.subTest(clock=label):
                bootstrap = create_command("outcome-clock-" + label, "outcome-clock-host-" + label, scope_id=self.f.storage.scope_id)
                evidence = record_input("receipt", "clock-" + label, scope_id=self.f.storage.scope_id)
                evidence["namespace"] = "synthetic:outcomes"
                evidence["provenance"].update(origin="host", producer=self.transport.capabilities.value["producer"],
                    recorded_at=deepcopy(reported_at), parents=[auth])
                evidence["body"].update(stage=stage, operation_id=bootstrap["command_id"], recorded_at=deepcopy(reported_at),
                    outcome="synthetic:" + stage, evidence=[auth], details=domain_value({"declared_observation": stage}))
                def insert(tx):
                    matter = tx.insert(tx.command["body"]["matter"]); tx.insert(evidence)
                    return tx.success("created", {"matter": pin(matter)})
                self.assertEqual(self.f.storage.execute(bootstrap, insert)["status"], "success")
                source = self.f.storage.get(entity_ref(evidence))
                for mutation in ("reported_at", "receipt_id", "extra_source"):
                    with self.subTest(clock=label, mutation=mutation):
                        key = "tamper-clock-" + label + "-" + mutation
                        changed = self.service.prepare_outcome(auth, pin(source), command_id=key, idempotency_key=key)
                        request = changed["extensions"][REQUEST_EXTENSION]["value"]
                        if mutation == "extra_source": request["evidence"].append(pin(source))
                        else:
                            request["observation"]["value"][mutation] = deepcopy(self.f.now) if mutation == "reported_at" else "rewritten-receipt"
                        before = self.f.storage.get(self.service._attempt_ref(auth))
                        refused = self.service.execute(changed)
                        self.assertEqual(refused["status"], "failure", refused)
                        self.assertEqual(refused["error"]["code"], "E_EVIDENCE_INVALID")
                        self.assertEqual(self.f.storage.get(self.service._attempt_ref(auth)), before)
                        self.assertEqual(self.a.baseline(), baseline)
                command = self.service.prepare_outcome(auth, pin(source), command_id="record-clock-" + label,
                    idempotency_key="record-clock-" + label)
                recorded = self.service.execute(command)
                self.assertEqual(recorded.get("outcome"), "recorded", recorded)
                fact = self.f.storage.get(recorded["body"]["delivery_receipt"])
                observation = fact["extensions"][OBSERVATION_EXTENSION]["value"]
                self.assertEqual(observation["reported_at"], reported_at)
                self.assertEqual(observation["ordering"], "unavailable")
                self.assertEqual(observation["observed_at"], self.f.now)
                self.assertIn(pin(source), fact["body"]["evidence"])
                self.assertIn(pin(source), fact["provenance"]["parents"])
                self.assertEqual(self.f.storage.get(pin(source)), source)
                self.assertEqual(self.a.baseline(), baseline)
                current = self.f.storage.get(self.service._attempt_ref(auth))["value"]["value"]
                self.assertEqual(current["status"], "delivered")
                self.assertEqual(current["current"], delivery)
                self.assertEqual(len(self.transport.calls), 1)
                self.assertEqual(self.transport.lookups, [])

    def test_lease_expiry_after_authorization_is_definite_system_no_send(self):
        from matter.outbox import ENGINE
        from matter.storage import entity_ref
        intent, lease, prepared = self.authorize(identity="refuse-lease", lease_ms=1000)
        def expire(auth): self.f.now = deepcopy(lease["expires_at"])
        with self.assertRaises(StorageError) as refused: self.service.send(prepared, before_io=expire)
        self.assertEqual(refused.exception.code, "E_DEPENDENCY_STALE")
        auth = self.f.storage.command_receipt("auth-refuse-lease")["result"]["body"]["authorization"]
        history = self.service.history(auth)
        self.assertEqual(history["status"], "failed")
        fact = history["observations"][0]
        self.assertEqual(fact["provenance"]["origin"], "system")
        self.assertEqual(fact["provenance"]["producer"], ENGINE)
        self.assertEqual(fact["extensions"]["matter:delivery-observation"]["value"]["reason"], "delivery:refused_before_io")
        allocation = self.f.storage.get(entity_ref(history["authorization"]["body"]["details"]["value"]["attention_budget"]))
        self.assertEqual(allocation["value"]["value"]["status"], "committed")
        recorded = self.service.send(prepared)
        self.assertEqual(recorded.get("outcome"), "recorded")
        self.assertEqual(self.service.reconcile(auth, command_id="local-failed-query", idempotency_key="local-failed-query"), recorded)
        self.assertEqual(self.transport.lookups, [])
        self.assertEqual(self.transport.calls, [])
        self.enqueue(identity="eligible-after-definite-refusal")

    def test_payload_failure_after_authorization_is_not_a_fabricated_transport_timeout(self):
        _, _, prepared = self.authorize(identity="refuse-content")
        def unavailable(auth):
            digest = self.f.storage.get(auth)["body"]["details"]["value"]["content_digest"]
            # Delete this fixture's own synthetic blob after authorization,
            # exercising the real payload store's unavailable path.
            (self.f.payloads._directory / digest).unlink()
        with self.assertRaises(StorageError) as refused: self.service.send(prepared, before_io=unavailable)
        self.assertEqual(refused.exception.code, "E_EVIDENCE_UNAVAILABLE")
        auth = self.f.storage.command_receipt("auth-refuse-content")["result"]["body"]["authorization"]
        history = self.service.history(auth)
        self.assertEqual(history["status"], "failed")
        self.assertEqual(history["observations"][0]["provenance"]["origin"], "system")
        self.assertEqual(self.transport.calls, [])
        self.assertIsNone(self.a.baseline()["value"]["value"]["delivered"])

    def test_ahead_transport_clock_preserves_delivery_fact_without_ordering_baseline_by_it(self):
        from matter.outbox import OBSERVATION_EXTENSION
        _, _, prepared = self.authorize(identity="skew")
        reported = add_milliseconds(self.f.now, 5000)
        self.transport.callback = lambda **kw: TransportResult({"status": "delivered", "receipt_id": "clock-skew-receipt",
            "at": reported, "milestone": "example:delivered", "reason": "transport:accepted"})
        result = self.service.send(prepared)
        self.assertEqual(result.get("outcome"), "delivered", result)
        fact = self.f.storage.get(result["body"]["delivery_receipt"])
        observation = fact["extensions"][OBSERVATION_EXTENSION]["value"]
        self.assertEqual(observation["reported_at"], reported)
        self.assertEqual(observation["ordering"], "unavailable")
        self.assertEqual(self.a.baseline()["value"]["value"]["delivered"]["delivered_at"], self.f.now)
        self.assertEqual(len(self.transport.calls), 1)

    def test_repeated_uncertainty_is_coalesced_and_cannot_block_later_positive_lookup(self):
        from matter.outbox import DestinationDefinition, REQUEST_EXTENSION
        self.transport = SyntheticTransport(lookup={"scope": component("coalesced-lookup"), "reliable_terminal": True})
        d = self.destination.value; d["transport"] = self.transport.capabilities.reference
        self.destination = DestinationDefinition(d); self.service = self.make_service()
        self.transport.callback = lambda **kw: TransportResult(UNKNOWN)
        _, _, prepared = self.authorize(identity="poll")
        with self.assertRaises(StorageError): self.service.send(prepared)
        auth = self.f.storage.command_receipt("auth-poll")["result"]["body"]["authorization"]
        # A serialized generic observation cannot claim the driver's local proof
        # that no I/O happened to an already unknown external send.
        forged = self.service._prepare_refusal(auth, "E_EVIDENCE_UNAVAILABLE")
        refused = self.service.execute(forged)
        self.assertEqual(refused["error"]["code"], "E_AUTHORITY_REQUIRED")
        template = self.service.prepare_observation(auth, TransportResult(UNKNOWN), command_id="poll-template", idempotency_key="poll-template")
        for index in range(129):
            self.f.now = add_milliseconds(self.f.now, 1)
            poll = deepcopy(template); poll["command_id"] = poll["idempotency_key"] = "poll-" + str(index)
            observed = poll["extensions"][REQUEST_EXTENSION]["value"]["observation"]["value"]
            observed["observed_at"] = deepcopy(self.f.now)
            observed["eligibility_at_observation"]["checked_at"] = deepcopy(self.f.now)
            result = self.service.execute(poll)
            self.assertEqual(result.get("outcome"), "recorded", result)
        self.assertEqual(len(self.service.history(auth)["observations"]), 1)
        key = self.f.storage.get(auth)["body"]["details"]["value"]["delivery_key"]
        self.transport.seen[key] = TransportResult({"status": "delivered", "receipt_id": "eventual-receipt", "at": deepcopy(self.f.now),
            "milestone": "example:delivered", "reason": "transport:accepted"})
        result = self.service.reconcile(auth, command_id="eventual-positive", idempotency_key="eventual-positive")
        self.assertEqual(result.get("outcome"), "delivered", result)
        self.assertEqual(len(self.service.history(auth)["observations"]), 2)
        self.assertEqual(len(self.transport.calls), 1)
        self.assertEqual(len(self.transport.lookups), 1)
