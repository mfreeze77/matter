"""MAT-018 independent context consumption and scoped host dispositions."""

from copy import deepcopy
import unittest

from matter.authority import AuthorityPolicy, CAPABILITIES, CONTROL_KINDS
from matter.contexts import ContextDefinition, ContextService, context_ref
from matter.contracts import ContractError
from matter.controls import ControlService
from matter.dependencies import capture_dependencies, register_dependency, registration_ref, require_current_dependency
from matter.dispositions import DispositionDefinition, DispositionService, disposition_ref
from matter.invalidation import InvalidationHook
from matter.storage import SQLiteStore, StorageError, entity_ref, pin

from integration.helpers import create_command, domain_value, projection_ref, record_input


UNBOUNDED = {"state": "unknown", "reason": "not_applicable"}


class ContextScopeTests(unittest.TestCase):
    def setUp(self):
        from integration.test_assessment_commit import AssessmentCommitTests
        self.fixture = AssessmentCommitTests(methodName="runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        fixture = self.fixture
        fixture.storage.close()
        self.hook = InvalidationHook(clock=lambda: deepcopy(fixture.now))
        self.storage = SQLiteStore(fixture.database, scope_id=fixture.storage.scope_id, transaction_hook=self.hook)
        self.addCleanup(self.storage.close)
        fixture.storage = self.storage
        self.controls = ControlService(self.storage, policy=fixture.controls.policy, clock=lambda: deepcopy(fixture.now))
        fixture.controls = self.controls
        fixture.service = fixture.make_service()
        self.hook.controls = self.controls
        self.contexts = ContextService(self.storage, controls=self.controls)
        self.dispositions = DispositionService(self.storage, controls=self.controls)
        self.sequence = 0

    def definition(self, kind, identity=None, *, version="1.0", content=None, until=None):
        f = self.fixture
        defaults = {
            "purpose": {"objectives": [], "constraints": []},
            "objective": {"statement": "Synthetic objective.", "constraints": []},
            "audience": {"audience_id": identity or "observer", "audience_kind": "human", "purposes": [],
                         "responsibilities": [], "preferences": []},
            "responsibility": {"owner": f.actor, "capabilities": ["write"], "purposes": []},
            "preference": {"preferred_treatment": "quiet", "channels": [], "interruption_budget": domain_value({"limit": 0})}}
        return ContextDefinition({"schema_version": "1.0", "namespace": "example:contexts", "id": identity or kind,
            "semantic_version": version, "kind": kind, "description": "Synthetic explicitly accepted context.",
            "applies_to": [entity_ref(f.subject)], "effective_from": deepcopy(f.now),
            "effective_until": until or deepcopy(UNBOUNDED), "content": content or defaults[kind]})

    def publish(self, definition, *, previous=None, service=None):
        self.sequence += 1
        service = service or self.contexts
        command = service.prepare(definition, command_id=f"context-{self.sequence}", idempotency_key=f"context-key-{self.sequence}",
            actor=self.fixture.actor, authority=entity_ref(self.fixture.authority), previous=previous)
        result = service.commit(command)
        self.assertEqual(result["status"], "success", result)
        address = disposition_ref(definition) if isinstance(definition, DispositionDefinition) else context_ref(self.storage.scope_id, definition)
        return self.storage.get(address), command, result

    def read_token(self, targets):
        targets = list({tuple(entity_ref(ref).items()): entity_ref(ref) for ref in targets}.values())
        return self.controls.capture(actor=self.fixture.actor, authority=entity_ref(self.fixture.authority),
                                     capability="read", targets=targets)

    def select(self, records):
        return self.contexts.capture(self.read_token([self.fixture.subject, *records]), [pin(record) for record in records])

    def consumer(self, identity, *, positive=(), contexts=(), conditions=(), value=None):
        with self.storage.snapshot() as view:
            manifest = capture_dependencies(view, scope_id=self.storage.scope_id, as_of=self.fixture.now,
                positive=list(positive), contexts=list(contexts), time_conditions=list(conditions), controls=self.controls)
        command = create_command(identity, identity + "-transaction", scope_id=self.storage.scope_id,
                                 expected_revisions=manifest.read_pins)
        target = projection_ref(identity, self.storage.scope_id)
        def handler(tx):
            matter = tx.insert(tx.command["body"]["matter"])
            stored = tx.put_projection(target, domain_value(value or {"synthetic": identity}))
            register_dependency(tx, pin(stored), manifest, as_of=self.fixture.now, controls=self.controls)
            return tx.success("created", {"matter": pin(matter)})
        self.assertEqual(self.storage.execute(command, handler)["status"], "success")
        return self.storage.get(target)

    def state(self, target):
        return self.storage.get(registration_ref(target))["value"]["value"]["status"]

    def purpose_and_audiences(self):
        purpose, _, _ = self.publish(self.definition("purpose"))
        observer, _, _ = self.publish(self.definition("audience", "observer"))
        worker, _, _ = self.publish(self.definition("audience", "worker", content={"audience_id": "worker",
            "audience_kind": "host_agent", "purposes": [], "responsibilities": [], "preferences": []}))
        return purpose, observer, worker

    def disposition(self, kind, purpose, audience, *, subject=None, until=None, status="active", decision=None):
        selected = self.select([purpose, audience]).value["components"]
        return DispositionDefinition({"schema_version": "1.0", "namespace": "example:dispositions", "kind": kind,
            "matter": entity_ref(self.fixture.subject), "purpose": {"reference": selected[0]["reference"], "context": pin(purpose)},
            "audience": {"reference": selected[1]["reference"], "context": pin(audience)},
            "subject": subject or pin(self.fixture.source), "effective_from": deepcopy(self.fixture.now),
            "effective_until": until or deepcopy(UNBOUNDED), "reason": "Explicit synthetic host disposition.",
            "decision": decision, "status": status})

    def disposition_token(self, disposition, purpose, audience):
        body = disposition["value"]["value"]["definition"]
        return self.read_token([disposition, purpose, audience, self.fixture.subject, body["subject"]])

    def test_shared_actual_evidence_assessment_has_independent_audience_treatments(self):
        original, _, assessment = self.fixture.publish()
        purpose, observer, worker = self.purpose_and_audiences()
        responsibility, _, _ = self.publish(self.definition("responsibility", "worker-owner", content={
            "owner": {**self.fixture.actor, "id": "host-working-agent"}, "capabilities": ["write"], "purposes": []}))
        quiet, _, _ = self.publish(self.definition("preference", "observer-preferences"))
        hint, _, _ = self.publish(self.definition("preference", "worker-preferences", content={
            "preferred_treatment": "host_hint", "channels": ["host"], "interruption_budget": domain_value({"limit": 1})}))
        human_context = self.select([purpose, observer, quiet])
        worker_context = self.select([purpose, worker, responsibility, hint])
        human = self.consumer("observer-treatment", positive=[pin(assessment)], contexts=human_context.dependencies,
            value={"assessment": pin(assessment), "treatment": "quiet", "reason": "handled_by_owner"})
        agent = self.consumer("worker-treatment", positive=[pin(assessment)], contexts=worker_context.dependencies,
            value={"assessment": pin(assessment), "treatment": "host_hint", "owner": "host-working-agent"})
        self.assertEqual(human["value"]["value"]["assessment"], agent["value"]["value"]["assessment"])
        self.assertNotEqual(human["value"]["value"]["treatment"], agent["value"]["value"]["treatment"])
        self.assertEqual(self.storage.get(pin(assessment)), assessment)
        revised = self.definition("preference", "observer-preferences", version="2.0", content={
            "preferred_treatment": "digest", "channels": ["digest"], "interruption_budget": domain_value({"limit": 1})})
        self.publish(revised, previous=pin(quiet))
        self.assertEqual(self.state(human), "invalidated")
        self.assertEqual(self.state(agent), "current")
        self.assertEqual(self.state(assessment), "current")
        self.assertEqual(self.controls.check(original.token), original.token)
        self.assertEqual(self.storage.get(pin(assessment)), assessment)

    def test_context_version_change_preserves_identity_history_and_exact_assessment_binding(self):
        objective, _, _ = self.publish(self.definition("objective", "objective-a"))
        old_definition = self.definition("purpose", content={"objectives": [self.select([objective]).value["components"][0]["reference"]], "constraints": []})
        purpose, _, _ = self.publish(old_definition)
        selection = self.select([purpose])
        audience = self.definition("audience", "purpose-test-audience")
        audience_record, _, _ = self.publish(audience)
        self.fixture.purpose = selection.value["components"][0]["reference"]
        self.fixture.audience = audience.reference
        _, _, assessment = self.fixture.publish(extra=selection.dependencies)
        new_objective, _, _ = self.publish(self.definition("objective", "objective-b"))
        replacement = self.definition("purpose", version="2.0", content={
            "objectives": [self.select([new_objective]).value["components"][0]["reference"]], "constraints": []})
        updated, _, _ = self.publish(replacement, previous=pin(purpose))
        self.assertEqual(entity_ref(updated), entity_ref(purpose))
        self.assertEqual(self.storage.get(pin(purpose)), purpose)
        self.assertEqual(self.storage.get(pin(assessment)), assessment)
        self.assertEqual(assessment["body"]["purpose"], old_definition.reference)
        self.assertEqual(self.storage.get(pin(self.fixture.subject)), self.fixture.subject)
        self.assertEqual(self.state(assessment), "invalidated")
        with self.assertRaises(StorageError) as error:
            self.contexts.capture(self.read_token([updated, self.fixture.subject]), [pin(purpose)])
        self.assertEqual(error.exception.code, "E_DEPENDENCY_STALE")
        historical = self.contexts.read(self.read_token([updated, self.fixture.subject]), pin(purpose))
        self.assertEqual(historical.value["components"][0]["reference"], old_definition.reference)

    def test_deferral_exact_audience_scope_and_nanosecond_expiry_reconsideration(self):
        purpose, observer, worker = self.purpose_and_audiences()
        until = {"state": "known", "value": "2026-10-10T12:00:00.000000001Z", "precision": "nanosecond"}
        definition = self.disposition("deferral", purpose, observer, until=until)
        deferred, _, _ = self.publish(definition, service=self.dispositions)
        token = self.disposition_token(deferred, purpose, observer)
        selection = self.dispositions.read(token, pin(deferred))
        self.assertTrue(selection.value["active"])
        human = self.consumer("deferred-human", contexts=selection.dependencies, conditions=selection.time_conditions)
        other = self.consumer("unrelated-worker", contexts=self.select([purpose, worker]).dependencies)
        self.fixture.now = deepcopy(until)
        expired = self.dispositions.read(token, pin(deferred))
        self.assertFalse(expired.value["active"])
        with self.storage.snapshot() as view:
            with self.assertRaises(StorageError) as error:
                require_current_dependency(view, registration_ref(human), as_of=until, controls=self.controls)
        self.assertEqual(error.exception.code, "E_DEPENDENCY_STALE")
        self.consumer("expiry-boundary-trigger")
        self.assertEqual(self.state(human), "invalidated")
        self.assertEqual(self.state(other), "current")

    def test_acknowledgement_is_not_agreement_repair_or_lifecycle_change(self):
        purpose, observer, _ = self.purpose_and_audiences()
        source_before, matter_before = self.fixture.source, self.fixture.subject
        definition = self.disposition("acknowledgement", purpose, observer)
        stored, _, _ = self.publish(definition, service=self.dispositions)
        self.assertIsNone(stored["value"]["value"]["definition"]["decision"])
        self.assertEqual(self.storage.get(pin(source_before)), source_before)
        self.assertEqual(self.storage.get(pin(matter_before)), matter_before)
        altered = definition.value
        altered["decision"] = domain_value({"repaired": True})
        with self.assertRaises(StorageError):
            DispositionDefinition(altered)

    def test_authorized_explicit_disposition_supersession_and_exact_retry(self):
        purpose, observer, _ = self.purpose_and_audiences()
        first = self.disposition("decision", purpose, observer, decision=domain_value({"option": "a"}))
        old, command, result = self.publish(first, service=self.dispositions)
        altered = first.value
        altered.update(status="withdrawn", reason="Explicit host correction.")
        changed, _, _ = self.publish(DispositionDefinition(altered), previous=pin(old), service=self.dispositions)
        self.assertEqual(self.storage.get(pin(old)), old)
        self.assertEqual(self.dispositions.commit(command), result)
        self.assertEqual(self.storage.get(disposition_ref(first)), changed)
        current = self.dispositions.read(self.disposition_token(changed, purpose, observer), pin(changed))
        self.assertFalse(current.value["active"])
        with self.assertRaises(StorageError) as error:
            self.publish(first, service=self.dispositions)
        self.assertEqual(error.exception.code, "E_DEPENDENCY_STALE")

    def test_rejection_is_exact_proposal_and_audience_not_all_future_evidence(self):
        purpose, observer, worker = self.purpose_and_audiences()
        proposals = []
        for index in range(2):
            command = create_command(f"proposal-host-{index}", f"proposal-transaction-{index}", scope_id=self.storage.scope_id)
            proposal = record_input("association_proposal", f"bounded-proposal-{index}", scope_id=self.storage.scope_id)
            proposal["body"]["subject"] = pin(self.fixture.source)
            def handler(tx):
                matter = tx.insert(tx.command["body"]["matter"])
                tx.insert(proposal)
                return tx.success("created", {"matter": pin(matter)})
            self.assertEqual(self.storage.execute(command, handler)["status"], "success")
            proposals.append(self.storage.get(entity_ref(proposal)))
        rejected = self.disposition("rejection", purpose, observer, subject=pin(proposals[0]))
        stored, _, _ = self.publish(rejected, service=self.dispositions)
        later = self.disposition("rejection", purpose, observer, subject=pin(proposals[1]))
        unrelated = self.disposition("rejection", purpose, worker, subject=pin(proposals[0]))
        self.assertNotEqual(disposition_ref(rejected), disposition_ref(later))
        self.assertNotEqual(disposition_ref(rejected), disposition_ref(unrelated))
        for absent in (later, unrelated):
            with self.assertRaises(StorageError) as error:
                self.storage.get(disposition_ref(absent))
            self.assertEqual(error.exception.code, "E_NOT_FOUND")
        self.assertTrue(self.dispositions.read(self.disposition_token(stored, purpose, observer), pin(stored)).value["active"])
        self.assertEqual(self.storage.get(pin(proposals[1])), proposals[1])
        self.assertEqual(self.storage.get(pin(self.fixture.source)), self.fixture.source)

    def test_immutable_versions_and_public_component_validation(self):
        definition = self.definition("objective")
        old, _, _ = self.publish(definition)
        altered = definition.value
        altered["content"]["statement"] = "Changed under same version."
        with self.assertRaises(StorageError) as error:
            self.publish(ContextDefinition(altered), previous=pin(old))
        self.assertEqual(error.exception.code, "E_SOURCE_IDENTITY_CONFLICT")
        detached = definition.value
        detached["id"] = "mutated-copy"
        self.assertNotEqual(definition.value["id"], detached["id"])
        with self.assertRaises(AttributeError):
            definition.extra = True
        invalid = definition.value
        invalid["content"]["undeclared"] = True
        with self.assertRaises(ContractError):
            ContextDefinition(invalid)
        original_version = self.select([old]).value["components"][0]["version"]
        next_record, _, _ = self.publish(self.definition("objective", version="2.0"), previous=pin(old))
        reused, _, _ = self.publish(definition, previous=pin(next_record))
        selected = self.select([reused]).value["components"][0]
        self.assertEqual(selected["version"], original_version)
        self.assertEqual(selected["reference"], definition.reference)

    def test_static_target_policy_covers_every_scope_reference_at_prepare_commit_read_replay(self):
        definition = self.definition("purpose")
        slot = context_ref(self.storage.scope_id, definition)
        def restricted(targets):
            return ControlService(self.storage, policy=AuthorityPolicy(self.storage.scope_id,
                actors=[self.fixture.actor], authorities=[pin(self.fixture.authority)], capabilities=CAPABILITIES,
                control_kinds=CONTROL_KINDS, targets=targets), clock=lambda: deepcopy(self.fixture.now))
        narrow = ContextService(self.storage, controls=restricted([slot]))
        with self.assertRaises(StorageError) as error:
            self.publish(definition, service=narrow)
        self.assertEqual(error.exception.code, "E_SCOPE_FORBIDDEN")
        full_controls = restricted([slot, entity_ref(self.fixture.subject)])
        full = ContextService(self.storage, controls=full_controls)
        stored, command, result = self.publish(definition, service=full)
        self.assertEqual(full.commit(command), result)
        token = full_controls.capture(actor=self.fixture.actor, authority=entity_ref(self.fixture.authority),
            capability="read", targets=[slot, entity_ref(self.fixture.subject)])
        self.assertEqual(full.read(token, pin(stored)).value["components"][0]["reference"], definition.reference)
        next_definition = self.definition("purpose", version="2.0")
        prepared = full.prepare(next_definition, command_id="restricted-commit", idempotency_key="restricted-commit",
            actor=self.fixture.actor, authority=entity_ref(self.fixture.authority), previous=pin(stored))
        self.assertEqual(narrow.commit(prepared)["error"]["code"], "E_SCOPE_FORBIDDEN")
        self.assertEqual(self.storage.get(slot), stored)
        self.assertEqual(narrow.commit(command)["error"]["code"], "E_SCOPE_FORBIDDEN")
        with self.assertRaises(StorageError):
            narrow.read(token, pin(stored))

    def test_context_replay_and_read_obey_later_source_scope_read_denial(self):
        from control_helpers import control_command
        from integration.helpers import _in_scope
        definition = self.definition("purpose")
        stored, command, result = self.publish(definition)
        token = self.read_token([stored, self.fixture.subject])
        denied = _in_scope(control_command("deny-context-scope", self.fixture.authority,
            targets=[self.fixture.subject], action="deny", capabilities=["read"], now=self.fixture.now), self.storage.scope_id)
        denied["actor"] = deepcopy(self.fixture.actor)
        denied["body"]["control"]["body"]["actor"] = deepcopy(self.fixture.actor)
        self.assertEqual(self.controls.apply(self.controls.prepare(denied))["status"], "success")
        refused = self.contexts.commit(command)
        self.assertEqual(refused["error"]["code"], "E_AUTHORITY_REQUIRED")
        with self.assertRaises(StorageError):
            self.contexts.read(token, pin(stored))
        self.assertEqual(self.storage.command_receipt(command["idempotency_key"])["result"], result)
        self.assertEqual(self.storage.get(pin(stored)), stored)

    def test_intervals_cross_scope_and_forged_supersession_are_refused(self):
        definition = self.definition("purpose")
        stored, _, _ = self.publish(definition)
        next_definition = self.definition("purpose", version="2.0")
        command = self.contexts.prepare(next_definition, command_id="forged-supersession", idempotency_key="forged-supersession",
            actor=self.fixture.actor, authority=entity_ref(self.fixture.authority), previous=pin(stored))
        command["body"]["control"].pop("supersedes")
        result = self.contexts.commit(command)
        self.assertEqual(result["error"]["code"], "E_AUTHORITY_REQUIRED")
        bad = next_definition.value
        bad["effective_until"] = deepcopy(bad["effective_from"])
        with self.assertRaises(StorageError):
            ContextDefinition(bad)
        bad = next_definition.value
        bad["applies_to"][0]["scope_id"] = "example:foreign"
        with self.assertRaises(StorageError) as error:
            self.publish(ContextDefinition(bad), previous=pin(stored))
        self.assertEqual(error.exception.code, "E_SCOPE_FORBIDDEN")

    def test_context_disposition_history_and_replay_survive_new_store_handle(self):
        purpose, observer, _ = self.purpose_and_audiences()
        disposition, command, result = self.publish(self.disposition("acknowledgement", purpose, observer), service=self.dispositions)
        token = self.disposition_token(disposition, purpose, observer)
        with SQLiteStore(self.fixture.database, scope_id=self.storage.scope_id) as reopened:
            controls = ControlService(reopened, policy=self.controls.policy, clock=lambda: deepcopy(self.fixture.now))
            contexts = ContextService(reopened, controls=controls)
            dispositions = DispositionService(reopened, controls=controls)
            self.assertTrue(dispositions.read(token, pin(disposition)).value["active"])
            self.assertEqual(dispositions.commit(command), result)
            selection = contexts.capture(token, [pin(purpose), pin(observer)])
            self.assertEqual(len(selection.value["components"]), 2)

    def test_nested_public_targets_are_not_hidden_inside_preference_payload(self):
        definition = self.definition("preference", content={"preferred_treatment": "quiet", "channels": [],
            "interruption_budget": domain_value({"related_source": pin(self.fixture.source)})})
        slot = context_ref(self.storage.scope_id, definition)
        narrow_controls = ControlService(self.storage, policy=AuthorityPolicy(self.storage.scope_id,
            actors=[self.fixture.actor], authorities=[pin(self.fixture.authority)], capabilities=CAPABILITIES,
            control_kinds=CONTROL_KINDS, targets=[slot, entity_ref(self.fixture.subject)]),
            clock=lambda: deepcopy(self.fixture.now))
        with self.assertRaises(StorageError) as error:
            self.publish(definition, service=ContextService(self.storage, controls=narrow_controls))
        self.assertEqual(error.exception.code, "E_SCOPE_FORBIDDEN")

    def test_future_objective_interval_is_explicit_and_does_not_authorize_future_work(self):
        definition = self.definition("objective")
        changed = definition.value
        changed["effective_from"] = {"state": "known", "value": "2026-10-11T12:00:00Z", "precision": "second"}
        changed["effective_until"] = {"state": "known", "value": "2026-10-12T12:00:00Z", "precision": "second"}
        stored, _, _ = self.publish(ContextDefinition(changed))
        selected = self.select([stored])
        self.assertFalse(selected.value["components"][0]["active"])
        self.assertEqual(selected.time_conditions[0]["next_check_at"], changed["effective_from"])
        historical_or_future_data = self.contexts.read(self.read_token([stored, self.fixture.subject]), pin(stored),
            at=changed["effective_from"])
        self.assertTrue(historical_or_future_data.value["components"][0]["active"])
        self.assertEqual(self.fixture.now["value"], "2026-10-10T12:00:00Z")
        command = self.contexts.prepare(self.definition("purpose"), command_id="source-cannot-mint-context",
            idempotency_key="source-cannot-mint-context", actor=self.fixture.actor, authority=entity_ref(self.fixture.authority))
        command["body"]["control"]["provenance"]["origin"] = "model"
        with self.assertRaises(ContractError) as error:
            self.contexts.commit(command)
        self.assertIn(error.exception.code, {"E_AUTHORITY_REQUIRED", "E_SCHEMA_INVALID"})

    def test_context_update_race_is_atomic_and_does_not_publish_stale_version(self):
        definition = self.definition("purpose")
        stored, _, _ = self.publish(definition)
        next_definition = self.definition("purpose", version="2.0")
        command = self.contexts.prepare(next_definition, command_id="racing-context", idempotency_key="racing-context",
            actor=self.fixture.actor, authority=entity_ref(self.fixture.authority), previous=pin(stored))
        changed, _, _ = self.publish(self.definition("purpose", version="3.0"), previous=pin(stored))
        result = self.contexts.commit(command)
        self.assertEqual(result["status"], "failure")
        self.assertIn(result["error"]["code"], {"E_DEPENDENCY_STALE", "E_REVISION_CONFLICT"})
        self.assertEqual(self.storage.get(context_ref(self.storage.scope_id, definition)), changed)
        self.assertEqual(self.storage.get(pin(stored)), stored)
