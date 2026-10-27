"""MAT-016 actual core writes and transitive freshness over scoped SQLite."""

from copy import deepcopy
import unittest
from unittest.mock import patch

from matter.associations import AssociationService
from matter.canonical import canonical_digest
from matter.controls import ControlService
from matter.coverage import CoverageService
from matter.dependencies import (
    capture_dependencies, capture_freshness, read_registration, recomputation_token,
    register_dependency, registration_ref, require_current_dependency, require_freshness, scope_fence_ref,
)
from matter.invalidation import InvalidationHook
from matter.matters import MatterService
from matter.observations import ObservationIngestor
from matter.occurrences import OccurrenceService
from matter.storage import SQLiteStore, StorageError, entity_ref, pin

from coverage_helpers import CoverageTestCase, T1, T2, T3, T4, specification
from integration.helpers import create_command, domain_value, projection_ref
from matter_helpers import metadata_command
from occurrence_helpers import OccurrenceTestCase, declared, grouping_command, replacement
from rule_helpers import component


def unique_refs(values):
    return list({(ref["scope_id"], ref["namespace"], ref["id"]): ref for ref in values}.values())


class GraphFixture:
    def install_hook(self, *, controls=None):
        self.graph_sequence = 0
        self.hook = InvalidationHook(clock=lambda: deepcopy(self.graph_now), controls=controls)
        old = self.storage
        old.close()
        self.storage = SQLiteStore(self.database, scope_id=old.scope_id, transaction_hook=self.hook)
        self.addCleanup(self.storage.close)

    def host(self, identity, *, registered=True, **manifest_options):
        self.graph_sequence += 1
        scope = self.storage.scope_id
        target = projection_ref(identity, scope)
        with self.storage.snapshot() as view:
            manifest = capture_dependencies(view, scope_id=scope, as_of=self.graph_now,
                                             controls=self.hook.controls, **manifest_options)
        command = create_command(f"graph-register-{self.graph_sequence}", f"graph-record-{self.graph_sequence}", scope_id=scope,
                                 expected_revisions=manifest.read_pins)
        def handler(tx):
            subject = tx.insert(tx.command["body"]["matter"])
            result = tx.put_projection(target, domain_value({"synthetic": identity}))
            if registered:
                register_dependency(tx, pin(result), manifest, as_of=self.graph_now, controls=self.hook.controls)
            return tx.success("created", {"matter": pin(subject)})
        result = self.storage.execute(command, handler)
        self.assertEqual(result["status"], "success", result)
        return self.storage.get(target), self.storage.get(registration_ref(target)) if registered else None

    def value(self, record):
        return record["value"]["value"]

    def state(self, target):
        return self.value(self.storage.get(registration_ref(target)))

    def assert_stale(self, registration, *, controls=None):
        with self.storage.snapshot() as view:
            with self.assertRaises(StorageError) as caught:
                require_current_dependency(view, entity_ref(registration), as_of=self.graph_now, controls=controls or self.hook.controls)
            self.assertEqual(caught.exception.code, "E_DEPENDENCY_STALE")

    def fresh(self, registration):
        with self.storage.snapshot() as view:
            return require_current_dependency(view, entity_ref(registration), as_of=self.graph_now, controls=self.hook.controls)

    def revise_host(self, target, identity="context-edit"):
        current = self.storage.get(entity_ref(target))
        self.graph_sequence += 1
        command = create_command(f"{identity}-{self.graph_sequence}", f"context-record-{self.graph_sequence}",
                                 scope_id=self.storage.scope_id, expected_revisions=[pin(current)])
        def handler(tx):
            subject = tx.insert(tx.command["body"]["matter"])
            tx.put_projection(entity_ref(current), domain_value({"synthetic": "revised", "epoch": current["revision"] + 1}))
            return tx.success("created", {"matter": pin(subject)})
        result = self.storage.execute(command, handler)
        self.assertEqual(result["status"], "success", result)
        return command, result


class DependencyCoverageTests(GraphFixture, CoverageTestCase):
    def setUp(self):
        super().setUp()
        self.graph_now = deepcopy(T2)
        self.install_hook()
        self.ingestor = ObservationIngestor(self.storage, self.payloads)
        self.service = AssociationService(self.storage, policy=self.policy)
        self.matters = MatterService(self.storage, identity_policy=self.matters._policy)
        self.coverage = CoverageService(self.storage, policy=self.coverage_policy)

    def test_unknown_observation_id_invalidates_narrow_absence_and_descendants_atomically(self):
        covered, _, _ = self.publish_coverage()
        watch, _, _ = self.register_watch(covered)
        absence, absence_reg = self.host("absence-conclusion", negative_registrations=[pin(watch)])
        queued, queued_reg = self.host("queued-after-absence", positive=[pin(absence)])
        unrelated, _, _ = self.arrival("unrelated-arrival", event="not-the-watched-event")
        self.assertEqual(self.state(absence)["status"], "current")
        self.assertEqual(self.fresh(absence_reg)["revision"], absence_reg["revision"])
        matching, command, _ = self.arrival("previously-unknown-id", occurred_at=T1)
        self.assertEqual(self.state(absence)["status"], "invalidated")
        self.assertEqual(self.state(queued)["status"], "invalidated")
        receipt = self.storage.receipt_for(pin(self.storage.get(registration_ref(queued))))
        self.assertEqual(receipt["body"]["operation_id"], command["command_id"])
        self.assertEqual(self.storage.get(pin(queued)), queued)
        self.assertEqual(self.storage.get(pin(absence_reg)), absence_reg)
        self.assert_stale(queued_reg)

    def test_typed_query_matches_new_identity_and_ignores_unrelated_arrivals(self):
        target, registration = self.host("typed-query", queries=[specification()])
        self.arrival("query-unrelated", event="unrelated")
        self.assertEqual(self.state(target)["status"], "current")
        self.fresh(registration)
        self.arrival("query-matching")
        self.assertEqual(self.state(target)["status"], "invalidated")
        self.assertTrue(self.state(target)["recompute_pending"])

    def test_indeterminate_query_arrival_is_not_treated_as_unrelated(self):
        from coverage_helpers import UNKNOWN
        target, registration = self.host("indeterminate-query", queries=[specification()])
        self.arrival("unknown-event-time", occurred_at=UNKNOWN)
        self.assertEqual(self.state(target)["status"], "invalidated")
        self.assert_stale(registration)

    def test_matching_arrival_while_already_invalidated_advances_epoch_without_duplicate_work(self):
        target, registration = self.host("query-cohort", queries=[specification()])
        _, first, _ = self.arrival("matching-one")
        invalid = self.storage.get(registration_ref(target))
        first_epoch = self.value(invalid)["epoch"]
        with self.storage.snapshot() as view:
            recompute = recomputation_token(view, pin(invalid))
        self.arrival("matching-two")
        after = self.storage.get(registration_ref(target))
        self.assertGreater(self.value(after)["epoch"], first_epoch)
        self.assertTrue(self.value(after)["recompute_pending"])
        self.assertEqual(len(self.value(after)["reasons"]), 2)
        self.assertNotEqual(recompute["value"]["registration"], pin(after))

    def test_duplicate_intake_and_exact_retry_do_not_revision_or_repeat_invalidation(self):
        target, _ = self.host("deduplicated-query", queries=[specification()])
        _, command, original = self.arrival("one-arrival")
        invalid = self.storage.get(registration_ref(target))
        self.assertEqual(self.ingestor.ingest(command), original)
        self.assertEqual(self.storage.get(registration_ref(target)), invalid)
        self.assertEqual(len(self.value(invalid)["reasons"]), 1)

    def test_new_candidate_publication_invalidates_uniqueness_without_discovery(self):
        first = self.matter("candidate-one")
        second = self.matter("candidate-two")
        catalog, _, _, _ = self.publish([first])
        unique, _ = self.host("candidate-uniqueness", candidate_sets=[pin(catalog)])
        self.publish([first, second], command_id="republish-two", previous=catalog)
        self.assertEqual(self.state(unique)["status"], "invalidated")

    def test_candidate_member_change_invalidates_before_catalog_republication(self):
        candidate = self.matter("considered-candidate")
        catalog, _, _, _ = self.publish([candidate])
        target, _ = self.host("candidate-member", candidate_sets=[pin(catalog)])
        edit = metadata_command("rename-considered", candidate, {"title": "Corrected candidate", "extensions": {}})
        result = self.matters.update_metadata(self.matters.prepare(edit))
        self.assertEqual(result["status"], "success", result)
        self.assertEqual(self.storage.get(pin(catalog)), catalog)
        self.assertEqual(self.state(target)["status"], "invalidated")

    def test_unrelated_audience_context_leaves_evidence_current(self):
        audience_a, _ = self.host("audience-a", registered=False)
        audience_b, _ = self.host("audience-b", registered=False)
        evidence, evidence_reg = self.host("evidence-only", positive=[pin(self.subject)])
        first, _ = self.host("attention-a", positive=[pin(evidence)], contexts=[pin(audience_a)])
        second, _ = self.host("attention-b", positive=[pin(evidence)], contexts=[pin(audience_b)])
        self.revise_host(audience_a)
        self.assertEqual(self.state(first)["status"], "invalidated")
        self.assertEqual(self.state(second)["status"], "current")
        self.assertEqual(self.state(evidence)["status"], "current")
        self.fresh(evidence_reg)

    def test_freshness_token_refuses_stale_context_and_keeps_original_history(self):
        context, _ = self.host("freshness-context", registered=False)
        target, registration = self.host("dispatch-candidate", contexts=[pin(context)])
        with self.storage.snapshot() as view:
            token = capture_freshness(view, pin(registration), as_of=self.graph_now)
            require_freshness(view, token, as_of=self.graph_now)
        self.revise_host(context)
        with self.storage.snapshot() as view:
            with self.assertRaises(StorageError) as caught:
                require_freshness(view, token, as_of=self.graph_now)
            self.assertEqual(caught.exception.code, "E_DEPENDENCY_STALE")
        self.assertEqual(self.storage.get(pin(registration)), registration)
        self.assertEqual(self.storage.get(pin(target)), target)

    def test_recomputation_racing_second_correction_cannot_publish_fresh(self):
        context, _ = self.host("racing-context", registered=False)
        target, _ = self.host("racing-target", contexts=[pin(context)])
        self.revise_host(context)
        with self.storage.snapshot() as view:
            old = view.get(registration_ref(target))
            token = recomputation_token(view, pin(old))
            current_context = view.get(entity_ref(context))
            manifest = capture_dependencies(view, scope_id=self.storage.scope_id, as_of=self.graph_now, contexts=[pin(current_context)])
        self.revise_host(context)
        command = create_command("racing-publish", "racing-publish-record", scope_id=self.storage.scope_id,
                                 expected_revisions=unique_refs([*manifest.read_pins, token["value"]["registration"], pin(target)]))
        def handler(tx):
            subject = tx.insert(tx.command["body"]["matter"])
            updated = tx.put_projection(entity_ref(target), domain_value({"recomputed": True}))
            register_dependency(tx, pin(updated), manifest, as_of=self.graph_now, previous=token)
            return tx.success("created", {"matter": pin(subject)})
        result = self.storage.execute(command, handler, dependency_error_code="E_DEPENDENCY_STALE")
        self.assertEqual(result["error"]["code"], "E_DEPENDENCY_STALE")
        self.assertEqual(self.storage.get(entity_ref(target)), target)
        self.assertEqual(self.state(target)["status"], "invalidated")

    def test_unconfigured_privileged_handle_cannot_make_stale_query_pass_freshness(self):
        target, registration = self.host("raw-bypass-query", queries=[specification()])
        raw = SQLiteStore(self.database, scope_id=self.storage.scope_id)
        self.addCleanup(raw.close)
        ingestor = ObservationIngestor(raw, self.payloads)
        command, payload = self.arrival_command("bypassed-hook")
        result = ingestor.ingest(ingestor.prepare(command), payload=payload)
        self.assertEqual(result["status"], "success", result)
        self.assertEqual(self.state(target)["status"], "current")
        self.assert_stale(registration)

    def test_independent_time_deadlines_stale_at_earlier_expiry(self):
        condition = {"condition": component("deadline"), "next_check_at": T4, "expires_at": T3}
        target, registration = self.host("independent-deadlines", time_conditions=[condition])
        self.fresh(registration)
        self.graph_now = deepcopy(T3)
        self.assert_stale(registration)
        # An ordinary operation advances the configured hook's explicit clock
        # check; no background scheduler or invented observation is required.
        self.host("clock-check-trigger")
        self.assertEqual(self.state(target)["status"], "invalidated")
        self.assertEqual(self.state(target)["reasons"][0]["cause"], "temporal_transition")

    def test_bounded_reason_tail_preserves_history_without_blocking_arrivals(self):
        target, original = self.host("bounded-reasons", queries=[specification()])
        with patch("matter.invalidation.MAX_REASONS", 2):
            self.arrival("tail-one")
            first = self.storage.get(registration_ref(target))
            self.arrival("tail-two")
            self.arrival("tail-three")
        latest = self.storage.get(registration_ref(target))
        self.assertEqual(self.value(latest)["epoch"], 3)
        self.assertEqual(len(self.value(latest)["reasons"]), 2)
        self.assertTrue(self.value(latest)["recompute_pending"])
        self.assertEqual(self.storage.get(pin(first)), first)


class DependencyOccurrenceTests(GraphFixture, OccurrenceTestCase):
    def setUp(self):
        super().setUp()
        self.graph_now = {"state": "known", "value": "2050-01-01T00:00:00Z", "precision": "second"}
        self.install_hook()
        self.observations = ObservationIngestor(self.storage, self.payloads)
        self.service = OccurrenceService(self.storage, grouping_policy=self.policy)

    def test_regrouping_invalidates_exact_recurrence_claim_and_queued_descendants(self):
        first = self.observe("first")
        second = self.observe("second")
        occurrence = self.group("mistaken-group", [first, second], assignments=[declared(first), declared(second)])
        recurrence, recurrence_reg = self.host("recurrence", positive=[pin(occurrence)])
        claim, claim_reg = self.host("claim-view", positive=[pin(recurrence)])
        queued, queued_reg = self.host("queued-projection", positive=[pin(claim)])
        unrelated, _ = self.host("unrelated-view", positive=[pin(first)])
        command = self.service.prepare(grouping_command("correct-group", replacements=[replacement(occurrence, [first])]))
        result = self.service.commit(command)
        self.assertEqual(result["status"], "success", result)
        for target in (recurrence, claim, queued):
            value = self.state(target)
            self.assertEqual(value["status"], "invalidated")
            self.assertEqual(value["epoch"], 1)
            self.assertEqual(len(value["reasons"]), 1)
        self.assertEqual(self.state(unrelated)["status"], "current")
        receipt = self.storage.receipt_for(pin(self.storage.get(registration_ref(queued))))
        self.assertEqual(receipt["body"]["operation_id"], command["command_id"])
        for record in (occurrence, recurrence_reg, claim_reg, queued_reg):
            self.assertEqual(self.storage.get(pin(record)), record)

    def test_cycles_and_foreign_scope_are_refused(self):
        source = self.observe("cycle-source")
        target, registration = self.host("cycle-target", positive=[pin(source)])
        foreign = {**pin(source), "scope_id": "foreign"}
        with self.assertRaises(StorageError) as caught:
            self.host("foreign", positive=[foreign])
        self.assertEqual(caught.exception.code, "E_SCOPE_FORBIDDEN")
        with self.storage.snapshot() as view:
            manifest = capture_dependencies(view, scope_id=self.storage.scope_id, as_of=self.graph_now, positive=[pin(target)])
            token = recomputation_token(view, pin(registration))
        command = create_command("self-cycle", "cycle-record", scope_id=self.storage.scope_id,
                                 expected_revisions=unique_refs([*manifest.read_pins, pin(target), pin(registration)]))
        def handler(tx):
            register_dependency(tx, pin(target), manifest, as_of=self.graph_now, previous=token)
        result = self.storage.execute(command, handler)
        self.assertEqual(result["error"]["code"], "E_POLICY_INVALID")

    def test_actual_observation_correction_invalidates_old_snapshot_consumers(self):
        from observation_helpers import observation_command
        source = self.observe("original-observation")
        target, _ = self.host("observation-derived", positive=[pin(source)])
        queued, _ = self.host("observation-queued", positive=[pin(target)])
        payload = b"SYNTHETIC corrected source bytes.\n"
        command = observation_command("correct-original-observation", "corrected-observation", scope_id=self.storage.scope_id,
            payload=payload, source_namespace=source["body"]["source_identity"]["namespace"],
            event_id=source["body"]["source_identity"]["event_id"], revision_id="corrected-revision")
        command["body"]["observation"]["supersedes"] = [pin(source)]
        result = self.observations.ingest(self.observations.prepare(command), payload=payload)
        self.assertEqual(result["status"], "success", result)
        self.assertEqual(self.state(target)["status"], "invalidated")
        self.assertEqual(self.state(queued)["status"], "invalidated")
        self.assertEqual(self.state(target)["reasons"][0]["cause"], "evidence_correction")
        self.assertEqual(self.storage.get(pin(source)), source)


class DependencyAssessmentTests(GraphFixture, unittest.TestCase):
    def setUp(self):
        # Reuse actual publication setup without inheriting/rerunning its tests.
        from integration.test_assessment_commit import AssessmentCommitTests
        fixture = AssessmentCommitTests(methodName="runTest")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.database, self.storage = fixture.database, fixture.storage
        self.graph_now = deepcopy(fixture.now)
        self.install_hook()
        fixture.storage = self.storage
        fixture.controls = ControlService(self.storage, policy=fixture.controls.policy, clock=lambda: deepcopy(self.graph_now))
        self.hook.controls = fixture.controls
        fixture.matters = MatterService(self.storage, identity_policy=fixture.matters._policy)
        from matter.claims import ClaimService
        fixture.claims = ClaimService(self.storage)
        fixture.service = fixture.make_service()

    def deny_read(self, identity, *, target=None):
        from control_helpers import control_command
        from integration.helpers import _in_scope
        fixture = self.fixture
        command = _in_scope(control_command(identity, fixture.authority, targets=[target or fixture.source],
                                            action="deny", capabilities=["read"], now=self.graph_now), self.storage.scope_id)
        command["actor"] = deepcopy(fixture.actor)
        command["body"]["control"]["body"]["actor"] = deepcopy(fixture.actor)
        return fixture.controls.apply(fixture.controls.prepare(command))

    def test_actual_published_assessment_and_raw_judgment_invalidate_with_current_lane(self):
        from matter.assessments import assessment_current_ref
        fixture = self.fixture
        prepared, command, assessment = fixture.publish()
        lane_ref = assessment_current_ref(self.storage.scope_id, fixture.subject, profile=fixture.profile.reference,
                                         purpose=fixture.purpose, audience=fixture.audience)
        lane = self.storage.get(lane_ref)
        judgment = self.storage.get(assessment["body"]["judgments"][0])
        queued, queued_reg = self.host("actual-assessment-queue", positive=[pin(lane)])
        self.assertEqual(self.state(judgment)["status"], "current")
        self.assertEqual(self.state(assessment)["status"], "current")
        fixture.rename_subject()
        self.assertEqual(self.state(judgment)["status"], "invalidated")
        self.assertEqual(self.state(assessment)["status"], "invalidated")
        self.assertEqual(self.state(queued)["status"], "invalidated")
        self.assertEqual(self.storage.get(lane_ref)["value"]["value"]["status"], "invalidated")
        self.assertEqual(self.storage.get(pin(lane)), lane)
        self.assertEqual(self.storage.get(pin(assessment)), assessment)
        self.assertEqual(self.storage.get(pin(judgment)), judgment)
        with self.assertRaises(StorageError):
            fixture.service.current(fixture.subject, profile=fixture.profile.reference,
                                    purpose=fixture.purpose, audience=fixture.audience)

    def test_read_access_loss_invalidates_source_required_derivative_and_descendant(self):
        fixture = self.fixture
        token = fixture.controls.capture(actor=fixture.actor, authority=entity_ref(fixture.authority), capability="read",
                                         targets=[entity_ref(fixture.source)])
        target, registration = self.host("read-required", positive=[pin(fixture.source)], control_token=token)
        queued, _ = self.host("read-dependent-queue", positive=[pin(target)])
        result = self.deny_read("deny-source-read")
        self.assertEqual(result["status"], "success", result)
        self.assertEqual(self.state(target)["status"], "invalidated")
        self.assertEqual(self.state(queued)["status"], "invalidated")
        self.assertEqual(self.storage.get(pin(fixture.source)), fixture.source)
        self.assert_stale(registration, controls=fixture.controls)

    def test_immutable_claim_correction_notice_invalidates_old_claim_consumers(self):
        fixture = self.fixture
        original, _, _ = fixture.append("original-assertion")
        target, _ = self.host("claim-assessment-view", positive=[pin(original)])
        queued, _ = self.host("claim-queued-view", positive=[pin(target)])
        correction, command, _ = fixture.append("corrected-assertion", supersedes=[original], value="Corrected proposition", version="2.0")
        self.assertEqual(self.storage.get(pin(original)), original)
        self.assertNotEqual(original["id"], correction["id"])
        self.assertEqual(self.state(target)["status"], "invalidated")
        self.assertEqual(self.state(queued)["status"], "invalidated")
        self.assertEqual(self.state(target)["reasons"][0]["cause"], "evidence_correction")
        receipt = self.storage.receipt_for(pin(self.storage.get(registration_ref(target))))
        self.assertEqual(receipt["body"]["operation_id"], command["command_id"])

    def test_hooked_assessment_republication_replaces_invalidated_lane_once(self):
        from matter.assessments import assessment_current_ref
        fixture = self.fixture
        _, _, original = fixture.publish()
        address = assessment_current_ref(self.storage.scope_id, fixture.subject, profile=fixture.profile.reference,
                                         purpose=fixture.purpose, audience=fixture.audience)
        lane = self.storage.get(address)
        first_registration = self.storage.get(registration_ref(lane))
        fixture.rename_subject()
        invalidated = self.storage.get(address)
        self.assertEqual(invalidated["value"]["value"]["status"], "invalidated")
        _, _, replacement = fixture.publish()
        current = self.storage.get(address)
        registration = self.storage.get(registration_ref(current))
        self.assertEqual(current["value"]["value"]["status"], "current")
        self.assertEqual(current["value"]["value"]["assessment"], pin(replacement))
        self.assertEqual(self.state(current)["status"], "current")
        self.assertGreater(registration["revision"], first_registration["revision"])
        self.fresh(registration)
        self.assertEqual(self.storage.get(pin(original)), original)
        self.assertEqual(self.storage.get(pin(lane)), lane)
        self.assertEqual(self.storage.get(pin(invalidated)), invalidated)

    def test_actual_assessment_refuses_token_missing_selected_source_scope(self):
        fixture = self.fixture
        request = fixture.request()
        token = fixture.controls.capture(actor=fixture.actor, authority=entity_ref(fixture.authority),
                                         capability="assessment", targets=[entity_ref(fixture.subject)])
        request["body"]["control_epoch"] = token["control_epoch"]
        with self.assertRaises(StorageError) as caught:
            fixture.service.prepare(request, token=token, plan=fixture.plan)
        self.assertEqual(caught.exception.code, "E_AUTHORITY_REQUIRED")
        self.assertEqual(token["targets"], [entity_ref(fixture.subject)])

    def test_generic_registration_keeps_original_token_and_separate_source_read_guards(self):
        fixture = self.fixture
        token = fixture.controls.capture(actor=fixture.actor, authority=entity_ref(fixture.authority),
                                         capability="assessment", targets=[entity_ref(fixture.subject)])
        # This is a host freshness registration, not an assessment admission or
        # permission to act. The actual assessment gate above refuses this token.
        target, registration = self.host("separate-read-guards", positive=[pin(fixture.source)], control_token=token)
        original = self.value(registration)["manifest"]["control_token"]
        self.assertEqual(original, token)
        self.assertEqual(original["targets"], [entity_ref(fixture.subject)])
        self.assertIn(pin(fixture.source), [entry["reference"] for entry in self.value(registration)["manifest"]["read_access"]])
        self.assertEqual(self.deny_read("deny-under-narrow-token")["status"], "success")
        self.assertEqual(self.state(target)["status"], "invalidated")

    def test_over_capacity_graph_never_rolls_back_operator_read_denial(self):
        fixture = self.fixture
        token = fixture.controls.capture(actor=fixture.actor, authority=entity_ref(fixture.authority), capability="read",
                                         targets=[entity_ref(fixture.source)])
        target, registration = self.host("capacity-source", positive=[pin(fixture.source)], control_token=token)
        self.host("capacity-child-one", positive=[pin(target)])
        self.host("capacity-child-two", positive=[pin(target)])
        with self.storage.snapshot() as view:
            freshness = capture_freshness(view, pin(registration), as_of=self.graph_now, controls=fixture.controls)
        with patch("matter.invalidation.MAX_DEPENDENCIES", 1):
            result = self.deny_read("capacity-denial")
        self.assertEqual(result["status"], "success", result)
        fence = self.storage.get(scope_fence_ref(self.storage.scope_id))
        self.assertEqual(fence["value"]["value"]["reason"], "control_graph_fallback")
        with self.storage.snapshot() as view:
            with self.assertRaises(StorageError) as caught:
                require_freshness(view, freshness, as_of=self.graph_now, controls=fixture.controls)
            self.assertEqual(caught.exception.code, "E_DEPENDENCY_STALE")
            with self.assertRaises(StorageError) as caught:
                fixture.controls._view(view, actor=fixture.actor, authority=entity_ref(fixture.authority),
                                      capability="read", targets=[entity_ref(fixture.source)], now=self.graph_now)
            self.assertEqual(caught.exception.code, "E_AUTHORITY_REQUIRED")
        self.assertEqual(self.storage.get(pin(fixture.source)), fixture.source)

    def test_recomputation_recovers_after_scope_fallback_and_second_fallback_fences_it(self):
        from control_helpers import control_command
        from integration.helpers import _in_scope
        fixture = self.fixture
        first_token = fixture.controls.capture(actor=fixture.actor, authority=entity_ref(fixture.authority), capability="read",
                                               targets=[entity_ref(fixture.source)])
        target, _ = self.host("scope-recovery", positive=[pin(fixture.source)], control_token=first_token)
        with patch("matter.invalidation.MAX_DEPENDENCIES", 1):
            denied = self.deny_read("scope-recovery-deny")
        self.assertEqual(denied["status"], "success")
        control = self.storage.get(denied["body"]["control"])
        allow = _in_scope(control_command("scope-recovery-allow", fixture.authority, targets=[fixture.source],
            action="allow", capabilities=["read"], supersedes=[pin(control)], now=self.graph_now), self.storage.scope_id)
        allow["actor"] = deepcopy(fixture.actor)
        allow["body"]["control"]["body"]["actor"] = deepcopy(fixture.actor)
        self.assertEqual(fixture.controls.apply(fixture.controls.prepare(allow))["status"], "success")

        def prepare_recomputation(identity):
            token = fixture.controls.capture(actor=fixture.actor, authority=entity_ref(fixture.authority), capability="read",
                                              targets=[entity_ref(fixture.source)])
            with self.storage.snapshot() as view:
                registration = view.get(registration_ref(target))
                previous = recomputation_token(view, pin(registration))
                current_target = view.get(entity_ref(target))
                manifest = capture_dependencies(view, scope_id=self.storage.scope_id, as_of=self.graph_now,
                    positive=[pin(fixture.source)], control_token=token, controls=fixture.controls)
            command = create_command(identity, identity + "-record", scope_id=self.storage.scope_id,
                expected_revisions=unique_refs([*manifest.read_pins, previous["value"]["registration"], pin(current_target)]))
            def handler(tx):
                subject = tx.insert(tx.command["body"]["matter"])
                fresh = tx.put_projection(entity_ref(target), domain_value({"synthetic": identity}))
                register_dependency(tx, pin(fresh), manifest, as_of=self.graph_now, controls=fixture.controls, previous=previous)
                return tx.success("created", {"matter": pin(subject)})
            return command, handler

        command, handler = prepare_recomputation("scope-recovery-publish")
        result = self.storage.execute(command, handler, dependency_error_code="E_DEPENDENCY_STALE")
        self.assertEqual(result["status"], "success", result)
        registration = self.storage.get(registration_ref(target))
        self.fresh(registration)
        self.assertEqual(self.state(target)["status"], "current")
        with self.storage.snapshot() as view:
            old_freshness = capture_freshness(view, pin(registration), as_of=self.graph_now, controls=fixture.controls)
        racing, handler = prepare_recomputation("scope-second-fallback-race")
        with patch("matter.invalidation.MAX_DEPENDENCIES", 1):
            second = self.deny_read("scope-unrelated-matter-deny", target=fixture.subject)
        self.assertEqual(second["status"], "success")
        result = self.storage.execute(racing, handler, dependency_error_code="E_DEPENDENCY_STALE")
        self.assertEqual(result["error"]["code"], "E_DEPENDENCY_STALE")
        with self.storage.snapshot() as view:
            with self.assertRaises(StorageError) as caught:
                require_freshness(view, old_freshness, as_of=self.graph_now, controls=fixture.controls)
            self.assertEqual(caught.exception.code, "E_DEPENDENCY_STALE")

    def test_hooked_ordinary_supersession_keeps_new_lane_fresh_and_invalidates_old_queue(self):
        from matter.assessments import assessment_current_ref
        fixture = self.fixture
        _, _, original = fixture.publish()
        address = assessment_current_ref(self.storage.scope_id, fixture.subject, profile=fixture.profile.reference,
                                         purpose=fixture.purpose, audience=fixture.audience)
        lane = self.storage.get(address)
        queued, _ = self.host("old-current-lane-queue", positive=[pin(lane)])
        fixture.audience = {**fixture.audience, "version": "2.0", "digest": canonical_digest({"changed": "audience-version"}, "synthetic.context.v1")}
        _, _, replacement = fixture.publish()
        current = self.storage.get(address)
        self.assertEqual(self.state(current)["status"], "current")
        self.assertEqual(self.state(queued)["status"], "invalidated")
        self.fresh(self.storage.get(registration_ref(current)))
        self.assertEqual(self.storage.get(pin(original)), original)
        self.assertEqual(current["value"]["value"]["assessment"], pin(replacement))


if __name__ == "__main__":
    unittest.main()
