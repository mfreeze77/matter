"""MAT-020 actual SQLite reservations and deterministic attention firing."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from threading import Barrier
import unittest
from unittest.mock import patch

from matter._rule_values import domain
from matter.access import AccessService, HostAccessPolicy
from matter.assessments import AssessmentService
from matter.attention import AttentionPolicy, AttentionService
from matter.authority import AuthorityPolicy
from matter.budgets import BudgetDefinition, BudgetService, REQUEST_EXTENSION as BUDGET_REQUEST, budget_ref
from matter.contexts import ContextDefinition
from matter.contracts import ContractError
from matter.controls import ControlService
from matter.invalidation import InvalidationHook
from matter.scheduler import Scheduler, TimerDefinition, firing_key, timer_ref
from matter.rules import RuleRegistry
from matter.profiles import ProfileRegistry
from matter.planner import RulePlan
from matter.storage import SQLiteStore, StorageError, entity_ref, pin

from control_helpers import control_command
from integration.helpers import _in_scope, fixture
from integration import test_audience_attention as attention_fixture
from observation_helpers import known_time
from rule_helpers import EARLY, NOW, LATE


END = known_time("2027-01-01T00:00:00Z")
T1 = known_time("2026-10-10T13:00:00Z")
T2 = known_time("2026-10-10T14:00:00Z")
T3 = known_time("2026-10-10T15:00:00Z")
T4 = known_time("2026-10-10T16:00:00Z")


class TimerBudgetTests(unittest.TestCase):
    def setUp(self):
        self.a = attention_fixture.AudienceAttentionTests(methodName="runTest")
        self.a.setUp()
        self.addCleanup(self.a.doCleanups)
        self.f, self.episode = self.a.f, self.a.episode
        self.sequence = 0
        self.resource = self.policy("resource", {"calls": 1, "input_bytes": 1048576, "output_bytes": 1048576, "elapsed_ms": 5000})
        self.attention = self.policy("attention", {"deliveries": 1, "interruption_units": 2})
        self.budgets = BudgetService(self.f.storage, definitions=[self.resource, self.attention], controls=self.f.controls,
            clock=lambda: deepcopy(self.f.now))
        self.scheduler = Scheduler(self.f.storage, attention=self.a.service, controls=self.f.controls, clock=lambda: deepcopy(self.f.now))

    def policy(self, kind, limits):
        return BudgetDefinition({"schema_version": "1.0", "namespace": "example", "id": kind + "-shared",
            "semantic_version": "1.0", "kind": kind, "window": {"start": EARLY, "end": END, "bounds": "closed_open"},
            "limits": limits, "units": {key: "example:" + key for key in limits}, "description": "Synthetic fixed-window shared allocation."})

    def command(self, operation, body):
        self.sequence += 1
        command = _in_scope(fixture("commands/" + operation + ".json"), self.f.storage.scope_id)
        command.update(command_id="timer-budget-" + str(self.sequence), idempotency_key="timer-budget-key-" + str(self.sequence),
            actor=self.f.actor, authority=entity_ref(self.f.authority), expected_revisions=[], body=deepcopy(body))
        return command

    def reserve_command(self, identity, *, policy=None, expires=LATE, token=None):
        policy = policy or self.resource
        token = token or self.f.controls.capture(actor=self.f.actor, authority=entity_ref(self.f.authority),
            capability="assessment" if policy.value["kind"] == "resource" else "delivery", targets=[entity_ref(self.f.subject)])
        command = self.command("reserve_budget", {"budget": policy.reference, "reservation_id": identity,
            "amounts": policy.value["limits"], "expires_at": expires, "targets": [entity_ref(self.f.subject)]})
        return self.budgets.prepare(command, token=token)

    def reserve(self, identity, **options):
        command = self.reserve_command(identity, **options)
        result = self.budgets.execute(command)
        self.assertEqual(result.get("outcome"), "reserved", result)
        return self.f.storage.get(result["body"]["reservation"]), command, result

    def settle(self, reservation, original, action):
        command = self.command("settle_budget", {"reservation": pin(reservation), "action": action})
        token = original["extensions"][BUDGET_REQUEST]["value"]["token"]["value"]
        command = self.budgets.prepare(command, token=token)
        return command, self.budgets.execute(command)

    def schedule(self, assessment, *, points=(T1,), token=None, identity="condition", generation=1, version="1.0", rules=None):
        token = token or self.f.controls.capture(actor=self.f.actor, authority=entity_ref(self.f.authority),
            capability="assessment", targets=self.a.targets(assessment))
        definition = TimerDefinition({"schema_version": "1.0", "namespace": "example", "id": identity,
            "semantic_version": version, "condition_id": identity, "generation": generation,
            "matter": pin(self.f.subject), "assessment": pin(assessment), "profile": self.f.profile.reference,
            "purpose": self.a.purpose_ref, "audience": self.a.audience_ref, "rules": rules or [self.f.rule_instance.reference],
            "dependencies": [pin(self.f.subject), pin(assessment), self.a.context_refs["purpose"], self.a.context_refs["audience"]],
            "checkpoints": [{"id": "point-" + str(index), "at": point} for index, point in enumerate(points)],
            "expires_at": END, "max_clock_skew_ms": 1000})
        command = self.command("schedule_timer", {"action": "create", "timer": domain("timer-definition", definition.value), "previous": None})
        command = self.scheduler.prepare_schedule(command, token=token)
        result = self.scheduler.execute(command)
        self.assertEqual(result.get("outcome"), "scheduled", result)
        return self.f.storage.get(result["body"]["timer"]), definition, token, command

    def fire_command(self, timer, definition, token, assessment, *, checkpoint=None):
        checkpoint = checkpoint or [point for point in definition.value["checkpoints"] if point["at"]["value"] <= self.f.now["value"]][-1]
        attention = self.a.prepare(assessment, token=token)
        command = self.command("fire_timer", {"timer": pin(timer), "firing_key": firing_key(definition, checkpoint),
            "attention_command": domain("operation-command", attention)})
        return self.scheduler.prepare_fire(command)

    @contextmanager
    def restarted(self):
        hook = InvalidationHook(clock=lambda: deepcopy(self.f.now))
        with SQLiteStore(self.f.database, scope_id=self.f.storage.scope_id, transaction_hook=hook) as storage:
            controls = ControlService(storage, policy=self.f.controls.policy, clock=lambda: deepcopy(self.f.now))
            hook.controls = controls
            assessments = AssessmentService(storage, profiles=self.f.profiles, rules=self.f.rules, bindings=self.f.bindings,
                schemas=self.f.schemas, controls=controls, clock=lambda: deepcopy(self.f.now), qualifications=self.f.service.qualifications)
            attention = AttentionService(storage, assessments=assessments, policies=self.a.service.policies,
                controls=controls, clock=lambda: deepcopy(self.f.now))
            yield Scheduler(storage, attention=attention, controls=controls, clock=lambda: deepcopy(self.f.now))

    def test_deadline_crossing_updates_actual_attention_without_semantic_invocation(self):
        # A declared future purpose becomes active at its deadline. The exact
        # source, claim, occurrence, assessment and context records stay fixed.
        value = self.a.contexts.definition("purpose", version="2.0").value
        value["effective_from"] = deepcopy(T1)
        purpose, _, _ = self.a.contexts.publish(ContextDefinition(value), previous=pin(self.a.purpose))
        self.a.purpose = purpose
        self.a.purpose_ref = self.a.contexts.select([purpose]).value["components"][0]["reference"]
        self.a.context_refs["purpose"] = pin(purpose)
        self.f.purpose = self.a.purpose_ref
        self.episode.remember(purpose)
        assessment, _, _, _ = self.a.assess("timeless-support")
        initial, _, _, _ = self.a.evaluate(assessment)
        self.assertEqual(initial["treatment"], "quiet")
        self.assertIn("no_active_purpose", initial["reasons"])
        before_calls = len(self.f.calls)
        timer, definition, token, _ = self.schedule(assessment)
        self.f.now = deepcopy(T1)
        command = self.fire_command(timer, definition, token, assessment)
        result = self.scheduler.execute(command)
        self.assertEqual(result.get("outcome"), "fired", result)
        decision = self.f.storage.get(result["body"]["attention_decision"])
        self.assertEqual(decision["body"]["details"]["value"]["treatment"], "update")
        self.assertEqual(decision["body"]["details"]["value"]["assessment"], pin(assessment))
        self.assertEqual(len(self.f.calls), before_calls)
        self.assertEqual(self.f.storage.receipt_for(pin(decision))["body"]["operation_id"], command["command_id"])
        self.assertEqual(self.scheduler.execute(command), result)

    def test_concurrent_connections_cannot_exceed_one_shared_remaining_budget(self):
        first, second = self.reserve_command("worker-one"), self.reserve_command("worker-two")
        barrier = Barrier(2)
        def worker(command):
            with SQLiteStore(self.f.database, scope_id=self.f.storage.scope_id) as storage:
                controls = ControlService(storage, policy=self.f.controls.policy, clock=lambda: deepcopy(self.f.now))
                service = BudgetService(storage, definitions=[self.resource], controls=controls, clock=lambda: deepcopy(self.f.now))
                barrier.wait(timeout=15)
                return service.execute(command)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(worker, command) for command in (first, second)]
            results = [future.result(timeout=30) for future in futures]
        self.assertEqual(sum(result.get("outcome") == "reserved" for result in results), 1, results)
        self.assertEqual(sum(result["status"] == "failure" for result in results), 1, results)
        account = self.f.storage.get(budget_ref(self.f.storage.scope_id, self.resource))["value"]["value"]
        self.assertEqual(account["held"]["calls"] + account["charged"]["calls"], 1)
        result = self.budgets.execute(self.reserve_command("fresh-loser"))
        self.assertEqual(result.get("outcome"), "budget_limited", result)
        self.assertEqual(result["body"]["remaining"]["calls"], 0)

    def test_restart_coalesces_downtime_once_and_records_real_delay(self):
        assessment, _, _, _ = self.a.assess("downtime-support")
        timer, definition, token, _ = self.schedule(assessment, points=(T1, T2, T3))
        self.f.now = deepcopy(T4)
        # A new backend handle and independently constructed host services
        # recover only durable rows, then coalesce all missed checkpoints.
        with self.restarted() as restarted:
            self.assertEqual(len(restarted.due()), 1)
            result = restarted.execute(self.fire_command(timer, definition, token, assessment))
            self.assertEqual(result.get("outcome"), "fired", result)
            self.assertEqual(result["body"]["coalesced_count"], 3)
            self.assertEqual(result["body"]["scheduled_at"], T3)
            self.assertEqual(result["body"]["actual_at"], T4)
            firing = self.f.storage.get(result["body"]["firing"])["body"]["details"]["value"]
            self.assertEqual(firing["delay_ms"], 3600000)
            self.assertEqual(restarted.due(), [])
            current = self.f.storage.get(entity_ref(timer))
            duplicate = self.command("fire_timer", {"timer": pin(current), "firing_key": result["body"]["firing"]["id"], "attention_command": None})
            duplicate = restarted.prepare_fire(duplicate)
            again = restarted.execute(duplicate)
            self.assertEqual(again.get("outcome"), "already_fired", again)
            self.assertEqual(again["body"]["firing"], result["body"]["firing"])

    def test_expired_unused_capacity_returns_once_and_committed_unknown_never_refunds(self):
        held, original, _ = self.reserve("expires-once", expires=T1)
        self.f.now = deepcopy(T1)
        _, expired = self.settle(held, original, "release")
        self.assertEqual(expired.get("outcome"), "expired", expired)
        self.assertEqual(expired["body"]["remaining"]["calls"], 1)
        current = self.f.storage.get(expired["body"]["reservation"])
        _, again = self.settle(current, original, "release")
        self.assertEqual(again.get("outcome"), "unchanged", again)
        self.assertEqual(again["body"]["remaining"]["calls"], 1)
        held, original, _ = self.reserve("committed-unknown", expires=T2)
        _, committed = self.settle(held, original, "commit")
        self.assertEqual(committed.get("outcome"), "committed", committed)
        committed_row = self.f.storage.get(committed["body"]["reservation"])
        self.f.now = deepcopy(T3)
        _, no_refund = self.settle(committed_row, original, "release")
        self.assertEqual(no_refund.get("outcome"), "unchanged", no_refund)
        self.assertEqual(no_refund["body"]["remaining"]["calls"], 0)
        with self.f.storage.snapshot() as view:
            with self.assertRaises(StorageError):
                self.budgets.require_committed(view, pin(committed_row))

    def test_resource_and_attention_accounts_are_independent_and_envelope_requires_precharge(self):
        held, original, _ = self.reserve("resource-cap", expires=known_time("2026-10-10T12:00:00.250Z"))
        with self.f.storage.snapshot() as view:
            with self.assertRaises(StorageError):
                self.budgets.resource_envelope(view, pin(held), ceiling=self.f.profile.value["resource_limits"])
        _, result = self.settle(held, original, "commit")
        committed = self.f.storage.get(result["body"]["reservation"])
        with self.f.storage.snapshot() as view:
            envelope = self.budgets.resource_envelope(view, pin(committed), ceiling=self.f.profile.value["resource_limits"])
        self.assertEqual(envelope.remaining_budget["max_calls"], 1)
        self.assertEqual(envelope.remaining_budget["max_elapsed_ms"], 250)
        self.assertEqual(envelope.remaining_budget["max_evidence"], self.f.profile.value["resource_limits"]["max_evidence"])
        attention, _, _ = self.reserve("attention-cap", policy=self.attention)
        self.assertEqual(attention["value"]["value"]["amounts"]["deliveries"], 1)
        result = self.budgets.execute(self.reserve_command("another-resource"))
        self.assertEqual(result.get("outcome"), "budget_limited", result)

    def test_direct_stop_bypasses_exhausted_budget_and_old_timer_is_inert_after_restart(self):
        held, original, _ = self.reserve("all-resource-capacity")
        self.settle(held, original, "commit")
        assessment, _, _, _ = self.a.assess("stoppable-timer")
        timer, definition, token, _ = self.schedule(assessment)
        control = _in_scope(control_command("direct-stop", self.f.authority, targets=[self.f.subject], now=NOW), self.f.storage.scope_id)
        control["actor"] = self.f.actor
        control["body"]["control"]["body"]["actor"] = self.f.actor
        stopped = self.f.controls.apply(self.f.controls.prepare(control))
        self.assertEqual(stopped["status"], "success", stopped)
        self.f.now = deepcopy(T1)
        command = self.command("fire_timer", {"timer": pin(timer), "firing_key": firing_key(definition, definition.value["checkpoints"][0]), "attention_command": None})
        result = self.scheduler.execute(self.scheduler.prepare_fire(command))
        self.assertEqual(result.get("outcome"), "inert", result)
        with self.restarted() as restarted:
            self.assertEqual(restarted.due(), [])

    def test_explicit_cancel_survives_restart_and_same_generation_cannot_renew(self):
        assessment, _, _, _ = self.a.assess("cancelled-timer")
        timer, definition, token, _ = self.schedule(assessment)
        command = self.command("schedule_timer", {"action": "cancel", "timer": domain("timer-definition", definition.value), "previous": pin(timer)})
        result = self.scheduler.execute(self.scheduler.prepare_schedule(command, token=token))
        self.assertEqual(result.get("outcome"), "cancelled", result)
        self.f.now = deepcopy(T4)
        with self.restarted() as restarted:
            self.assertEqual(restarted.due(), [])
        current = self.f.storage.get(entity_ref(timer))
        command = self.command("schedule_timer", {"action": "replace", "timer": domain("timer-definition", definition.value), "previous": pin(current)})
        with self.assertRaises(StorageError):
            self.scheduler.prepare_schedule(command, token=token)

    def test_fresh_equal_epoch_token_cannot_replace_original_timer_work_context(self):
        assessment, _, _, _ = self.a.assess("original-timer-token")
        timer, definition, original, _ = self.schedule(assessment)
        self.f.now = deepcopy(T1)
        replacement = self.f.controls.capture(actor=self.f.actor, authority=entity_ref(self.f.authority),
            capability="assessment", targets=self.a.targets(assessment))
        self.assertEqual(replacement["control_epoch"], original["control_epoch"])
        self.assertNotEqual(replacement["captured_at"], original["captured_at"])
        with self.assertRaises(StorageError) as error:
            self.fire_command(timer, definition, replacement, assessment)
        self.assertEqual(error.exception.code, "E_AUTHORITY_REQUIRED")

    def test_attention_stage_failure_rolls_back_firing_and_cursor(self):
        assessment, _, _, _ = self.a.assess("atomic-timer")
        timer, definition, token, _ = self.schedule(assessment)
        self.f.now = deepcopy(T1)
        command = self.fire_command(timer, definition, token, assessment)
        with patch.object(self.a.service, "stage", side_effect=StorageError("E_STORAGE_UNAVAILABLE")):
            result = self.scheduler.execute(command)
        self.assertEqual(result["status"], "failure", result)
        self.assertEqual(self.f.storage.get(entity_ref(timer)), timer)
        with self.assertRaises(StorageError):
            self.f.storage.get({"scope_id": self.f.storage.scope_id, "namespace": "matter.scheduler", "record_type": "receipt", "id": command["body"]["firing_key"]})

    def test_newly_installed_access_boundary_refuses_replay_without_original_access_context(self):
        assessment, _, _, _ = self.a.assess("access-history")
        timer, definition, token, _ = self.schedule(assessment)
        self.f.now = deepcopy(T1)
        command = self.fire_command(timer, definition, token, assessment)
        result = self.scheduler.execute(command)
        self.assertEqual(result.get("outcome"), "fired", result)
        policy = HostAccessPolicy(scope_id=self.f.storage.scope_id, audiences=[self.a.audience_ref], providers=[],
            grants=[{"reference": pin(self.f.source), "audiences": [self.a.audience_ref], "providers": []}])
        self.a.service.access = AccessService(policy=policy, controls=self.f.controls)
        refused = self.scheduler.execute(command)
        self.assertEqual(refused["status"], "failure", refused)
        self.assertEqual(refused["error"]["code"], "E_AUTHORITY_REQUIRED")
        current = self.f.storage.get(entity_ref(timer))
        old = self.command("fire_timer", {"timer": pin(current), "firing_key": result["body"]["firing"]["id"], "attention_command": None})
        with self.assertRaises(ContractError) as inspected:
            self.scheduler.prepare_fire(old)
        self.assertEqual(inspected.exception.code, "E_AUTHORITY_REQUIRED")

    def test_timer_cannot_mislabel_its_actual_assessment_rule_versions(self):
        assessment, _, _, _ = self.a.assess("bound-rule-versions")
        unused = self.f.rule(self.f.binding_instance, identity="installed-but-unselected")
        self.f.rules = RuleRegistry([self.f.rule_instance, unused])
        self.f.service.rules = self.f.rules
        with self.assertRaises(StorageError) as error:
            self.schedule(assessment, rules=[unused.reference])
        self.assertEqual(error.exception.code, "E_EVIDENCE_INVALID")
        self.assertEqual(self.scheduler.due(), [])

    def restrict_authority(self, targets):
        prior = self.f.controls.policy.definition
        self.f.controls.policy = AuthorityPolicy(self.f.storage.scope_id, actors=prior["actors"],
            authorities=prior["authorities"], capabilities=prior["capabilities"],
            control_kinds=prior["control_kinds"], targets=targets)

    def deny_read(self, identity):
        command = _in_scope(control_command(identity, self.f.authority, targets=[self.f.subject],
            action="deny", capabilities=["read"], now=self.f.now), self.f.storage.scope_id)
        command["actor"] = self.f.actor
        command["body"]["control"]["body"]["actor"] = self.f.actor
        result = self.f.controls.apply(self.f.controls.prepare(command))
        self.assertEqual(result["status"], "success", result)

    def test_settlement_replay_uses_historical_allocation_targets_not_release_hint(self):
        self.restrict_authority([entity_ref(self.f.subject)])
        held, original, _ = self.reserve("scoped-release")
        release = self.command("settle_budget", {"reservation": pin(held), "action": "release"})
        token = original["extensions"][BUDGET_REQUEST]["value"]["token"]["value"]
        release = self.budgets.prepare(release, token=token)
        # Unused-capacity cleanup is authenticated against the stored work
        # targets. Its caller context cannot omit those targets on later replay.
        release["extensions"][BUDGET_REQUEST]["value"]["token"]["value"]["targets"] = []
        released = self.budgets.execute(release)
        self.assertEqual(released.get("outcome"), "released", released)
        self.assertEqual(self.budgets.execute(release), released)
        self.assertGreater(self.f.storage.get(entity_ref(held))["revision"], held["revision"])
        held, original, _ = self.reserve("scoped-commit")
        commit, committed = self.settle(held, original, "commit")
        self.assertEqual(committed.get("outcome"), "committed", committed)
        self.assertEqual(self.budgets.execute(commit), committed)
        self.deny_read("deny-scoped-budget-replay")
        for command in (release, commit):
            refused = self.budgets.execute(command)
            self.assertEqual(refused["status"], "failure", refused)
            self.assertEqual(refused["error"]["code"], "E_AUTHORITY_REQUIRED")

    def test_scope_restricted_empty_attention_fire_replays_audit_original_timer_targets(self):
        assessment, _, _, _ = self.a.assess("scoped-timer-history")
        timer, definition, token, _ = self.schedule(assessment, identity="completed-history")
        inert_timer, inert_definition, inert_token, _ = self.schedule(assessment, identity="inert-history")
        self.f.now = deepcopy(T1)
        fired = self.scheduler.execute(self.fire_command(timer, definition, token, assessment))
        self.assertEqual(fired.get("outcome"), "fired", fired)
        # Tightening the host ceiling invalidates work tokens, while keeping
        # actual historical READ permission for precisely these stored targets.
        self.restrict_authority(token["targets"])
        current = self.f.storage.get(entity_ref(timer))
        duplicate = self.command("fire_timer", {"timer": pin(current), "firing_key": fired["body"]["firing"]["id"], "attention_command": None})
        duplicate = self.scheduler.prepare_fire(duplicate)
        already = self.scheduler.execute(duplicate)
        self.assertEqual(already.get("outcome"), "already_fired", already)
        self.assertEqual(self.scheduler.execute(duplicate), already)
        inert = self.command("fire_timer", {"timer": pin(inert_timer),
            "firing_key": firing_key(inert_definition, inert_definition.value["checkpoints"][0]), "attention_command": None})
        inert = self.scheduler.prepare_fire(inert)
        withheld = self.scheduler.execute(inert)
        self.assertEqual(withheld.get("outcome"), "inert", withheld)
        self.assertEqual(self.scheduler.execute(inert), withheld)
        self.deny_read("deny-scoped-fire-replay")
        for command in (duplicate, inert):
            refused = self.scheduler.execute(command)
            self.assertEqual(refused["status"], "failure", refused)
            self.assertEqual(refused["error"]["code"], "E_AUTHORITY_REQUIRED")

    def test_restart_discovers_healthy_timer_with_orphaned_rules_and_cancels_missing_profile(self):
        old_assessment, _, _, _ = self.a.assess("old-registry-version")
        orphan, old_definition, _, _ = self.schedule(old_assessment, identity="orphan-fire")
        cancel, cancel_definition, cancel_token, _ = self.schedule(old_assessment, identity="orphan-cancel")
        f = self.f
        old_profile, old_rule = f.profile, f.rule_instance
        current_rule = f.rule(f.binding_instance, identity="current-only-rule")
        current_profile = f.make_profile(current_rule, identity="current-only-profile")
        f.rules = RuleRegistry([old_rule, current_rule])
        f.profiles = ProfileRegistry([old_profile, current_profile])
        f.profile, f.rule_instance = current_profile, current_rule
        f.plan = RulePlan(current_profile, rules=f.rules, schemas=f.schemas, nodes={"evidence": current_rule.reference})
        f.service.rules, f.service.profiles = f.rules, f.profiles
        value = self.a.policy.value
        value.update(id="current-only-attention", profile=current_profile.reference)
        self.a.policy = AttentionPolicy(value)
        self.a.service = AttentionService(f.storage, assessments=f.service, policies=[self.a.policy],
            controls=f.controls, clock=lambda: deepcopy(f.now))
        self.scheduler = Scheduler(f.storage, attention=self.a.service, controls=f.controls, clock=lambda: deepcopy(f.now))
        healthy_assessment, _, _, _ = self.a.assess("healthy-registry-version")
        healthy, healthy_definition, healthy_token, _ = self.schedule(healthy_assessment, identity="healthy-fire")
        before_calls = len(f.calls)
        f.rules = RuleRegistry([current_rule])
        f.service.rules = f.rules
        f.now = deepcopy(T1)
        # First restart keeps the old profile but has dropped its exact rule.
        with self.restarted() as restarted:
            self.assertEqual({item["timer"]["id"] for item in restarted.due()}, {orphan["id"], cancel["id"], healthy["id"]})
            command = self.command("fire_timer", {"timer": pin(orphan),
                "firing_key": firing_key(old_definition, old_definition.value["checkpoints"][0]), "attention_command": None})
            result = restarted.execute(restarted.prepare_fire(command))
            self.assertEqual(result.get("outcome"), "inert", result)
            self.assertEqual(result["body"]["reason"], "original_policy_unavailable")
        # A second reopen also drops the old profile. The other orphan can still
        # be administratively cancelled, and the healthy timer still fires.
        f.profiles = ProfileRegistry([current_profile])
        f.service.profiles = f.profiles
        with self.restarted() as restarted:
            self.assertEqual({item["timer"]["id"] for item in restarted.due()}, {cancel["id"], healthy["id"]})
            command = self.command("schedule_timer", {"action": "cancel",
                "timer": domain("timer-definition", cancel_definition.value), "previous": pin(cancel)})
            result = restarted.execute(restarted.prepare_schedule(command, token=cancel_token))
            self.assertEqual(result.get("outcome"), "cancelled", result)
            self.assertEqual([item["timer"]["id"] for item in restarted.due()], [healthy["id"]])
            inner = self.a.prepare(healthy_assessment, token=healthy_token)
            command = self.command("fire_timer", {"timer": pin(healthy),
                "firing_key": firing_key(healthy_definition, healthy_definition.value["checkpoints"][0]),
                "attention_command": domain("operation-command", inner)})
            result = restarted.execute(restarted.prepare_fire(command))
            self.assertEqual(result.get("outcome"), "fired", result)
            self.assertEqual(restarted.due(), [])
        self.assertEqual(len(f.calls), before_calls)


if __name__ == "__main__":
    unittest.main()
