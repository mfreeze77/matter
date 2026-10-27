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
    time_watch, temporal_watch_keys, due_time_watch_keys,
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

    def test_historical_temporal_registrations_do_not_poison_intake_or_recomputation(self):
        archived = []
        unknown = {"state": "unknown", "reason": "not_applicable"}
        def at(hour):
            return {"state": "known", "value": f"2026-10-08T{hour:02d}:00:00Z", "precision": "second"}
        with patch("matter.dependencies.MAX_LIVE_TEMPORAL", 2), patch("matter.invalidation.MAX_DEPENDENCIES", 4):
            for index in range(6):
                deadline = at(15 + index)
                target, original = self.host(f"historical-time-{index}", time_conditions=[{
                    "condition": component(f"historical-{index}"), "next_check_at": deadline, "expires_at": unknown}])
                self.graph_now = deadline
                self.arrival(f"expire-history-{index}")
                registration = self.storage.get(registration_ref(target))
                self.assertEqual(self.value(registration)["status"], "invalidated")
                self.assertNotIn(time_watch(self.storage.scope_id), registration["watch_keys"])
                self.assertFalse(any(key.startswith("dependency-time-prefix-") for key in registration["watch_keys"]))
                with self.storage.snapshot() as view:
                    read_registration(view, pin(registration))
                archived.append((target, registration))
            self.assertEqual(self.storage.watchers(time_watch(self.storage.scope_id)), [])
            deadline = at(21)
            condition = {"condition": component("post-history"), "next_check_at": deadline, "expires_at": unknown}
            future, fresh_registration = self.host("post-history-live", time_conditions=[condition])
            self.arrival("post-history-intake")
            self.fresh(fresh_registration)
            target, old_registration = archived[0]
            with self.storage.snapshot() as view:
                previous = recomputation_token(view, pin(old_registration))
                manifest = capture_dependencies(view, scope_id=self.storage.scope_id, as_of=self.graph_now,
                                                time_conditions=[condition])
            command = create_command("repair-after-history", "repair-history-record", scope_id=self.storage.scope_id,
                expected_revisions=unique_refs([*manifest.read_pins, pin(target), previous["value"]["registration"]]))
            def handler(tx):
                record = tx.insert(tx.command["body"]["matter"])
                fresh = tx.put_projection(entity_ref(target), domain_value({"recomputed_after_history": True}))
                register_dependency(tx, pin(fresh), manifest, as_of=self.graph_now, previous=previous)
                return tx.success("created", {"matter": pin(record)})
            result = self.storage.execute(command, handler)
            self.assertEqual(result["status"], "success", result)
            current = self.storage.get(registration_ref(target))
            self.assertIn(time_watch(self.storage.scope_id), current["watch_keys"])
            self.fresh(current)
            self.assertEqual(len(self.storage.watchers(time_watch(self.storage.scope_id))), 2)

    def test_future_temporal_payloads_are_not_loaded_by_unrelated_intake(self):
        unknown = {"state": "unknown", "reason": "not_applicable"}
        futures = [self.host(f"future-index-{index}", time_conditions=[{
            "condition": component(f"future-{index}"), "next_check_at": T4, "expires_at": unknown}])[1] for index in range(5)]
        loaded, requested = [], []
        hook = self.hook
        class Probe:
            def __init__(self, transaction):
                self.transaction = transaction
            def __getattr__(self, name):
                return getattr(self.transaction, name)
            def watchers(self, key, *, limit=512):
                requested.append(key)
                result = self.transaction.watchers(key, limit=limit)
                if key.startswith("dependency-time-prefix-"):
                    loaded.extend(pin(record) for record in result)
                return result
        def traced(transaction, changes):
            return hook(Probe(transaction), changes)
        # Five live future rows exceed this hook cohort limit. The old global
        # temporal scan would refuse this three-write ordinary intake.
        with patch.object(self.storage, "_transaction_hook", traced), patch("matter.invalidation.MAX_DEPENDENCIES", 4):
            _, command, result = self.arrival("future-independent-arrival")
        self.assertEqual(result["status"], "success")
        self.assertNotIn(time_watch(self.storage.scope_id), requested)
        self.assertTrue(any(key.startswith("dependency-time-prefix-") for key in requested))
        self.assertEqual(loaded, [])
        receipt = self.storage.command_receipt(command["idempotency_key"])["receipt"]
        for registration in futures:
            self.assertNotIn(pin(registration), receipt["body"]["evidence"])
            self.fresh(registration)

    def test_live_temporal_capacity_refuses_only_the_new_registration(self):
        condition = {"condition": component("live-capacity"), "next_check_at": T4,
                     "expires_at": {"state": "unknown", "reason": "not_applicable"}}
        with patch("matter.dependencies.MAX_LIVE_TEMPORAL", 2):
            first, first_reg = self.host("capacity-time-one", time_conditions=[condition])
            second, second_reg = self.host("capacity-time-two", time_conditions=[condition])
            with self.storage.snapshot() as view:
                manifest = capture_dependencies(view, scope_id=self.storage.scope_id, as_of=self.graph_now,
                                                time_conditions=[condition])
            target = projection_ref("over-live-capacity", self.storage.scope_id)
            command = create_command("over-live-capacity", "over-capacity-record", scope_id=self.storage.scope_id,
                                     expected_revisions=manifest.read_pins)
            def handler(tx):
                record = tx.insert(tx.command["body"]["matter"])
                fresh = tx.put_projection(target, domain_value({"too_many_live_timers": True}))
                register_dependency(tx, pin(fresh), manifest, as_of=self.graph_now)
                return tx.success("created", {"matter": pin(record)})
            result = self.storage.execute(command, handler)
            self.assertEqual(result["error"]["code"], "E_BUDGET_EXHAUSTED")
            with self.assertRaises(StorageError) as caught:
                self.storage.get(target)
            self.assertEqual(caught.exception.code, "E_NOT_FOUND")
            self.arrival("ordinary-after-capacity-refusal")
            self.fresh(first_reg)
            self.fresh(second_reg)
            self.assertEqual(len(self.storage.watchers(time_watch(self.storage.scope_id))), 2)

    def test_due_unswept_cohort_does_not_refuse_its_replacement_host_registration(self):
        unknown = {"state": "unknown", "reason": "not_applicable"}
        with patch("matter.dependencies.MAX_LIVE_TEMPORAL", 2):
            old = [self.host(f"due-host-{index}", time_conditions=[{
                "condition": component("due-host"), "next_check_at": T3, "expires_at": unknown}])[0] for index in range(2)]
            self.graph_now = deepcopy(T3)
            target, registration = self.host("first-write-after-due", time_conditions=[{
                "condition": component("future-host"), "next_check_at": T4, "expires_at": unknown}])
            self.fresh(registration)
            self.assertEqual(self.state(target)["status"], "current")
            for prior in old:
                self.assertEqual(self.state(prior)["status"], "invalidated")
            self.assertEqual(len(self.storage.watchers(time_watch(self.storage.scope_id))), 1)


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

    def test_hooked_publication_with_source_restricted_static_policy_keeps_transitive_read_guards(self):
        from matter.assessments import assessment_current_ref
        from matter.authority import AuthorityPolicy, CAPABILITIES, CONTROL_KINDS
        fixture = self.fixture
        policy = AuthorityPolicy(self.storage.scope_id, actors=[fixture.actor], authorities=[pin(fixture.authority)],
            capabilities=CAPABILITIES, control_kinds=CONTROL_KINDS,
            targets=[entity_ref(fixture.subject), entity_ref(fixture.source)])
        fixture.controls = ControlService(self.storage, policy=policy, clock=lambda: deepcopy(self.graph_now))
        self.hook.controls = fixture.controls
        fixture.service = fixture.make_service()
        _, _, assessment = fixture.publish()
        judgment = self.storage.get(assessment["body"]["judgments"][0])
        lane = self.storage.get(assessment_current_ref(self.storage.scope_id, fixture.subject,
            profile=fixture.profile.reference, purpose=fixture.purpose, audience=fixture.audience))
        judgment_registration = self.storage.get(registration_ref(judgment))
        assessment_registration = self.storage.get(registration_ref(assessment))
        lane_registration = self.storage.get(registration_ref(lane))
        self.assertIn(pin(fixture.source), [entry["reference"] for entry in self.value(judgment_registration)["manifest"]["read_access"]])
        for registration in (assessment_registration, lane_registration):
            self.fresh(registration)
            guarded = [entry["reference"] for entry in self.value(registration)["manifest"]["read_access"]]
            self.assertNotIn(pin(judgment), guarded)
            self.assertNotIn(pin(assessment), guarded)
        self.assertEqual(fixture.service.current(fixture.subject, profile=fixture.profile.reference,
            purpose=fixture.purpose, audience=fixture.audience), assessment)
        self.assertEqual(self.deny_read("restricted-policy-source-denial")["status"], "success")
        for target in (judgment, assessment, lane):
            self.assertEqual(self.state(target)["status"], "invalidated")
        self.assert_stale(lane_registration)

    def test_invalidated_old_published_judgments_leave_live_temporal_index(self):
        from matter.planner import RulePlan
        from matter.profiles import ProfileRegistry
        from matter.rules import RuleRegistry
        from rule_helpers import LATE
        fixture = self.fixture
        condition = {"condition": component("published-deadline"), "next_check_at": deepcopy(LATE),
                     "expires_at": {"state": "unknown", "reason": "not_applicable"}}
        fixture.rule_instance = fixture.rule(fixture.binding_instance, change=lambda definition: definition.update(temporal_dependencies=[condition]))
        fixture.rules = RuleRegistry([fixture.rule_instance])
        fixture.profile = fixture.make_profile(fixture.rule_instance)
        fixture.profiles = ProfileRegistry([fixture.profile])
        fixture.plan = RulePlan(fixture.profile, rules=fixture.rules, schemas=fixture.schemas,
                               nodes={"evidence": fixture.rule_instance.reference})
        fixture.service = fixture.make_service()
        _, _, assessment = fixture.publish()
        judgment = self.storage.get(assessment["body"]["judgments"][0])
        original = self.storage.get(registration_ref(judgment))
        self.assertIn(time_watch(self.storage.scope_id), original["watch_keys"])
        self.graph_now = deepcopy(LATE)
        fixture.now = deepcopy(LATE)
        # A real trusted host control is one ordinary transaction boundary for
        # checking due work; no synthetic scheduler or provider is introduced.
        self.deny_read("expire-published-read")
        invalidated = self.storage.get(registration_ref(judgment))
        self.assertEqual(self.value(invalidated)["status"], "invalidated")
        self.assertNotIn(time_watch(self.storage.scope_id), invalidated["watch_keys"])
        self.assertFalse(any(key.startswith("dependency-time-prefix-") for key in invalidated["watch_keys"]))
        self.assertEqual(self.storage.get(pin(original)), original)

    def test_due_full_cohort_admits_actual_multi_registration_publication_without_prior_write(self):
        from matter.planner import RulePlan
        from matter.profiles import ProfileRegistry
        from matter.rules import RuleRegistry
        from rule_helpers import LATE
        fixture = self.fixture
        unknown = {"state": "unknown", "reason": "not_applicable"}
        future = {**LATE, "value": "2026-10-12T12:00:00Z"}
        condition = {"condition": component("replacement-publication"), "next_check_at": future, "expires_at": unknown}
        fixture.rule_instance = fixture.rule(fixture.binding_instance, change=lambda definition: definition.update(temporal_dependencies=[condition]))
        fixture.rules = RuleRegistry([fixture.rule_instance])
        fixture.profile = fixture.make_profile(fixture.rule_instance)
        fixture.profiles = ProfileRegistry([fixture.profile])
        fixture.plan = RulePlan(fixture.profile, rules=fixture.rules, schemas=fixture.schemas,
                               nodes={"evidence": fixture.rule_instance.reference})
        fixture.service = fixture.make_service()
        hook = self.hook
        capacity_limits = []
        class SmallDefaultSystemView:
            def __init__(self, transaction):
                self.transaction = transaction
            def __getattr__(self, name):
                return getattr(self.transaction, name)
            def watchers(self, key, *, limit=2):
                if key.startswith("dependency-time-"):
                    capacity_limits.append(limit)
                return self.transaction.watchers(key, limit=limit)
        def limited_hook(transaction, changes):
            return hook(SmallDefaultSystemView(transaction), changes)
        with patch("matter.dependencies.MAX_LIVE_TEMPORAL", 2), patch("matter.invalidation.MAX_LIVE_TEMPORAL", 2):
            old = [self.host(f"due-publication-{index}", time_conditions=[{
                "condition": component("due-publication"), "next_check_at": LATE, "expires_at": unknown}])[0] for index in range(2)]
            self.graph_now = deepcopy(LATE)
            fixture.now = deepcopy(LATE)
            with patch.object(self.storage, "_transaction_hook", limited_hook):
                _, _, assessment = fixture.publish()
            judgment = self.storage.get(assessment["body"]["judgments"][0])
            self.fresh(self.storage.get(registration_ref(judgment)))
            self.fresh(self.storage.get(registration_ref(assessment)))
            for prior in old:
                self.assertEqual(self.state(prior)["status"], "invalidated")
            self.assertIn(4, capacity_limits)
            self.assertEqual(len(self.storage.watchers(time_watch(self.storage.scope_id))), 2)

    def test_hook_admission_and_sweep_share_one_instant_across_clock_boundary(self):
        from matter.planner import RulePlan
        from matter.profiles import ProfileRegistry
        from matter.rules import RuleRegistry
        from rule_helpers import LATE
        fixture = self.fixture
        before = {"state": "known", "value": "2026-10-10T12:00:00.000000000Z", "precision": "nanosecond"}
        due = {**before, "value": "2026-10-10T12:00:00.000000001Z"}
        unknown = {"state": "unknown", "reason": "not_applicable"}
        condition = {"condition": component("clock-boundary-publication"), "next_check_at": LATE, "expires_at": unknown}
        fixture.rule_instance = fixture.rule(fixture.binding_instance, change=lambda definition: definition.update(temporal_dependencies=[condition]))
        fixture.rules = RuleRegistry([fixture.rule_instance])
        fixture.profile = fixture.make_profile(fixture.rule_instance)
        fixture.profiles = ProfileRegistry([fixture.profile])
        fixture.plan = RulePlan(fixture.profile, rules=fixture.rules, schemas=fixture.schemas,
                               nodes={"evidence": fixture.rule_instance.reference})
        fixture.service = fixture.make_service()
        self.graph_now = deepcopy(before)
        fixture.now = deepcopy(before)
        reads = []
        def advancing_clock():
            self.graph_now = deepcopy(before if not reads else due)
            reads.append(deepcopy(self.graph_now))
            return deepcopy(self.graph_now)
        with patch("matter.dependencies.MAX_LIVE_TEMPORAL", 2), patch("matter.invalidation.MAX_LIVE_TEMPORAL", 2):
            old, _ = self.host("clock-boundary-old", time_conditions=[{
                "condition": component("clock-boundary-old"), "next_check_at": due, "expires_at": unknown}])
            prepared = fixture.prepare()
            command = fixture.command(prepared)
            self.hook.clock = advancing_clock
            result = fixture.service.commit(command)
            self.assertEqual(result["error"]["code"], "E_BUDGET_EXHAUSTED", result)
            self.assertEqual(reads, [before])
            self.assertEqual(self.state(old)["status"], "current")
            self.assertEqual(len(self.storage.watchers(time_watch(self.storage.scope_id))), 1)
            # A new attempt at the reached boundary frees exactly the rows its
            # own sweep will invalidate; no unrelated write is needed to recover.
            self.graph_now = deepcopy(due)
            fixture.now = deepcopy(due)
            self.hook.clock = lambda: deepcopy(self.graph_now)
            _, _, assessment = fixture.publish()
            self.assertEqual(self.state(old)["status"], "invalidated")
            self.fresh(self.storage.get(registration_ref(assessment)))
            self.assertEqual(len(self.storage.watchers(time_watch(self.storage.scope_id))), 2)


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

    def repair_malformed_fence_during_control(self, malformed):
        fixture = self.fixture
        token = fixture.controls.capture(actor=fixture.actor, authority=entity_ref(fixture.authority), capability="read",
                                         targets=[entity_ref(fixture.source)])
        target, registration = self.host("damaged-fence-target", positive=[pin(fixture.source)], control_token=token)
        with self.storage.snapshot() as view:
            freshness = capture_freshness(view, pin(registration), as_of=self.graph_now, controls=fixture.controls)
        address = scope_fence_ref(self.storage.scope_id)
        # This is valid privileged storage data with an invalid *domain*
        # declaration, not raw SQLite corruption or bypassed digest checks.
        with SQLiteStore(self.database, scope_id=self.storage.scope_id) as raw:
            command = create_command("seed-malformed-fence", "seed-fence-record", scope_id=self.storage.scope_id)
            def seed(tx):
                subject = tx.insert(tx.command["body"]["matter"])
                tx.put_projection(address, malformed)
                return tx.success("created", {"matter": pin(subject)})
            self.assertEqual(raw.execute(command, seed)["status"], "success")
            old = raw.get(address)
        # Ordinary source intake needs only the verified scope-fence pin for
        # due-cohort routing. Its damaged derivative payload must not block it.
        fixture.ingestor = ObservationIngestor(self.storage, fixture.payloads)
        arrived = fixture.observe("intake-with-malformed-fence")
        self.assertEqual(self.storage.get(pin(arrived)), arrived)
        self.assertEqual(self.storage.get(address), old)
        with self.storage.snapshot() as view:
            with self.assertRaises(StorageError):
                capture_dependencies(view, scope_id=self.storage.scope_id, as_of=self.graph_now)
        # No capacity failure is forced: a real control explicitly detects and
        # repairs the malformed declaration through its bounded fallback.
        denied = self.deny_read("deny-with-malformed-fence")
        self.assertEqual(denied["status"], "success", denied)
        repaired = self.storage.get(address)
        self.assertEqual(repaired["value"]["value"]["epoch"], old["revision"] + 1)
        self.assertEqual(repaired["revision"], old["revision"] + 1)
        self.assertEqual(repaired["value"]["value"]["reason"], "control_graph_fallback")
        self.assertEqual(self.storage.get(pin(old)), old)
        with self.storage.snapshot() as view:
            with self.assertRaises(StorageError) as caught:
                require_freshness(view, freshness, as_of=self.graph_now, controls=fixture.controls)
            self.assertEqual(caught.exception.code, "E_DEPENDENCY_STALE")
            with self.assertRaises(StorageError) as caught:
                fixture.controls._view(view, actor=fixture.actor, authority=entity_ref(fixture.authority),
                                      capability="read", targets=[entity_ref(fixture.source)], now=self.graph_now)
            self.assertEqual(caught.exception.code, "E_AUTHORITY_REQUIRED")

    def test_unknown_scope_fence_schema_cannot_roll_back_admitted_control(self):
        self.repair_malformed_fence_during_control(domain_value({"obsolete": "unknown fence schema"}))

    def test_malformed_scope_fence_value_cannot_roll_back_admitted_control(self):
        from matter._rule_values import runtime_schema
        self.repair_malformed_fence_during_control({"schema": runtime_schema("dependency-scope-fence")[0],
                                                  "value": {"epoch": "not-a-counter"}})

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


class TemporalPrefixTests(unittest.TestCase):
    def test_exact_nanosecond_due_boundaries_and_supported_utc_dates(self):
        scope = "synthetic:temporal-prefix"
        for before, due in (
            ("0001-01-01T00:00:00.000000000Z", "0001-01-01T00:00:00.000000001Z"),
            ("1969-12-31T23:59:59.999999998Z", "1969-12-31T23:59:59.999999999Z"),
            ("1969-12-31T23:59:59.999999999Z", "1970-01-01T00:00:00.000000000Z"),
            ("9999-12-31T23:59:59.999999998Z", "9999-12-31T23:59:59.999999999Z"),
        ):
            with self.subTest(due=due):
                instant = lambda value: {"state": "known", "value": value, "precision": "nanosecond"}
                condition = {"condition": component("exact-boundary"), "next_check_at": instant(due),
                             "expires_at": {"state": "unknown", "reason": "not_reported"}}
                indexed = set(temporal_watch_keys(scope, [condition]))
                self.assertEqual(len(indexed), 77)
                self.assertEqual(indexed & set(due_time_watch_keys(scope, instant(before))), set())
                self.assertEqual(len(indexed & set(due_time_watch_keys(scope, instant(due)))), 1)

    def test_expiry_before_next_check_is_indexed_at_the_earlier_deadline(self):
        condition = {"condition": component("independent-boundaries"), "next_check_at": T4, "expires_at": T3}
        indexed = set(temporal_watch_keys("synthetic:earlier-expiry", [condition]))
        self.assertFalse(indexed & set(due_time_watch_keys("synthetic:earlier-expiry", T2)))
        self.assertEqual(len(indexed & set(due_time_watch_keys("synthetic:earlier-expiry", T3))), 1)



if __name__ == "__main__":
    unittest.main()
