"""MAT-017 synthetic episodes through real claims, grouping, assessments and SQLite."""

from copy import deepcopy
import unittest
from unittest.mock import patch

from matter.assessments import AssessmentService
from matter.authority import AuthorityPolicy, CAPABILITIES, CONTROL_KINDS
from matter.canonical import canonical_bytes
from matter.claims import ClaimService
from matter.controls import ControlService, command_targets
from matter.dependencies import (capture_dependencies, capture_freshness, register_dependency,
                                 registration_ref, require_freshness)
from matter.invalidation import InvalidationHook
from matter.lifecycle import LifecycleDefinition, LifecycleService, lifecycle_ref, lifecycle_schema
from matter.observations import ObservationIngestor
from matter.occurrences import OccurrenceService
from matter.planner import RulePlan
from matter.profiles import ProfileDefinition, ProfileRegistry
from matter.rules import SchemaRegistry
from matter.storage import SQLiteStore, StorageError, entity_ref, pin

from claim_helpers import claim_command
from control_helpers import control_command
from integration.helpers import _in_scope, create_command, domain_value, fixture, projection_ref
from integration import test_assessment_commit as assessment_fixture
from observation_helpers import known_time, observation_command
from occurrence_helpers import declared, grouping_command, grouping_policy, occurrence_input
from rule_helpers import NOW, EARLY, LATE, component, schema


FUTURE = known_time("2027-01-01T00:00:00Z")


class LifecycleEpisodes(unittest.TestCase):
    def setUp(self):
        # Compose the existing actual publication fixture without inheriting
        # its test methods or replacing its services with mock authorities.
        f = self.f = assessment_fixture.AssessmentCommitTests("test_atomic_children_current_pointer_restart_and_exact_retry")
        f.setUp()
        self.addCleanup(f.doCleanups)
        self.hook = InvalidationHook(clock=lambda: deepcopy(f.now))
        scope = f.storage.scope_id
        f.storage.close()
        f.storage = SQLiteStore(f.database, scope_id=scope, transaction_hook=self.hook)
        self.addCleanup(f.storage.close)
        f.controls = ControlService(f.storage, policy=f.controls.policy, clock=lambda: deepcopy(f.now))
        self.hook.controls = f.controls
        f.claims = ClaimService(f.storage)
        f.ingestor = ObservationIngestor(f.storage, f.payloads)
        self.occurrences = OccurrenceService(f.storage, grouping_policy=grouping_policy())
        self.claim_schema = schema("lifecycle-condition", {
            "condition": {"type": "object", "additionalProperties": False,
                "properties": {"key": {"type": "string"}, "circumstance": {"type": "string"}},
                "required": ["key", "circumstance"]},
            "signal": {"enum": ["present", "recovered", "retracted"]},
            "confidence": {"type": "string"},
        }, ["condition", "signal"])
        f.schemas = SchemaRegistry([f.input_schema, f.output_schema, f.proposal_schema, self.claim_schema, lifecycle_schema()])
        self.definition = self.make_definition()
        self.install_profile(self.definition)
        self.public = {canonical_bytes(entity_ref(f.subject)): entity_ref(f.subject),
                       canonical_bytes(entity_ref(f.source)): entity_ref(f.source)}
        self.sequence = 0
        self.condition_a = {"key": "a", "circumstance": "required-operation"}
        self.condition_b = {"key": "b", "circumstance": "required-operation"}

    def make_definition(self, *, change=None):
        def edge(identity, trigger, before, after, signal, status="supported"):
            return {"id": identity, "semantic_version": "1.0", "description": "Synthetic explicit lifecycle edge.",
                "from_states": before, "to_state": after, "trigger": trigger, "claim_schema": self.claim_schema.reference,
                "predicate": "example:condition", "condition_pointer": "/condition", "signal_pointer": "/signal",
                "accepted_signals": [signal], "assessment_statuses": [status], "assessment_states": ["complete"],
                "requires_decision": False, "allowed_origins": ["source", "host", "system"],
                "effective_time": "claim_start", "allow_past_effective": True}
        value = {"schema_version": "1.0", "namespace": "example", "id": "episode-lifecycle", "semantic_version": "1.0",
            "description": "Synthetic condition correspondence; no domain rule imported.",
            "states": [{"name": "example:unknown", "role": "unknown"}, {"name": "example:open", "role": "open"},
                       {"name": "example:resolved", "role": "resolved"}], "initial_state": "example:unknown",
            "edges": [edge("establish", "establish", ["example:unknown"], "example:open", "present"),
                      edge("resolve", "resolution", ["example:open"], "example:resolved", "recovered"),
                      edge("recur", "recurrence", ["example:resolved"], "example:open", "present"),
                      edge("retract", "retraction", ["example:resolved"], "example:unknown", "retracted", "unknown")]}
        if change:
            change(value)
        return LifecycleDefinition(value, schemas=self.f.schemas)

    def install_profile(self, definition, *, validator=None):
        f = self.f
        value = f.make_profile(f.rule_instance).value
        lifecycle = deepcopy(value["components"]["evidence"])
        lifecycle.update(rules=[], outputs=[], dependencies=["evidence"], capabilities=[], conflict_resolvers=[],
                         lifecycle_extensions=[definition.extension])
        value["components"]["lifecycle"] = lifecycle
        f.profile = ProfileDefinition(value, rules=f.rules, schemas=f.schemas, allowed_data_scopes=[f.storage.scope_id],
            allowed_capabilities=[], conflict_resolvers=[f.rule_instance.value["conflict_policy"]])
        f.profiles = ProfileRegistry([f.profile])
        f.plan = RulePlan(f.profile, rules=f.rules, schemas=f.schemas, nodes={"evidence": f.rule_instance.reference})
        f.service = f.make_service()
        self.lifecycle = LifecycleService(f.storage, profiles=f.profiles, definitions=[definition], schemas=f.schemas,
            claims=f.claims, occurrences=self.occurrences, assessments=f.service, controls=f.controls,
            clock=lambda: deepcopy(f.now), decision_validator=validator)
        self.definition = definition

    def remember(self, *records):
        for record in records:
            self.public[canonical_bytes(entity_ref(record))] = entity_ref(record)

    def event(self, identity, *, at=EARLY, available_at=EARLY):
        f = self.f
        payload = ("Synthetic episode " + identity + ".\n").encode()
        command = observation_command("observe-" + identity, "source-" + identity, payload=payload,
            scope_id=f.storage.scope_id, event_id="event-" + identity, available_at=available_at)
        command["body"]["observation"]["body"]["occurred_at"] = deepcopy(at)
        result = f.ingestor.ingest(f.ingestor.prepare(command), payload=payload)
        self.assertEqual(result["status"], "success", result)
        source = f.storage.get(result["body"]["observation"])
        proposed = occurrence_input("happening-" + identity, [source], scope_id=f.storage.scope_id)
        proposed["body"]["occurred_at"] = deepcopy(at)
        group = grouping_command("group-" + identity, creates=[proposed], assignments=[declared(source)], scope_id=f.storage.scope_id)
        result = self.occurrences.commit(self.occurrences.prepare(group))
        self.assertEqual(result["status"], "success", result)
        occurrence = f.storage.get(entity_ref(proposed))
        self.remember(source, occurrence)
        return source, occurrence

    def claim(self, identity, condition, signal, source, *, effective=EARLY, supersedes=(), subject=None, confidence=None):
        f = self.f
        command = claim_command("claim-" + identity, identity, subject or f.subject, source,
            predicate="example:condition", supersedes=supersedes, version=identity)
        value = {"condition": deepcopy(condition), "signal": signal}
        if confidence is not None:
            value["confidence"] = confidence
        command["body"]["claim"]["body"]["value"] = {"schema": self.claim_schema.reference, "value": value}
        command["body"]["claim"]["body"]["applicability"] = {"start": deepcopy(effective), "end": FUTURE, "bounds": "closed_open"}
        result = f.claims.append(f.claims.prepare(command))
        self.assertEqual(result["status"], "success", result)
        record = f.storage.get(result["body"]["claim"])
        self.remember(record)
        return record

    def assess(self, claim, occurrence, *, status="supported", purpose=None):
        f = self.f
        request = f.request(evidence=[pin(claim), pin(occurrence)])
        request["body"]["purpose"] = purpose or component("condition-purpose-" + claim["body"]["value"]["value"]["condition"]["key"])
        prepared = f.prepare(request=request, extra=[pin(claim), pin(occurrence)])
        command = f.command(prepared, interpretations=[{"node": "evidence", "claim": pin(claim),
            "labels": {"example:positive": status}, "evidence_standard": f.profile.component_references["evidence"]}])
        result = f.service.commit(command)
        self.assertEqual(result["status"], "success", result)
        assessment = f.storage.get(result["body"]["assessment"])
        self.remember(assessment)
        for ref in assessment["body"]["judgments"]:
            self.remember(f.storage.get(ref))
        return assessment

    def command(self, edge, claim, occurrence, assessment, *, condition=None, token=None, decision=None):
        f = self.f
        self.sequence += 1
        condition = condition or claim["body"]["value"]["value"]["condition"]
        command = _in_scope(fixture("commands/request_transition.json"), f.storage.scope_id)
        command.update(command_id="transition-" + str(self.sequence), idempotency_key="transition-key-" + str(self.sequence),
            actor=f.actor, authority=entity_ref(f.authority), expected_revisions=[])
        address = lifecycle_ref(f.subject, profile=f.profile.reference, condition=condition)
        try:
            revision = f.storage.get(address)["value"]["value"]["lifecycle_revision"]
        except StorageError as error:
            self.assertEqual(error.code, "E_NOT_FOUND")
            revision = 1
        command["body"] = {"matter": pin(f.subject), "lifecycle_revision": revision,
            "profile_edge": self.definition.edge_reference(edge), "evidence": [pin(claim), pin(occurrence)],
            "assessment": pin(assessment), "effective_at": claim["body"]["applicability"]["start"]}
        token = token or f.controls.capture(actor=f.actor, authority=entity_ref(f.authority), capability="transition",
            targets=list(self.public.values()))
        return self.lifecycle.prepare(command, profile=f.profile.reference, condition=condition, claim=pin(claim),
            occurrence=pin(occurrence), token=token, decision=decision)

    def apply(self, edge, claim, occurrence, assessment, **options):
        command = self.command(edge, claim, occurrence, assessment, **options)
        return command, self.lifecycle.transition(command)

    def establish(self, condition=None, *, identity="initial", at=EARLY):
        source, occurrence = self.event(identity, at=at)
        claim = self.claim(identity, condition or self.condition_a, "present", source, effective=at)
        assessment = self.assess(claim, occurrence)
        command, result = self.apply("establish", claim, occurrence, assessment)
        self.assertEqual(result.get("outcome"), "applied", result)
        return claim, occurrence, assessment, command, result

    def resolved(self):
        initial = self.establish()
        source, occurrence = self.event("recovery", at=NOW)
        claim = self.claim("recovery", self.condition_a, "recovered", source, effective=NOW)
        assessment = self.assess(claim, occurrence)
        command, result = self.apply("resolve", claim, occurrence, assessment)
        self.assertEqual(result.get("outcome"), "applied", result)
        return initial, claim, occurrence, assessment, command, result

    def current(self, condition=None):
        return self.lifecycle.current(self.f.subject, profile=self.f.profile.reference, condition=condition or self.condition_a)

    def test_matching_recovery_is_automatic_and_current_is_registered(self):
        initial, claim, occurrence, assessment, command, result = self.resolved()
        state = self.current()
        self.assertEqual(state["value"]["value"]["state"], "example:resolved")
        self.assertEqual(state["value"]["value"]["basis"]["claim"], pin(claim))
        self.assertIsNone(self.f.storage.get(result["body"]["transition_receipt"])["body"]["details"]["value"]["decision"])
        registration = self.f.storage.get(registration_ref(state))
        self.assertEqual(registration["value"]["value"]["status"], "current")
        self.assertEqual(self.lifecycle.transition(command), result)
        self.assertEqual(len(self.lifecycle.history(self.f.subject, profile=self.f.profile.reference, condition=self.condition_a)), 2)
        # A new command for precisely the same admitted transition is a semantic
        # no-op, whereas exact retry above comes from the durable journal.
        _, duplicate = self.apply("resolve", claim, occurrence, assessment)
        self.assertEqual(duplicate.get("outcome"), "already_applied", duplicate)
        self.assertEqual(self.current(), state)
        tampered = self.command("resolve", claim, occurrence, assessment)
        tampered["body"]["effective_at"] = FUTURE
        refused = self.lifecycle.transition(tampered)
        self.assertTrue(refused.get("outcome", "").startswith("held_for_"), refused)
        self.assertEqual(self.current(), state)
        with self.f.storage.snapshot() as view:
            self.assertEqual(self.lifecycle.read_current(view, self.f.subject, profile=self.f.profile.reference,
                condition=self.condition_a), state)
        self.assertEqual(self.lifecycle.state_role(self.f.profile.reference, state["value"]["value"]["state"]), "resolved")

    def test_unrelated_success_cannot_resolve_other_condition_or_circumstances(self):
        self.establish()
        self.establish(self.condition_b, identity="condition-b")
        source, occurrence = self.event("b-success", at=NOW)
        claim = self.claim("b-success", self.condition_b, "recovered", source, effective=NOW)
        assessment = self.assess(claim, occurrence)
        _, wrong = self.apply("resolve", claim, occurrence, assessment, condition=self.condition_a)
        self.assertEqual(wrong.get("outcome"), "held_for_evidence", wrong)
        self.assertEqual(self.current()["value"]["value"]["state"], "example:open")
        _, right = self.apply("resolve", claim, occurrence, assessment)
        self.assertEqual(right.get("outcome"), "applied", right)
        self.assertEqual(self.current(self.condition_b)["value"]["value"]["state"], "example:resolved")
        # The compound condition selector includes circumstances, not only a
        # topical key. A same-key success for another required scope is held.
        other = {**self.condition_a, "circumstance": "optional-operation"}
        source, occurrence = self.event("other-circumstance", at=NOW)
        claim = self.claim("other-circumstance", other, "recovered", source, effective=NOW)
        assessment = self.assess(claim, occurrence, purpose=component("other-circumstance-purpose"))
        _, wrong = self.apply("resolve", claim, occurrence, assessment, condition=self.condition_a)
        self.assertEqual(wrong.get("outcome"), "held_for_evidence", wrong)

    def test_old_occurrence_redelivery_stays_resolved_but_new_happening_reopens(self):
        initial, recovery, recovered_event, _, _, _ = self.resolved()
        old_claim, old_event = initial[:2]
        # Assessing redelivered evidence today does not turn its old occurrence
        # into a fresh happening. A separate lane preserves the current basis.
        assessment = self.assess(old_claim, old_event, purpose=component("redelivery-check"))
        _, replay = self.apply("recur", old_claim, old_event, assessment)
        self.assertEqual(replay.get("outcome"), "held_for_evidence", replay)
        self.assertEqual(self.current()["value"]["value"]["state"], "example:resolved")
        self.f.now = deepcopy(LATE)
        source, occurrence = self.event("distinct-recurrence", at=LATE, available_at=LATE)
        claim = self.claim("distinct-recurrence", self.condition_a, "present", source, effective=LATE)
        assessment = self.assess(claim, occurrence)
        _, result = self.apply("recur", claim, occurrence, assessment)
        self.assertEqual(result.get("outcome"), "applied", result)
        self.assertEqual(self.current()["value"]["value"]["state"], "example:open")
        receipts = self.lifecycle.history(self.f.subject, profile=self.f.profile.reference, condition=self.condition_a)
        self.assertEqual([item["body"]["details"]["value"]["trigger"] for item in receipts], ["establish", "resolution", "recurrence"])

    def test_distinct_id_without_later_happening_does_not_reopen(self):
        self.resolved()
        source, occurrence = self.event("late-published-old-event", at=EARLY, available_at=NOW)
        claim = self.claim("late-published-old-event", self.condition_a, "present", source, effective=EARLY)
        assessment = self.assess(claim, occurrence, purpose=component("old-event-purpose"))
        _, result = self.apply("recur", claim, occurrence, assessment)
        self.assertEqual(result.get("outcome"), "held_for_evidence", result)
        self.assertEqual(self.current()["value"]["value"]["state"], "example:resolved")

    def test_retraction_uses_actual_correction_and_unknown_never_proves_opposite(self):
        _, resolved_claim, resolved_event, _, _, result = self.resolved()
        old_receipt = self.f.storage.get(result["body"]["transition_receipt"])
        source, occurrence = self.event("withdrawn-source", at=NOW)
        retraction = self.claim("withdrawn-source", self.condition_a, "retracted", source,
            effective=NOW, supersedes=[resolved_claim])
        # The actual correction write invalidates the old lifecycle immediately.
        with self.assertRaises(StorageError) as stale:
            self.current()
        self.assertEqual(stale.exception.code, "E_DEPENDENCY_STALE")
        assessment = self.assess(retraction, occurrence, status="unknown")
        _, result = self.apply("retract", retraction, occurrence, assessment)
        self.assertEqual(result.get("outcome"), "applied", result)
        state = self.current()["value"]["value"]
        self.assertEqual(state["state"], "example:unknown")
        self.assertEqual(assessment["body"]["propositions"][0]["status"], "unknown")
        self.assertEqual(self.f.storage.get(pin(old_receipt)), old_receipt)
        self.assertEqual(len(self.lifecycle.history(self.f.subject, profile=self.f.profile.reference, condition=self.condition_a)), 3)

    def test_unrelated_retraction_is_held_and_refutation_is_not_unknown(self):
        _, prior_claim, _, _, _, _ = self.resolved()
        source, occurrence = self.event("unrelated-retraction", at=NOW)
        claim = self.claim("unrelated-retraction", self.condition_a, "retracted", source, effective=NOW)
        assessment = self.assess(claim, occurrence, status="unknown", purpose=component("unrelated-retraction-purpose"))
        _, result = self.apply("retract", claim, occurrence, assessment)
        self.assertEqual(result.get("outcome"), "held_for_evidence", result)
        self.assertEqual(self.current()["value"]["value"]["state"], "example:resolved")
        retracted = self.claim("actual-retraction", self.condition_a, "retracted", source, effective=NOW, supersedes=[prior_claim])
        assessment = self.assess(retracted, occurrence, status="refuted")
        _, result = self.apply("retract", retracted, occurrence, assessment)
        self.assertEqual(result.get("outcome"), "held_for_evidence", result)

    def test_past_effective_resolution_preserves_prior_knowledge(self):
        self.establish(at=EARLY)
        self.f.now = deepcopy(LATE)
        source, occurrence = self.event("late-known-recovery", at=NOW, available_at=LATE)
        claim = self.claim("late-known-recovery", self.condition_a, "recovered", source, effective=NOW)
        assessment = self.assess(claim, occurrence)
        _, result = self.apply("resolve", claim, occurrence, assessment)
        self.assertEqual(result.get("outcome"), "applied", result)
        detail = self.f.storage.get(result["body"]["transition_receipt"])["body"]["details"]["value"]
        self.assertEqual(detail["effective_at"], NOW)
        self.assertEqual(detail["knowledge_at"], LATE)
        before = self.lifecycle.history(self.f.subject, profile=self.f.profile.reference, condition=self.condition_a, knowledge_at=NOW)
        self.assertEqual([item["body"]["details"]["value"]["to_state"] for item in before], ["example:open"])
        current_evidence = self.lifecycle.history(self.f.subject, profile=self.f.profile.reference,
            condition=self.condition_a, effective_at=NOW)
        self.assertEqual(current_evidence[-1]["body"]["details"]["value"]["to_state"], "example:resolved")

    def test_original_narrow_token_cannot_expand_to_late_discovered_read_targets(self):
        source, occurrence = self.event("narrow")
        claim = self.claim("narrow", self.condition_a, "present", source)
        assessment = self.assess(claim, occurrence)
        token = self.f.controls.capture(actor=self.f.actor, authority=entity_ref(self.f.authority), capability="transition",
            targets=[entity_ref(item) for item in (self.f.subject, claim, occurrence, assessment)])
        with self.assertRaises(StorageError) as error:
            self.command("establish", claim, occurrence, assessment, token=token)
        self.assertEqual(error.exception.code, "E_AUTHORITY_REQUIRED")
        self.assertIsNone(self.current())

    def test_stale_prepared_transition_cannot_commit_after_new_control(self):
        initial = self.establish()
        source, occurrence = self.event("recovery-stale", at=NOW)
        claim = self.claim("recovery-stale", self.condition_a, "recovered", source, effective=NOW)
        assessment = self.assess(claim, occurrence)
        command = self.command("resolve", claim, occurrence, assessment)
        control = _in_scope(control_command("stop-transition", self.f.authority, targets=[self.f.subject], now=NOW), self.f.storage.scope_id)
        control["actor"] = self.f.actor
        control["body"]["control"]["body"]["actor"] = self.f.actor
        applied = self.f.controls.apply(self.f.controls.prepare(control))
        self.assertEqual(applied["status"], "success", applied)
        result = self.lifecycle.transition(command)
        self.assertEqual(result["status"], "failure", result)
        self.assertIn(result["error"]["code"], {"E_DEPENDENCY_STALE", "E_CANCELLED"})
        raw = self.f.storage.get(lifecycle_ref(self.f.subject, profile=self.f.profile.reference, condition=self.condition_a))
        self.assertEqual(raw["value"]["value"]["state"], "example:open")

    def test_future_or_unknown_source_availability_cannot_backdate_knowledge(self):
        for identity, available_at in [("future-basis", LATE),
                ("unknown-basis", {"state": "unknown", "reason": "not_reported"})]:
            with self.subTest(identity=identity):
                source, occurrence = self.event(identity, at=EARLY, available_at=available_at)
                claim = self.claim(identity, self.condition_a, "present", source)
                assessment = self.assess(claim, occurrence)
                with self.assertRaises(StorageError) as error:
                    self.command("establish", claim, occurrence, assessment)
                self.assertEqual(error.exception.code, "E_EVIDENCE_UNAVAILABLE")
                self.assertIsNone(self.current())

    def test_high_confidence_does_not_install_an_undeclared_edge_or_capability(self):
        source, occurrence = self.event("confident")
        claim = self.claim("confident", self.condition_a, "present", source, confidence="1.000000000000000")
        assessment = self.assess(claim, occurrence)
        command = self.command("establish", claim, occurrence, assessment)
        command["body"]["profile_edge"]["digest"] = "0" * 64
        result = self.lifecycle.transition(command)
        self.assertEqual(result["status"], "failure", result)
        self.assertEqual(result["error"]["code"], "E_AUTHORITY_REQUIRED")
        self.assertIsNone(self.current())
        # A structurally valid same-epoch token for another capability does not
        # become a transition grant, even for a certain supported judgment.
        token = self.f.controls.capture(actor=self.f.actor, authority=entity_ref(self.f.authority), capability="assessment",
            targets=list(self.public.values()))
        with self.assertRaises(StorageError) as denied:
            self.command("establish", claim, occurrence, assessment, token=token)
        self.assertEqual(denied.exception.code, "E_AUTHORITY_REQUIRED")

    def test_acknowledgement_cannot_satisfy_explicit_human_decision_edge(self):
        def human(value):
            value["edges"][1]["requires_decision"] = True
        self.install_profile(self.make_definition(change=human), validator=lambda *args, **kwargs: True)
        self.establish()
        source, occurrence = self.event("human-recovery", at=NOW)
        claim = self.claim("human-recovery", self.condition_a, "recovered", source, effective=NOW)
        # Acknowledgement is accepted on the host control path, but is not a
        # decision about this lifecycle edge. Capture the assessment afterwards.
        control = _in_scope(control_command("ack", self.f.authority, targets=[self.f.subject], kind="acknowledgement",
            action="disposition", now=NOW), self.f.storage.scope_id)
        control["actor"] = self.f.actor
        control["body"]["control"]["body"]["actor"] = self.f.actor
        result = self.f.controls.apply(self.f.controls.prepare(control))
        self.assertEqual(result["status"], "success", result)
        record = self.f.storage.get(result["body"]["control"])
        assessment = self.assess(claim, occurrence)
        with self.assertRaises(StorageError) as denied:
            self.command("resolve", claim, occurrence, assessment, decision=pin(record))
        self.assertEqual(denied.exception.code, "E_AUTHORITY_REQUIRED")
        with self.assertRaises(StorageError) as missing:
            self.command("resolve", claim, occurrence, assessment)
        self.assertEqual(missing.exception.code, "E_AUTHORITY_REQUIRED")
        raw = self.f.storage.get(lifecycle_ref(self.f.subject, profile=self.f.profile.reference, condition=self.condition_a))
        self.assertEqual(raw["value"]["value"]["state"], "example:open")

    def test_transition_and_registered_queue_invalidation_share_one_commit(self):
        self.establish()
        state = self.current()
        f = self.f
        with f.storage.snapshot() as view:
            manifest = capture_dependencies(view, scope_id=f.storage.scope_id, as_of=f.now,
                positive=[pin(state)], controls=f.controls)
        command = create_command("queue-register", "queue-bootstrap", scope_id=f.storage.scope_id,
            expected_revisions=manifest.read_pins)
        address = projection_ref("synthetic-queued-advice", f.storage.scope_id)
        def register(tx):
            subject = tx.insert(tx.command["body"]["matter"])
            queued = tx.put_projection(address, domain_value({"synthetic": "pending advice"}))
            register_dependency(tx, pin(queued), manifest, as_of=f.now, controls=f.controls)
            return tx.success("created", {"matter": pin(subject)})
        result = f.storage.execute(command, register)
        self.assertEqual(result["status"], "success", result)
        with f.storage.snapshot() as view:
            fresh = capture_freshness(view, registration_ref(address), as_of=f.now, controls=f.controls)
        source, occurrence = self.event("queue-recovery", at=NOW)
        claim = self.claim("queue-recovery", self.condition_a, "recovered", source, effective=NOW)
        assessment = self.assess(claim, occurrence, purpose=component("independent-recovery-lane"))
        # The old lifecycle/queue remains fresh until this transition replaces
        # that state; publishing this independent assessment did not touch it.
        with f.storage.snapshot() as view:
            require_freshness(view, fresh, as_of=f.now, controls=f.controls)
        command, result = self.apply("resolve", claim, occurrence, assessment)
        self.assertEqual(result.get("outcome"), "applied", result)
        registration = f.storage.get(registration_ref(address))
        self.assertEqual(registration["value"]["value"]["status"], "invalidated")
        self.assertEqual(f.storage.receipt_for(pin(registration))["body"]["operation_id"], command["command_id"])
        with f.storage.snapshot() as view:
            with self.assertRaises(StorageError):
                require_freshness(view, fresh, as_of=f.now, controls=f.controls)

    def test_registration_failure_rolls_back_state_receipt_and_event_slot(self):
        source, occurrence = self.event("atomic")
        claim = self.claim("atomic", self.condition_a, "present", source)
        assessment = self.assess(claim, occurrence)
        command = self.command("establish", claim, occurrence, assessment)
        with patch("matter.lifecycle.register_dependency", side_effect=StorageError("E_STORAGE_UNAVAILABLE")):
            result = self.lifecycle.transition(command)
        self.assertEqual(result["status"], "failure", result)
        self.assertIsNone(self.current())
        self.assertEqual(self.lifecycle.history(self.f.subject, profile=self.f.profile.reference, condition=self.condition_a), [])

    def test_definition_is_immutable_and_cannot_make_retraction_prove_refutation(self):
        original = self.definition.reference
        edited = self.definition.value
        edited["edges"][0]["accepted_signals"] = ["recovered"]
        self.assertEqual(self.definition.reference, original)
        other = LifecycleDefinition(edited, schemas=self.f.schemas)
        self.assertNotEqual(other.reference, original)
        self.assertNotEqual(other.edge_reference("establish"), self.definition.edge_reference("establish"))
        edited = self.definition.value
        edited["edges"][-1]["assessment_statuses"] = ["refuted"]
        with self.assertRaises(StorageError):
            LifecycleDefinition(edited, schemas=self.f.schemas)


if __name__ == "__main__":
    unittest.main()
