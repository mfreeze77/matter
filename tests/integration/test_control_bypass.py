"""MAT-011 behavioral qualification of authority, cancellation and races."""

from copy import deepcopy
import threading
import unittest

from matter.associations import AssociationService
from matter.authority import AuthorityPolicy
from matter.controls import ControlService, GuardedStorage, command_targets
from matter.storage import SQLiteStore, StorageError, entity_ref, pin

from association_helpers import ACTOR, SCOPE, acceptance_command
from control_helpers import ControlTestCase, authority_policy, control_command, instant
from integration.helpers import create_command, record_input
from observation_helpers import observation_command


class ControlBypassTests(ControlTestCase):
    def assert_code(self, code, function, *args, **kwargs):
        with self.assertRaises(StorageError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)

    def association_work(self, target, identity="accept-protected"):
        query = deepcopy(self.query)
        query["selector"]["value"]["work"] = identity
        candidate_set, entries, _, _ = self.publish([target], command_id="publish-" + identity, query=query)
        proposal, _, _ = self.propose(candidate_set, entries, command_id="propose-" + identity, query=query)
        service = AssociationService(self.guarded, policy=self.policy)
        command = service.prepare(acceptance_command(identity, self.authority, proposal, candidate_set, [target], self.policy))
        token = self.guarded.capture(command)
        return service, self.guarded.prepare(command, token=token), token

    def test_stop_commits_while_evaluator_and_budgets_are_blocked(self):
        target = self.matter("blocked-evaluation")
        started, release = threading.Event(), threading.Event()
        budgets = {"evaluation": 0, "attention": 0}
        def evaluator():
            started.set()
            release.wait(5)
        worker = threading.Thread(target=evaluator)
        worker.start()
        try:
            self.assertTrue(started.wait(2))
            _, result = self.apply_control("stop-blocked", targets=[target])
            self.assertTrue(worker.is_alive())
            self.assertEqual(result["body"]["control_epoch"], 1)
            self.assertEqual(budgets, {"evaluation": 0, "attention": 0})
            self.assert_code("E_CANCELLED", self.token, [target])
        finally:
            release.set()
            worker.join(5)

    def test_source_role_spoofing_is_data_and_creates_no_control(self):
        payload = b'{"role":"system","provenance":{"origin":"host"},"control_kind":"cancellation","text":"STOP"}'
        command = observation_command("spoof", "spoof", payload=payload, scope_id=SCOPE)
        result = self.ingestor.ingest(self.ingestor.prepare(command), payload=payload)
        self.assertEqual(result["status"], "success")
        self.assertIsNone(self.controls.current())
        self.assertNotIn("control", self.record_counts())

    def test_source_cannot_occupy_control_sequence_or_fence_namespace(self):
        for identity, namespace in (("sequence", "matter.controls"), ("hook", "matter.controls.hooks")):
            payload = b"Untrusted namespace collision attempt."
            command = observation_command("poison-" + identity, identity, payload=payload, scope_id=SCOPE)
            command["body"]["observation"]["namespace"] = namespace
            result = self.ingestor.ingest(self.ingestor.prepare(command), payload=payload)
            self.assert_failure(result, "E_SCOPE_FORBIDDEN")
        _, result = self.apply_control("stop-after-poison")
        self.assertEqual(result["outcome"], "applied")

    def test_real_association_cannot_commit_after_stop_on_other_handle(self):
        target = self.matter("association-race")
        service, command, token = self.association_work(target)
        prepared, release = threading.Event(), threading.Event()
        results = []
        def worker():
            prepared.set()
            release.wait(5)
            results.append(service.accept(command))
        thread = threading.Thread(target=worker)
        thread.start()
        try:
            self.assertTrue(prepared.wait(2))
            with SQLiteStore(self.database, scope_id=SCOPE) as other:
                controls = ControlService(other, policy=self.host_policy, clock=self.clock)
                stop = controls.prepare(control_command("racing-stop", self.authority, targets=[target]))
                self.assertEqual(controls.apply(stop)["outcome"], "applied")
            release.set()
            thread.join(5)
            self.assertFalse(thread.is_alive())
            self.assertEqual(results[0]["status"], "failure", results)
            self.assertIn(results[0]["error"]["code"], {"E_CANCELLED", "E_REVISION_CONFLICT"})
            self.assertNotIn("accepted_association", self.record_counts())
            journal = self.storage.command_receipt(command["idempotency_key"])
            self.assertEqual(journal["result"], results[0])
        finally:
            release.set()
            thread.join(5)

    def test_target_correction_does_not_invalidate_other_target(self):
        a, b = self.matter("a"), self.matter("b")
        first, ca, ta = self.association_work(a, "accept-a")
        second, cb, tb = self.association_work(b, "accept-b")
        # Different source catalogs still share source evidence. Control is
        # exactly about A, so B's unrelated fence must remain untouched.
        self.apply_control("correct-a", targets=[a], action="invalidate")
        self.assert_code("E_DEPENDENCY_STALE", self.controls.check, ta)
        self.controls.check(tb)
        self.assertEqual(second.accept(cb)["status"], "success")
        self.assertFalse(any(ref["namespace"] == "matter.controls" and ref["id"] == "sequence" for ref in cb["expected_revisions"]))

    def test_original_token_cannot_be_renewed_by_late_prepare(self):
        target = self.matter("late-prepare")
        service, command, token = self.association_work(target)
        self.apply_control("correction", targets=[target], action="invalidate")
        self.assert_code("E_DEPENDENCY_STALE", self.guarded.prepare, command, token=token)
        fresh = self.guarded.capture(command)
        self.assert_code("E_IDEMPOTENCY_CONFLICT", self.guarded.prepare, command, token=fresh)

    def test_permission_denial_cannot_be_overridden_by_new_token_or_confidence(self):
        target = self.matter("denied")
        self.apply_control("deny-merge", targets=[target], action="deny", capabilities=["merge"])
        self.assert_code("E_AUTHORITY_REQUIRED", self.token, [target], capability="merge")
        low = ControlService(self.storage, policy=authority_policy(self.authority, capabilities=["read"]), clock=self.clock)
        command = control_command("forged-grant", self.authority, action="deny", capabilities=["merge"])
        self.assert_code("E_AUTHORITY_REQUIRED", low.prepare, command)

    def test_scope_policy_refuses_one_shot_targets_and_empty_context(self):
        a, b = self.matter("only-a"), self.matter("outside-b")
        policy = authority_policy(self.authority, targets=[entity_ref(a)])
        with self.storage.snapshot() as view:
            self.assert_code("E_SCHEMA_INVALID", policy.authorize, view, actor=ACTOR,
                             authority=entity_ref(self.authority), targets=iter([entity_ref(b)]), capability="read")
        scoped = ControlService(self.storage, policy=policy, clock=self.clock)
        token = self.token([a], controls=scoped)
        self.assert_code("E_AUTHORITY_REQUIRED", scoped.check, token, targets=[])
        self.assert_code("E_SCOPE_FORBIDDEN", self.token, [b], controls=scoped)

    def test_host_cannot_substitute_narrower_targets_than_actual_command(self):
        a, b = self.matter("expected-a"), self.matter("omitted-b")
        service, command, token = self.association_work(a)
        command["expected_revisions"].append(pin(b))
        self.assert_code("E_AUTHORITY_REQUIRED", self.guarded.prepare, command, token=token)

    def test_exact_replay_is_history_but_read_denial_blocks_success_and_failure_replay(self):
        target = self.matter("replay")
        service, command, token = self.association_work(target)
        success = service.accept(command)
        self.assertEqual(success["status"], "success")
        self.apply_control("stop-replay", targets=[target])
        self.assertEqual(service.accept(command), success)
        second = deepcopy(command)
        second["command_id"], second["idempotency_key"] = "cancelled-attempt", "cancelled-attempt"
        failure = service.accept(second)
        self.assertEqual(failure["status"], "failure")
        self.apply_control("deny-history", targets=[target], action="deny", capabilities=["read"])
        for old in (command, second):
            self.assert_failure(service.accept(old), "E_AUTHORITY_REQUIRED")
        self.assertEqual(self.storage.command_receipt(command["idempotency_key"])["result"], success)
        self.assertEqual(self.storage.command_receipt(second["idempotency_key"])["result"], failure)

    def test_shorter_stop_or_deny_never_implicitly_releases_indefinite_restriction(self):
        target = self.matter("sticky")
        only_stop = ControlService(self.storage, policy=authority_policy(self.authority, kinds=["cancellation"]), clock=self.clock)
        first = only_stop.prepare(control_command("forever", self.authority, targets=[target]))
        first_result = only_stop.apply(first)
        second = only_stop.prepare(control_command("short", self.authority, targets=[target], until=instant("2026-10-10T12:02:00Z")))
        self.assertEqual(only_stop.apply(second)["status"], "success")
        self.clock.value = instant("2026-10-10T12:03:00Z")
        self.assert_code("E_CANCELLED", self.token, [target], controls=only_stop)
        self.assertEqual(self.controls.current(entity_ref(target))["value"]["value"]["cancellations"], [first_result["body"]["control"]])

    def test_narrow_release_cannot_remove_an_overlapping_broader_restriction(self):
        for action, release, capability, code in (("cancel", "resume", "write", "E_CANCELLED"),
                                                  ("deny", "allow", "read", "E_AUTHORITY_REQUIRED")):
            a, b = self.matter(action + "-a"), self.matter(action + "-b")
            caps = [capability] if action == "deny" else []
            self.apply_control(action + "-broad", targets=[a, b], action=action, capabilities=caps,
                               until=instant("2026-10-10T12:10:00Z"))
            narrow = ControlService(self.storage, policy=authority_policy(self.authority, targets=[entity_ref(a)]), clock=self.clock)
            local = narrow.prepare(control_command(action + "-local", self.authority, targets=[a], action=action,
                                   capabilities=caps, until=instant("2026-10-10T12:20:00Z")))
            applied = narrow.apply(local)
            undo = narrow.prepare(control_command(action + "-local-release", self.authority, targets=[a], action=release,
                                  capabilities=caps, supersedes=[applied["body"]["control"]]))
            self.assertEqual(narrow.apply(undo)["status"], "success")
            self.assert_code(code, self.token, [a], capability=capability)
            self.assert_code(code, self.token, [b], capability=capability)
        b = self.matter("denial-sticky")
        self.apply_control("deny-forever", targets=[b], action="deny", capabilities=["read"])
        self.apply_control("deny-short", targets=[b], action="deny", capabilities=["read"], until=instant("2026-10-10T12:04:00Z"))
        self.clock.value = instant("2026-10-10T12:05:00Z")
        self.assert_code("E_AUTHORITY_REQUIRED", self.token, [b])

    def test_release_requires_exact_current_restriction_and_cannot_release_root_from_target(self):
        target = self.matter("release")
        _, root = self.apply_control("root-stop")
        self.assert_code("E_SCOPE_FORBIDDEN", self.controls.prepare,
            control_command("wrong-release", self.authority, targets=[target], action="resume", supersedes=[root["body"]["control"]]))
        self.assert_code("E_AUTHORITY_REQUIRED", self.controls.prepare,
            control_command("no-basis", self.authority, action="resume"))
        self.apply_control("release-root", action="resume", supersedes=[root["body"]["control"]])
        self.token([target])

    def test_historical_time_cannot_bypass_current_stop(self):
        target = self.matter("time-bypass")
        token = self.token([target])
        self.apply_control("time-stop", targets=[target])
        self.assert_code("E_POLICY_INVALID", self.controls.capture, actor=ACTOR, authority=entity_ref(self.authority),
                         capability="read", targets=[entity_ref(target)], as_of=instant("2026-10-09T12:00:00Z"))
        self.assert_code("E_CANCELLED", self.controls.read, token, entity_ref(target))

    def test_clock_regression_cannot_make_committed_stop_or_denial_inactive(self):
        for action, capability in (("cancel", "write"), ("deny", "read")):
            self.clock.value = instant()
            target = self.matter("clock-" + action)
            self.apply_control("clock-control-" + action, targets=[target], action=action,
                               capabilities=[capability] if action == "deny" else [])
            self.clock.value = instant("2026-10-10T11:59:59Z")
            self.assert_code("E_POLICY_INVALID", self.token, [target], capability=capability)

    def test_idempotency_duplicate_identity_conflict_and_restart(self):
        target = self.matter("restart")
        command, first = self.apply_control("durable-stop", targets=[target])
        self.assertEqual(self.controls.apply(command), first)
        duplicate = deepcopy(command)
        duplicate.update(command_id="new-redelivery", idempotency_key="new-redelivery", expected_revisions=[])
        result = self.controls.apply(self.controls.prepare(duplicate))
        self.assertEqual(result["outcome"], "duplicate")
        self.assertEqual(result["body"], first["body"])
        changed = deepcopy(duplicate)
        changed.update(command_id="conflict", idempotency_key="conflict")
        changed["body"]["control"]["body"]["effect"]["value"]["reason"] = "Changed payload."
        self.assert_code("E_SOURCE_IDENTITY_CONFLICT", self.controls.prepare, changed)
        with SQLiteStore(self.database, scope_id=SCOPE) as restarted:
            service = ControlService(restarted, policy=self.host_policy, clock=self.clock)
            self.assertEqual(service.apply(command), first)
            self.assert_code("E_CANCELLED", self.token, [target], controls=service)

    def test_hooks_are_explicit_and_failure_does_not_mask_durable_effect(self):
        calls = []
        def broken(control):
            calls.append(control["id"])
            raise RuntimeError("Sensitive host details are not recorded.")
        controls = ControlService(self.storage, policy=self.host_policy, clock=self.clock, hooks={"cancel-worker": broken})
        command = controls.prepare(control_command("hook-stop", self.authority))
        result = controls.apply(command)
        self.assertEqual(calls, [])
        self.assertEqual(result["outcome"], "applied")
        reports = controls.run_hooks(result["body"]["control"], attempt_id="first")
        self.assertEqual(reports[0]["status"], "failed")
        self.assertEqual(reports[0]["error_type"], "RuntimeError")
        self.assertEqual(len(calls), 1)
        self.assertEqual(controls.run_hooks(result["body"]["control"], attempt_id="first"), reports)
        self.assertEqual(len(calls), 1)
        controls.run_hooks(result["body"]["control"], attempt_id="explicit-retry")
        self.assertEqual(len(calls), 2)
        self.assertEqual(controls.apply(command), result)

    def test_temporary_release_is_refused_and_finite_restriction_expiry_invalidates_token(self):
        target = self.matter("expiry")
        _, denied = self.apply_control("temporary-denial", targets=[target], action="deny", capabilities=["read"],
                                       until=instant("2026-10-10T12:02:00Z"))
        work = self.token([target], capability="write")
        self.assert_code("E_POLICY_INVALID", self.controls.prepare, control_command("temporary-release", self.authority,
            targets=[target], action="allow", capabilities=["read"], supersedes=[denied["body"]["control"]],
            until=instant("2026-10-10T12:01:00Z")))
        self.clock.value = instant("2026-10-10T12:03:00Z")
        self.assert_code("E_DEPENDENCY_STALE", self.controls.check, work)
        self.token([target], capability="read")

    def test_evaluation_receipt_cannot_be_admitted_as_host_authority(self):
        command = create_command("fake-receipt", "fake-receipt-matter", scope_id=SCOPE)
        fake = deepcopy(self.authority)
        fake.pop("creation_receipt")
        fake["id"] = "evaluation-only"
        fake["body"]["stage"] = "evaluation"
        def handler(tx):
            tx.insert(fake)
            matter = tx.insert(tx.command["body"]["matter"])
            return tx.success("created", {"matter": pin(matter)})
        self.assertEqual(self.storage.execute(command, handler)["status"], "success")
        record = self.storage.get(entity_ref(fake))
        policy = AuthorityPolicy(SCOPE, actors=[ACTOR], authorities=[pin(record)], capabilities=["read"], control_kinds=["cancellation"])
        controls = ControlService(self.storage, policy=policy, clock=self.clock)
        self.assert_code("E_AUTHORITY_REQUIRED", controls.prepare, control_command("fake-control", record))

    def test_invalid_control_scope_effect_and_future_time_fail_before_mutation(self):
        variants = []
        bad = control_command("mismatch", self.authority)
        bad["body"]["control"]["body"]["actor"]["id"] = "another-actor"
        variants.append((bad, "E_SCOPE_FORBIDDEN"))
        bad = control_command("future", self.authority, now=instant("2026-10-11T12:00:00Z"))
        variants.append((bad, "E_POLICY_INVALID"))
        bad = control_command("unknown-effect", self.authority)
        bad["body"]["control"]["body"]["effect"]["schema"]["digest"] = "0" * 64
        variants.append((bad, "E_POLICY_INVALID"))
        for value, code in variants:
            self.assert_code(code, self.controls.prepare, value)
        self.assertIsNone(self.controls.current())

    def test_control_atomicity_and_lost_commit_acknowledgement(self):
        for stage in ("before_commit", "after_commit"):
            target = self.matter(stage)
            command = self.controls.prepare(control_command("crash-" + stage, self.authority, targets=[target]))
            def fault(point):
                if point == stage:
                    raise OSError("Synthetic storage fault.")
            with SQLiteStore(self.database, scope_id=SCOPE, fault_hook=fault) as faulty:
                service = ControlService(faulty, policy=self.host_policy, clock=self.clock)
                self.assert_failure(service.apply(command), "E_STORAGE_UNAVAILABLE")
            if stage == "before_commit":
                self.assertIsNone(self.controls.current(entity_ref(target)))
            else:
                self.assertIsNotNone(self.controls.current(entity_ref(target)))
            recovered = self.controls.apply(command)
            self.assertEqual(recovered["outcome"], "applied")
            self.assertEqual(self.controls.apply(command), recovered)

    def test_concurrent_hook_attempt_is_claimed_once_and_started_is_not_blindly_retried(self):
        entered, release = threading.Event(), threading.Event()
        calls, reports = [], []
        def hook(control):
            calls.append(control["id"])
            entered.set()
            release.wait(5)
        controls = ControlService(self.storage, policy=self.host_policy, clock=self.clock, hooks={"worker": hook})
        result = controls.apply(controls.prepare(control_command("hook-concurrent", self.authority)))
        reference = result["body"]["control"]
        thread = threading.Thread(target=lambda: reports.extend(controls.run_hooks(reference, attempt_id="one")))
        thread.start()
        try:
            self.assertTrue(entered.wait(3))
            second = controls.run_hooks(reference, attempt_id="one")
            self.assertEqual(second[0]["status"], "started")
            self.assertEqual(len(calls), 1)
        finally:
            release.set()
            thread.join(5)
        self.assertEqual(reports[0]["status"], "succeeded")
        self.assertEqual(len(calls), 1)

    def test_dispatch_authorization_is_fenced_and_completed_transport_stays_factual(self):
        target = self.matter("dispatch-target")
        token = self.token([target], capability="delivery")
        command = create_command("authorize-dispatch", "authorization-record", scope_id=SCOPE)
        command.update(actor=deepcopy(ACTOR), authority=entity_ref(self.authority))
        command["expected_revisions"] = [token["authority"]]
        delivery_ref = {"scope_id": SCOPE, "namespace": "example:delivery", "record_type": "receipt", "id": "actual-delivery"}
        def authorize(tx):
            self.controls.authorize_dispatch(tx, token, targets=[entity_ref(target)])
            receipt = record_input("receipt", delivery_ref["id"], scope_id=SCOPE)
            receipt["namespace"] = delivery_ref["namespace"]
            # Synthetic host transport evidence represents a completed send;
            # production adapters own their authorization-to-I/O boundary.
            receipt["body"].update(stage="delivered", outcome="example:transport_success")
            tx.insert(receipt)
            matter = tx.insert(tx.command["body"]["matter"])
            return tx.success("created", {"matter": pin(matter)})
        result = self.storage.execute(command, authorize)
        self.assertEqual(result["status"], "success")
        delivered = self.storage.get(delivery_ref)
        self.apply_control("stop-after-delivery", targets=[target])
        self.assertEqual(self.storage.get(delivery_ref), delivered)
        late = create_command("late-dispatch", "late-record", scope_id=SCOPE)
        late.update(actor=deepcopy(ACTOR), authority=entity_ref(self.authority), expected_revisions=[token["authority"]])
        failed = self.storage.execute(late, authorize)
        self.assertEqual(failed["status"], "failure")
        self.assertIn(failed["error"]["code"], {"E_CANCELLED", "E_REVISION_CONFLICT"})


if __name__ == "__main__":
    unittest.main()
