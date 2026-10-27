"""Synthetic delivery fixtures over the actual assessment/attention services."""
from copy import deepcopy
import unittest

from matter.budgets import BudgetDefinition, BudgetService
from matter.delivery import DeliveryService
from matter.outbox import DestinationDefinition, TransportCapabilities, TransportResult
from matter.storage import entity_ref, pin
from integration import test_audience_attention as attention_fixture
from integration.helpers import _in_scope, fixture, create_command
from rule_helpers import EARLY, NOW, LATE, component


class SyntheticTransport:
    def __init__(self, *, idempotency=None, lookup=None):
        self.capabilities = TransportCapabilities({"namespace": "synthetic", "id": "transport", "version": "1.0",
            "producer": component("host-transport"), "success_milestone": "example:delivered",
            "idempotency": idempotency, "receipt_lookup": lookup})
        self.calls, self.lookups, self.seen = [], [], {}
        self.callback = None
    def send(self, *, destination, delivery_key, content, authorization):
        self.calls.append((delivery_key, content))
        if self.callback is not None: return self.callback(destination=destination, delivery_key=delivery_key, content=content, authorization=authorization)
        value = TransportResult({"status": "delivered", "receipt_id": "receipt-" + str(len(self.calls)),
            "at": authorization["body"]["details"]["value"]["authorized_at"], "milestone": "example:delivered", "reason": "transport:accepted"})
        self.seen[delivery_key] = value
        return value
    def lookup(self, *, destination, delivery_key):
        self.lookups.append(delivery_key)
        return self.seen.get(delivery_key, TransportResult({"status": "not_found", "receipt_id": None,
            "at": {"state": "unknown", "reason": "not_reported"}, "milestone": None, "reason": "transport:not_found"}))


class DeliveryFixture(unittest.TestCase):
    def setUp(self):
        self.a = attention_fixture.AudienceAttentionTests(methodName="runTest")
        self.a.setUp(); self.addCleanup(self.a.doCleanups)
        self.f = self.a.f
        self.transport = SyntheticTransport()
        bootstrap = create_command("destination-bootstrap", "destination-permission", scope_id=self.f.storage.scope_id)
        def publish_destination(tx):
            stored = tx.insert(tx.command["body"]["matter"])
            return tx.success("created", {"matter": pin(stored)})
        result = self.f.storage.execute(bootstrap, publish_destination)
        self.assertEqual(result["status"], "success")
        self.destination_permission = self.f.storage.get(result["body"]["matter"])
        self.destination = DestinationDefinition({"namespace": "synthetic", "id": "notification", "version": "1.0",
            "audience": self.a.audience_ref, "permission_target": entity_ref(self.destination_permission), "transport": self.transport.capabilities.reference})
        self.definition = BudgetDefinition({"schema_version": "1.0", "namespace": "synthetic", "id": "delivery-attention", "semantic_version": "1.0",
            "kind": "attention", "window": {"start": EARLY, "end": LATE, "bounds": "closed_open"},
            "limits": {"deliveries": 10, "interruption_units": 10}, "units": {"deliveries": "synthetic:deliveries", "interruption_units": "synthetic:interruptions"},
            "description": "Synthetic delivery quota, distinct from resource work."})
        self.budgets = BudgetService(self.f.storage, definitions=[self.definition], controls=self.f.controls, clock=lambda: deepcopy(self.f.now))
        self.service = self.make_service()
        self.assessment, self.claim, self.source, self.occurrence = self.a.assess("repeated-agenda-mention")
        self.decision_value, self.decision, self.attention_command, _ = self.a.evaluate(self.assessment)
        self.token = self.f.controls.capture(actor=self.f.actor, authority=entity_ref(self.f.authority), capability="delivery",
            targets=[*self.a.targets(self.assessment), entity_ref(self.destination_permission)])
        self.sequence = 0
    def make_service(self, *, storage=None, attention=None, budgets=None, controls=None, transport=None):
        return DeliveryService(storage or self.f.storage, payloads=self.f.payloads, attention=attention or self.a.service,
            budgets=budgets or self.budgets, controls=controls or self.f.controls, destinations=[self.destination],
            transports=[transport or self.transport], clock=lambda: deepcopy(self.f.now))
    def prepare(self, identity=None, *, content=b"Synthetic agenda item: a declared condition needs attention.\n", service=None):
        self.sequence += 1
        command = _in_scope(fixture("commands/prepare_delivery.json"), self.f.storage.scope_id)
        command.update(command_id=identity or "delivery-intent-" + str(self.sequence), idempotency_key="queue-" + (identity or str(self.sequence)),
            actor=self.f.actor, authority=entity_ref(self.f.authority), expected_revisions=[])
        return (service or self.service).prepare(command, decision=pin(self.decision), attention_command=self.attention_command,
            token=self.token, destination=self.destination, content=content, budget=self.definition,
            amounts={"deliveries": 1, "interruption_units": 1}, expires_at=LATE)
    def enqueue(self, **kwargs):
        command = self.prepare(**kwargs)
        result = self.service.execute(command)
        self.assertEqual(result["outcome"], "ready", result)
        return result["body"]["intent"], command, result

    def authorize(self, intent=None, *, worker="worker", identity="work", lease_ms=10000):
        from matter.outbox import RESULT_EXTENSION
        if intent is None: intent, _, _ = self.enqueue()
        claim = self.service.prepare_claim(intent, token=self.token, worker=worker, lease_ms=lease_ms,
            command_id="claim-" + identity, idempotency_key="claim-" + identity)
        result = self.service.execute(claim)
        self.assertEqual(result.get("outcome"), "leased", result)
        lease = result["extensions"][RESULT_EXTENSION]["value"]["lease"]
        command = self.service.prepare_authorize(intent, token=self.token, lease=lease, attempt_id="attempt-" + identity,
            command_id="auth-" + identity, idempotency_key="auth-" + identity)
        return intent, lease, command

    def control(self, identity, *, target=None, action="cancel", capabilities=()):
        from control_helpers import control_command
        command = _in_scope(control_command(identity, self.f.authority, targets=[target or self.f.subject],
            action=action, capabilities=capabilities, now=self.f.now), self.f.storage.scope_id)
        command["actor"] = deepcopy(self.f.actor)
        command["body"]["control"]["body"]["actor"] = deepcopy(self.f.actor)
        result = self.f.controls.apply(self.f.controls.prepare(command))
        self.assertEqual(result["status"], "success", result)
        return result

    def restart_service(self):
        """Close original backend and reconstruct actual service ports on disk."""
        from copy import copy
        from matter.controls import ControlService
        from matter.storage import SQLiteStore
        self.f.storage.close()
        storage = SQLiteStore(self.f.database, scope_id=self.f.storage.scope_id)
        self.addCleanup(storage.close)
        controls = ControlService(storage, policy=self.f.controls.policy, clock=lambda: deepcopy(self.f.now))
        assessments = copy(self.a.service.assessments); assessments.storage = storage; assessments.controls = controls
        attention = copy(self.a.service); attention.storage = storage; attention.controls = controls; attention.assessments = assessments
        budgets = BudgetService(storage, definitions=[self.definition], controls=controls, clock=lambda: deepcopy(self.f.now))
        self.service = self.make_service(storage=storage, attention=attention, budgets=budgets, controls=controls)
        self.f.storage = storage
        return self.service
