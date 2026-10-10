"""Actual MAT-011 controls around detached MAT-012 evaluation attempts.

Only the synthetic host fixture persists a predecessor receipt/judgment. That
fixture is not an assessment commit service or a qualification of MAT-015.
"""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Event

from matter.authority import AuthorityPolicy, CAPABILITIES, CONTROL_KINDS
from matter.canonical import canonical_digest
from matter.controls import ControlService
from matter.evaluators import QualificationRegistry, admit_result, check_input_current
from matter.storage import SQLiteStore, StorageError, entity_ref, pin

from control_helpers import control_command
from integration.helpers import _in_scope, create_command, domain_value, record_input
from rule_helpers import RuleTestCase, NOW


class RuleControlIntegrationTests(RuleTestCase):
    def setUp(self):
        super().setUp()
        self.scope = self.storage.scope_id
        self.actor = {"scope_id": self.scope, "namespace": "example:host", "id": "reviewer"}
        self.authority = self._host_authority()
        self.policy = AuthorityPolicy(self.scope, actors=[self.actor], authorities=[pin(self.authority)],
            capabilities=CAPABILITIES, control_kinds=CONTROL_KINDS)
        self.controls = ControlService(self.storage, policy=self.policy, clock=lambda: deepcopy(NOW))
        other = SQLiteStore(self.database, scope_id=self.scope)
        self.addCleanup(other.close)
        self.control_writer = ControlService(other, policy=self.policy, clock=lambda: deepcopy(NOW))
        self.contexts = {}
        self.context_checks = []

    def _host_authority(self):
        command = create_command("rule-control-host-bootstrap", "rule-control-host-record", scope_id=self.scope)
        authority = record_input("receipt", "rule-control-host-authority", scope_id=self.scope)
        authority["namespace"] = "example:host"
        authority["provenance"]["origin"] = "host"
        authority["body"].update(stage="authority", operation_id=command["command_id"],
            outcome="example:granted", evidence=[], details=domain_value({"synthetic": "explicit host admission"}))

        def handler(tx):
            tx.insert(authority)
            stored = tx.insert(tx.command["body"]["matter"])
            return tx.success("created", {"matter": pin(stored)})

        result = self.storage.execute(command, handler)
        self.assertEqual(result["status"], "success", result)
        return self.storage.get(entity_ref(authority))

    def token(self, *targets, capability="assessment"):
        return self.controls.capture(actor=self.actor, authority=entity_ref(self.authority),
            capability=capability, targets=[entity_ref(target) for target in targets])

    def control(self, identity, *, targets, action="cancel", capabilities=()):
        command = _in_scope(control_command(identity, self.authority, targets=targets,
            action=action, capabilities=capabilities), self.scope)
        result = self.control_writer.apply(self.control_writer.prepare(command))
        self.assertEqual(result["status"], "success", result)
        return result

    def retain_context(self, prepared):
        self.contexts[prepared.digest] = prepared.control_token
        return prepared

    def resolve_context(self, view, *, input_digest, token_digest, control_epoch, as_of):
        token = self.contexts.get(input_digest)
        if (token is None or token_digest != canonical_digest(token, "matter.evaluation-control.v1")
                or token["control_epoch"] != control_epoch):
            raise StorageError("E_POLICY_INVALID", "The exact original host token was not retained.")
        self.context_checks.append(input_digest)
        return self.controls.require_current(view, token, capability=token["capability"],
            targets=token["targets"], as_of=as_of)

    def current(self, prepared, *, as_of):
        with self.storage.snapshot() as view:
            # Reuse this snapshot; ControlService.check would open a nested
            # operation on the same SQLite handle rather than share this read.
            return check_input_current(view, prepared, as_of=as_of,
                check_control_context=lambda **context: self.resolve_context(view, **context))

    def persist_historical_attempt(self, bundle):
        """Explicit fixture host stores immutable history before any correction."""
        judgment = bundle.judgment
        command = create_command("persist-" + judgment["id"], "host-record-" + judgment["id"],
            scope_id=self.scope)

        def handler(tx):
            tx.insert(bundle.receipt)
            tx.insert(judgment)
            stored = tx.insert(tx.command["body"]["matter"])
            return tx.success("created", {"matter": pin(stored)})

        result = self.storage.execute(command, handler)
        self.assertEqual(result["status"], "success", result)
        return self.storage.get(entity_ref(judgment))

    def test_actual_stop_during_deterministic_binding_discards_semantic_output(self):
        entered, release = Event(), Event()
        seen = []

        def blocked(request):
            seen.append(deepcopy(request))
            entered.set()
            if not release.wait(timeout=10):
                raise TimeoutError("The fixture host did not release the binding.")
            return self.response()

        binding = self.binding(blocked)
        rule = self.rule(binding)
        token = self.token(self.subject, self.source)
        prepared = self.packet(rule, control_token=token)
        runner = self.runner([rule], [binding])
        before = self.record_counts()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(runner.evaluate, prepared, judgment_id="cancelled-rule-result",
                attempt_id="cancelled-rule-attempt", check_control=self.controls.check)
            try:
                self.assertTrue(entered.wait(timeout=10), "The binding did not begin.")
                self.control("stop-during-rule", targets=[self.subject])
            finally:
                release.set()
            result = future.result(timeout=10)

        body = result.judgment["body"]
        self.assertEqual(body["execution_status"], "cancelled")
        self.assertEqual(body["failure"]["code"], "E_CANCELLED")
        self.assertNotIn("semantic_output", body)
        self.assertNotIn("evaluation_status", body)
        self.assertEqual(body["proposed_consequences"], [])
        events = result.receipt["body"]["details"]["value"]["events"]
        self.assertIn({"stage": "binding", "status": "completed"}, events)
        self.assertEqual(events[-1], {"stage": "post_gate", "status": "cancelled", "code": "E_CANCELLED"})
        self.assertEqual(prepared.control_token, token)
        self.assertNotIn("control_token", seen[0]["input"]["packet"])
        self.assertNotIn("authority", seen[0]["input"]["packet"])
        self.assertEqual(self.record_counts().get("judgment", 0), before.get("judgment", 0))

    def test_original_upstream_control_is_stale_despite_fresh_equal_epoch_downstream(self):
        first_binding = self.binding(identity="upstream")
        first_rule = self.rule(first_binding, identity="upstream")
        original = self.retain_context(self.packet(first_rule,
            control_token=self.token(self.subject, self.source)))
        first = self.runner([first_rule], [first_binding]).evaluate(original,
            judgment_id="upstream-result", attempt_id="upstream-attempt", check_control=self.controls.check)
        stored = self.persist_historical_attempt(first)
        stored_before = deepcopy(stored)
        other = self.make_matter("subject-b")
        self.control("correct-upstream-a", targets=[self.subject], action="invalidate")

        downstream_token = self.token(other, self.source)
        self.assertEqual(original.control_token["control_epoch"], downstream_token["control_epoch"])
        self.controls.check(downstream_token)
        downstream_calls = []

        def downstream(request):
            downstream_calls.append(request)
            return self.response()

        binding = self.binding(downstream, identity="downstream")

        def needs_upstream(definition):
            definition["dependencies"] = [{"rule": first_rule.reference, "accepted_labels": ["example:positive"],
                "accepted_statuses": ["applicable"], "require_qualified": True}]

        rule = self.rule(binding, identity="downstream", change=needs_upstream)
        packet = self.retain_context(self.packet(rule, control_token=downstream_token, upstream=[
            {"reference": pin(stored), "expected_input": original.value, "available_at": NOW}]))
        result = self.runner([first_rule, rule], [first_binding, binding]).evaluate(packet,
            judgment_id="downstream-result", attempt_id="downstream-attempt",
            check_control=self.controls.check, check_current=self.current)
        self.assertEqual(result.judgment["body"]["failure"]["code"], "E_DEPENDENCY_STALE")
        self.assertNotIn("semantic_output", result.judgment["body"])
        self.assertEqual(downstream_calls, [])
        self.assertIn(original.digest, self.context_checks)
        self.assertEqual(self.storage.get(entity_ref(stored)), stored_before)
        self.assert_code("E_DEPENDENCY_STALE", admit_result, stored, first_rule, binding=first_binding,
            schemas=self.schemas, expected_input=original, as_of=NOW,
            accepted_labels=["example:positive"], check_current=self.current)

    def test_qualified_recording_cannot_override_current_assessment_denial(self):
        initial = self.recorded()
        rule = self.rule(initial)
        packet = self.packet(rule, control_token=self.token(self.subject, self.source))
        certificate = self.certificate(rule, initial)
        response = self.response(qualification={"status": "qualified", "certificate": certificate["reference"]})
        binding = self.recorded([{"input_digest": packet.digest, "response": response}])
        runner = self.runner([rule], [binding], qualifications=QualificationRegistry([certificate]))
        admitted = runner.evaluate(packet, judgment_id="qualified-before-denial", attempt_id="qualified-before-attempt",
            check_control=self.controls.check)
        self.assertEqual(admitted.judgment["body"]["qualification"]["status"], "qualified")
        self.control("deny-rule-assessment", targets=[self.subject], action="deny", capabilities=["assessment"])
        denied = runner.evaluate(packet, judgment_id="qualified-after-denial", attempt_id="qualified-after-attempt",
            check_control=self.controls.check)
        self.assertEqual(denied.judgment["body"]["failure"]["code"], "E_AUTHORITY_REQUIRED")
        self.assertNotIn("semantic_output", denied.judgment["body"])
        self.assertEqual(denied.judgment["body"]["qualification"], {"status": "unknown"})
        self.assertFalse(denied.receipt["body"]["details"]["value"]["called"])

    def test_host_read_gate_refuses_new_packet_after_read_permission_revocation(self):
        token = self.token(self.source, capability="read")
        controls = self.controls

        class AuthorizedReadView:
            def get(self, reference):
                return controls.read(token, reference)

        binding = self.binding()
        rule = self.rule(binding)
        prepared = self.packet(rule, view=AuthorizedReadView())
        self.assertEqual(len(prepared.value["packet"]["evidence"]), 1)
        self.control("deny-rule-source-read", targets=[self.source], action="deny", capabilities=["read"])
        self.assert_code("E_AUTHORITY_REQUIRED", self.packet, rule, view=AuthorizedReadView())
        self.assertEqual(self.storage.get(entity_ref(self.source)), self.source)
        self.assertEqual(self.calls, [])
