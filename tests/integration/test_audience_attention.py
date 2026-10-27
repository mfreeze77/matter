"""MAT-019 actual context/claim/assessment/receipt episodes over SQLite."""

from copy import deepcopy
import unittest

from matter.attention import AttentionPolicy, AttentionService, RESULT_EXTENSION, _address
from matter.canonical import canonical_bytes
from matter.contexts import ContextService
from matter.dependencies import registration_ref
from matter.dispositions import DispositionService, disposition_ref, disposition_scope_ref
from matter.identity_dependencies import _value
from matter.storage import StorageError, entity_ref, pin
from matter._rule_values import domain

from integration.helpers import create_command, record_input
from integration import test_lifecycle_episodes as lifecycle_fixtures
from unit import test_context_scopes as context_fixtures
from unit.test_attention_deltas import policy_value
from rule_helpers import component


class AudienceAttentionTests(unittest.TestCase):
    def setUp(self):
        episode = self.episode = lifecycle_fixtures.LifecycleEpisodes(methodName="runTest")
        episode.setUp()
        self.addCleanup(episode.doCleanups)
        f = self.f = episode.f
        helper = self.contexts = context_fixtures.ContextScopeTests(methodName="runTest")
        helper.fixture, helper.storage, helper.controls = f, f.storage, f.controls
        helper.contexts = ContextService(f.storage, controls=f.controls)
        helper.dispositions = DispositionService(f.storage, controls=f.controls)
        helper.sequence = 100
        self.purpose, _, _ = helper.publish(helper.definition("purpose"))
        self.audience, _, _ = helper.publish(helper.definition("audience", "human"))
        self.purpose_ref = helper.select([self.purpose]).value["components"][0]["reference"]
        self.audience_ref = helper.select([self.audience]).value["components"][0]["reference"]
        f.purpose, f.audience = self.purpose_ref, self.audience_ref
        self.policy = AttentionPolicy(policy_value(episode.claim_schema.reference, f.profile.reference))
        self.service = AttentionService(f.storage, assessments=f.service, policies=[self.policy], controls=f.controls,
            clock=lambda: deepcopy(f.now), lifecycle=episode.lifecycle)
        self.sequence = 0
        self.context_refs = {"purpose": pin(self.purpose), "audience": pin(self.audience), "responsibilities": [], "preferences": []}
        self.episode.remember(self.purpose, self.audience)

    def assess(self, identity, *, signal="present", status="supported", source=None, occurrence=None, supersedes=(), confidence=None):
        if source is None:
            source, occurrence = self.episode.event(identity)
        claim = self.episode.claim(identity, self.episode.condition_a, signal, source, supersedes=supersedes, confidence=confidence)
        assessment = self.episode.assess(claim, occurrence, status=status, purpose=self.purpose_ref)
        return assessment, claim, source, occurrence

    def targets(self, assessment, *, subject=None):
        values = list(self.episode.public.values()) + [entity_ref(assessment)]
        for kind in ("acknowledgement", "deferral", "rejection", "decision"):
            values.append(disposition_scope_ref(namespace="example:dispositions", kind=kind, matter=entity_ref(self.f.subject),
                purpose={"reference": self.purpose_ref, "context": self.context_refs["purpose"]},
                audience={"reference": self.audience_ref, "context": self.context_refs["audience"]}, subject=subject or pin(assessment)))
        return list({canonical_bytes(entity_ref(v)): entity_ref(v) for v in values}.values())

    def prepare(self, assessment, *, subject=None, delivery_receipt=None, lifecycle=None, token=None, access_context=None):
        self.sequence += 1
        command = self.f.request()
        command.update(command_id=f"attention-{self.sequence}", idempotency_key=f"attention-key-{self.sequence}")
        command["body"].update(purpose=self.purpose_ref, audience=self.audience_ref)
        token = token or self.f.controls.capture(actor=self.f.actor, authority=entity_ref(self.f.authority),
            capability="assessment" if delivery_receipt is None else "delivery", targets=self.targets(assessment, subject=subject))
        command["body"]["control_epoch"] = token["control_epoch"]
        return self.service.prepare(command, policy=self.policy, assessment=pin(assessment), contexts=self.context_refs,
            token=token, subject=subject, delivery_receipt=delivery_receipt, lifecycle=lifecycle, access_context=access_context)

    def evaluate(self, assessment, **kwargs):
        command = self.prepare(assessment, **kwargs)
        result = self.service.evaluate(command)
        self.assertEqual(result["status"], "success", result)
        receipt = self.f.storage.get(result["extensions"][RESULT_EXTENSION]["value"]["decision"])
        return _value("attention-decision", receipt["body"]["details"]), receipt, command, result

    def milestone(self, decision, *, stage="delivered", origin="host", producer=None, at=None):
        body = _value("attention-decision", decision["body"]["details"])
        self.sequence += 1
        receipt = record_input("receipt", f"host-milestone-{self.sequence}", scope_id=self.f.storage.scope_id)
        receipt["namespace"] = "example:transport"
        instant = at or deepcopy(self.f.now)
        receipt["provenance"].update(origin=origin, producer=producer or component("host-transport"), recorded_at=instant, parents=[])
        receipt["body"].update(stage=stage, operation_id=f"host-delivery-{self.sequence}", recorded_at=instant,
            outcome="example:delivered", evidence=[pin(decision)], details=domain("attention-delivery-milestone", {
                "schema_version": "1.0", "decision": pin(decision), "assessment": body["assessment"],
                "matter": entity_ref(body["matter"]), "purpose": body["purpose"], "audience": body["audience"],
                "material_digest": body["material_digest"], "milestone": "delivered", "delivered_at": instant}))
        command = create_command(f"host-delivery-bootstrap-{self.sequence}", f"host-adapter-record-{self.sequence}", scope_id=self.f.storage.scope_id)
        def handler(tx):
            stored = tx.insert(tx.command["body"]["matter"])
            tx.insert(receipt)
            return tx.success("created", {"matter": pin(stored)})
        self.assertEqual(self.f.storage.execute(command, handler)["status"], "success")
        return self.f.storage.get(entity_ref(receipt))

    def deliver(self, assessment, receipt):
        command = self.prepare(assessment, delivery_receipt=pin(receipt))
        result = self.service.evaluate(command)
        self.assertEqual(result["status"], "success", result)
        return command, result

    def baseline(self):
        return self.f.storage.get(_address(self.f.subject, self.policy.reference, self.purpose_ref, self.audience_ref, baseline=True))

    def test_delivered_baseline_survives_paraphrase_and_internal_reassessment_never_advances_it(self):
        first, claim, source, occurrence = self.assess("first")
        initial, decision, _, _ = self.evaluate(first)
        self.assertEqual(initial["treatment"], "update")
        read_token = self.f.controls.capture(actor=self.f.actor, authority=entity_ref(self.f.authority), capability="read", targets=self.targets(first))
        self.assertEqual(self.service.current(self.f.subject, policy=self.policy, purpose=self.purpose_ref,
            audience=self.audience_ref, read_token=read_token), decision)
        self.assertIsNone(_value("attention-baseline", self.baseline()["value"])["delivered"])
        self.deliver(first, self.milestone(decision))
        baseline = self.baseline()
        with self.assertRaises(StorageError) as error:
            self.service.current(self.f.subject, policy=self.policy, purpose=self.purpose_ref,
                audience=self.audience_ref, read_token=read_token)
        self.assertEqual(error.exception.code, "E_DEPENDENCY_STALE")
        self.assertEqual(self.service.read(read_token, pin(decision)), decision)
        later, _, _, _ = self.assess("paraphrase", source=source, occurrence=occurrence, confidence="Different wording, identical typed meaning.")
        updated, _, _, _ = self.evaluate(later)
        self.assertEqual(updated["treatment"], "quiet")
        self.assertIn("no_material_change", updated["reasons"])
        self.assertIn("already_delivered", updated["reasons"])
        self.assertEqual(self.baseline(), baseline)

    def test_decisive_correction_without_new_positive_event_is_eligible(self):
        first, original, source, occurrence = self.assess("before-correction")
        _, decision, _, _ = self.evaluate(first)
        self.deliver(first, self.milestone(decision))
        corrected, retraction, _, _ = self.assess("correction", signal="retracted", status="unknown", source=source,
            occurrence=occurrence, supersedes=[original])
        after, _, _, _ = self.evaluate(corrected)
        self.assertEqual(after["treatment"], "correction")
        self.assertIn("correction_delta", after["reasons"])
        self.assertEqual(retraction["supersedes"], [pin(original)])
        self.assertEqual(self.f.storage.get(pin(source)), source)

    def test_unlinked_unknown_is_not_correction_but_explicit_transitive_lineage_is(self):
        first, original, source, occurrence = self.assess("lineage-original")
        _, delivered, _, _ = self.evaluate(first)
        self.deliver(first, self.milestone(delivered))
        unlinked, _, _, _ = self.assess("unlinked-unknown", signal="retracted", status="unknown", source=source, occurrence=occurrence)
        quiet, _, _, _ = self.evaluate(unlinked)
        self.assertEqual(quiet["treatment"], "quiet")
        self.assertIn("insufficient_evidence", quiet["reasons"])
        middle = self.episode.claim("lineage-middle", self.episode.condition_a, "retracted", source, supersedes=[original])
        corrected, _, _, _ = self.assess("lineage-final", signal="retracted", status="unknown", source=source,
            occurrence=occurrence, supersedes=[middle])
        correction, _, _, _ = self.evaluate(corrected)
        self.assertEqual(correction["treatment"], "correction")
        self.assertIn("correction_delta", correction["reasons"])

    def test_ambiguous_evidence_is_quiet_not_a_human_request(self):
        assessment, _, _, _ = self.assess("ambiguous", status="unknown", confidence="0.01")
        value, _, _, _ = self.evaluate(assessment)
        self.assertEqual(value["treatment"], "quiet")
        self.assertIn("insufficient_evidence", value["reasons"])
        self.assertIsNone(value["decision_request"])

    def test_host_origin_and_successful_delivered_milestone_are_mandatory(self):
        assessment, _, _, _ = self.assess("delivery-guard")
        _, decision, _, _ = self.evaluate(assessment)
        for options in ({"stage": "queued"}, {"stage": "delivery_unknown"}, {"stage": "consumed"},
                        {"origin": "system"}, {"producer": component("unadmitted-producer")}):
            receipt = self.milestone(decision, **options)
            with self.assertRaises(StorageError):
                self.prepare(assessment, delivery_receipt=pin(receipt))
        self.assertIsNone(_value("attention-baseline", self.baseline()["value"])["delivered"])

    def test_existing_deferral_is_not_omittable_and_new_absent_fence_refuses_prepared_attention(self):
        assessment, _, _, _ = self.assess("deferral")
        prepared = self.prepare(assessment)
        definition = self.contexts.disposition("deferral", self.purpose, self.audience, subject=pin(assessment),
            until={"state": "known", "value": "2026-10-11T12:00:00Z", "precision": "second"})
        stored, _, _ = self.contexts.publish(definition, service=self.contexts.dispositions)
        result = self.service.evaluate(prepared)
        self.assertEqual(result["status"], "failure")
        self.assertIn(result["error"]["code"], {"E_DEPENDENCY_STALE", "E_REVISION_CONFLICT"})
        value, _, _, _ = self.evaluate(assessment)
        self.assertEqual(value["treatment"], "quiet")
        self.assertIn("deferred_until_checkpoint", value["reasons"])
        self.assertEqual(disposition_ref(definition), disposition_scope_ref(**{
            name: definition.value[name] for name in ("namespace", "kind", "matter", "purpose", "audience", "subject")}))

    def test_equivalent_policy_identity_reuses_the_audience_purpose_baseline(self):
        assessment, _, _, _ = self.assess("policy-baseline")
        _, decision, _, _ = self.evaluate(assessment)
        self.deliver(assessment, self.milestone(decision))
        baseline = self.baseline()
        value = self.policy.value
        value["id"] = "new-attention-policy-identity"
        value["routine_treatment"] = "digest"
        self.policy = AttentionPolicy(value)
        self.service = AttentionService(self.f.storage, assessments=self.f.service, policies=[self.policy], controls=self.f.controls,
            clock=lambda: deepcopy(self.f.now), lifecycle=self.episode.lifecycle)
        current, _, _, _ = self.evaluate(assessment)
        self.assertEqual(current["treatment"], "quiet")
        self.assertIn("already_delivered", current["reasons"])
        self.assertEqual(self.baseline(), baseline)

    def test_uninformed_audience_single_critical_fact_and_explicit_reserved_decision(self):
        value = self.policy.value
        value["fields"][0]["roles"].append("critical")
        self.policy = AttentionPolicy(value)
        self.service = AttentionService(self.f.storage, assessments=self.f.service, policies=[self.policy], controls=self.f.controls,
            clock=lambda: deepcopy(self.f.now))
        assessment, _, _, _ = self.assess("single-critical")
        current, decision, _, _ = self.evaluate(assessment)
        self.assertEqual(current["treatment"], "update")
        self.assertIn("critical_fact", current["reasons"])
        self.deliver(assessment, self.milestone(decision))
        other, _, _ = self.contexts.publish(self.contexts.definition("audience", "uninformed-observer"))
        self.episode.remember(other)
        self.audience, self.audience_ref = other, self.contexts.select([other]).value["components"][0]["reference"]
        self.f.audience = self.audience_ref
        self.context_refs["audience"] = pin(other)
        later, _, _, _ = self.assess("other-audience")
        uninformed, _, _, _ = self.evaluate(later)
        self.assertEqual(uninformed["treatment"], "update")
        value = self.policy.value
        value["id"] = "reserved-decision-policy"
        value["decision"] = {"field": "condition", "audience": self.audience_ref,
            "prompt": "Choose the explicitly reserved synthetic option.", "options": [domain("attention-current", {"decision": pin(decision)}),
                {"schema": component("option"), "value": "second"}],
            "why_host_cannot_settle": "Only this audience owns the named decision authority."}
        self.policy = AttentionPolicy(value)
        self.service = AttentionService(self.f.storage, assessments=self.f.service, policies=[self.policy], controls=self.f.controls,
            clock=lambda: deepcopy(self.f.now))
        requested, _, _, _ = self.evaluate(later)
        self.assertEqual(requested["treatment"], "decision_request")
        self.assertEqual(len(requested["decision_request"]["options"]), 2)

    def test_owned_next_step_is_quiet_for_human_and_hint_for_working_agent(self):
        responsibility, _, _ = self.contexts.publish(self.contexts.definition("responsibility", "agent-owns-step", content={
            "owner": {**self.f.actor, "id": "worker"}, "capabilities": ["write"], "purposes": []}))
        self.episode.remember(responsibility)
        self.context_refs["responsibilities"] = [pin(responsibility)]
        value = self.policy.value
        value["fields"][0]["roles"].append("owned_next_step")
        self.policy = AttentionPolicy(value)
        self.service = AttentionService(self.f.storage, assessments=self.f.service, policies=[self.policy], controls=self.f.controls,
            clock=lambda: deepcopy(self.f.now))
        assessment, _, _, _ = self.assess("owned-human")
        human, _, _, _ = self.evaluate(assessment)
        self.assertEqual(human["treatment"], "quiet")
        self.assertIn("handled_by_owner", human["reasons"])
        responsibility_ref = self.contexts.select([responsibility]).value["components"][0]["reference"]
        worker, _, _ = self.contexts.publish(self.contexts.definition("audience", "worker", content={"audience_id": "worker",
            "audience_kind": "host_agent", "purposes": [], "responsibilities": [responsibility_ref], "preferences": []}))
        self.episode.remember(worker)
        self.audience, self.audience_ref = worker, self.contexts.select([worker]).value["components"][0]["reference"]
        self.context_refs["audience"], self.f.audience = pin(worker), self.audience_ref
        later, _, _, _ = self.assess("owned-worker")
        agent, _, _, _ = self.evaluate(later)
        self.assertEqual(agent["treatment"], "host_hint")
        self.assertEqual(self.f.storage.get(pin(self.f.subject)), self.f.subject)

    def test_actual_resolved_lifecycle_remains_consumable_after_equivalent_same_lane_assessment(self):
        # The lifecycle fixture now uses this exact purpose/audience lane.
        original_assess = self.episode.assess
        def same_lane(claim, occurrence, **kwargs):
            return original_assess(claim, occurrence, purpose=self.purpose_ref, **kwargs)
        self.episode.assess = same_lane
        _, _, first, _, _ = self.episode.establish()
        selected = {"profile": self.f.profile.reference, "condition": self.episode.condition_a}
        initial, informed, _, _ = self.evaluate(first, lifecycle=selected)
        self.assertEqual(initial["treatment"], "update")
        self.deliver(first, self.milestone(informed))
        delivered = self.baseline()
        source, occurrence = self.episode.event("attention-recovery", at=self.f.now)
        claim = self.episode.claim("attention-recovery", self.episode.condition_a, "recovered", source, effective=self.f.now)
        assessment = self.episode.assess(claim, occurrence)
        _, applied = self.episode.apply("resolve", claim, occurrence, assessment)
        self.assertEqual(applied["outcome"], "applied")
        state = self.episode.current()
        value, decision, _, _ = self.evaluate(assessment, lifecycle={"profile": self.f.profile.reference, "condition": self.episode.condition_a})
        self.assertEqual(value["treatment"], "quiet")
        self.assertIn("recovery_established", value["reasons"])
        paraphrase = self.f.observe("equivalent-recovery-paraphrase")
        self.episode.remember(paraphrase)
        refreshed = self.episode.assess(claim, occurrence, extra=[pin(paraphrase)])
        after, _, _, _ = self.evaluate(refreshed, lifecycle={"profile": self.f.profile.reference, "condition": self.episode.condition_a})
        self.assertEqual(after["treatment"], "quiet")
        self.assertIn("recovery_established", after["reasons"])
        self.assertEqual(self.episode.current(), state)
        self.assertEqual(self.baseline(), delivered)

    def test_access_metadata_and_derived_closure_resolved_lifecycle_then_read_revocation(self):
        from matter.access import AccessService, HostAccessPolicy
        from matter.assessments import PUBLICATION_EXTENSION
        from matter.lifecycle import lifecycle_ref
        from matter.rules import RuleRegistry
        from control_helpers import control_command
        from integration.helpers import _in_scope, fixture
        f, episode = self.f, self.episode
        # The default one-second graph fixture budget is for a tiny source pair.
        # This conformance case deliberately runs the full metadata/source guard
        # closure; retain a finite explicit budget rather than disabling a gate.
        f.rule_instance = f.rule(f.binding_instance, change=lambda value: value["resource_limits"].update(max_elapsed_ms=30000))
        f.rules = RuleRegistry([f.rule_instance])
        episode.install_profile(episode.definition)
        configured = self.policy.value
        configured["profile"] = f.profile.reference
        self.policy = AttentionPolicy(configured)
        self.service = AttentionService(f.storage, assessments=f.service, policies=[self.policy], controls=f.controls,
            clock=lambda: deepcopy(f.now), lifecycle=episode.lifecycle)
        source_a, occurrence_a = episode.event("access-open")
        claim_a = episode.claim("access-open", episode.condition_a, "present", source_a)
        source_b, occurrence_b = episode.event("access-recovered", at=f.now)
        claim_b = episode.claim("access-recovered", episode.condition_a, "recovered", source_b, effective=f.now)
        context_dependencies = self.contexts.select([self.purpose, self.audience]).dependencies
        admitted = [pin(f.storage.get(ref)) for ref in episode.public.values()]
        policy = HostAccessPolicy(scope_id=f.storage.scope_id, audiences=[self.audience_ref], providers=[],
            grants=[{"reference": ref, "audiences": [self.audience_ref], "providers": []} for ref in admitted])
        access = AccessService(policy=policy, controls=f.controls, current_read=f.storage.snapshot)
        f.service.access = access
        self.service.access = access

        def original_context(capability, references, assessment=None):
            targets = list(episode.public.values()) if assessment is None else self.targets(assessment)
            token = f.controls.capture(actor=f.actor, authority=entity_ref(f.authority), capability=capability, targets=targets)
            with f.storage.snapshot() as view:
                complete = {canonical_bytes(ref): ref for ref in [*references,
                    *[pin(view.get(ref)) for ref in episode.public.values()]]}
                context = access.capture(view, token=token, audience=self.audience_ref, references=list(complete.values()))
            return token, context

        def publish_and_transition(identity, claim, occurrence, edge):
            references = [pin(f.subject), pin(f.source), pin(claim), pin(occurrence), *context_dependencies]
            token, context = original_context("assessment", references)
            request = f.request(evidence=[pin(claim), pin(occurrence)])
            request["body"].update(purpose=self.purpose_ref, audience=self.audience_ref, control_epoch=token["control_epoch"])
            request["body"]["budget"]["max_elapsed_ms"] = 30000
            prepared = f.service.prepare(request, token=token, plan=f.plan,
                extra_dependencies=[pin(claim), pin(occurrence), *context_dependencies], access_context=context)
            command = f.command(prepared, interpretations=[{"node": "evidence", "claim": pin(claim),
                "labels": {"example:positive": "supported"}, "evidence_standard": f.profile.component_references["evidence"]}])
            graph = command["extensions"][PUBLICATION_EXTENSION]["value"]["graph"]
            self.assertEqual(command["body"]["assessment"]["body"]["evaluation_state"], "complete", {
                "reason": graph["nodes"]["evidence"]["reason"], "error": graph["nodes"]["evidence"]["error_code"],
                "events": graph["nodes"]["evidence"]["attempt_receipt"]["body"]["details"]["value"]["events"]})
            result = f.service.commit(command)
            self.assertEqual(result["status"], "success", result)
            assessment = f.storage.get(result["body"]["assessment"])
            episode.remember(assessment, *[f.storage.get(ref) for ref in assessment["body"]["judgments"]])
            token, context = original_context("transition", [pin(assessment), *references])
            transition = _in_scope(fixture("commands/request_transition.json"), f.storage.scope_id)
            address = lifecycle_ref(f.subject, profile=f.profile.reference, condition=episode.condition_a)
            try:
                revision = f.storage.get(address)["value"]["value"]["lifecycle_revision"]
            except StorageError as error:
                self.assertEqual(error.code, "E_NOT_FOUND")
                revision = 1
            transition.update(command_id="access-transition-" + identity, idempotency_key="access-transition-" + identity,
                actor=f.actor, authority=entity_ref(f.authority), expected_revisions=[])
            transition["body"] = {"matter": pin(f.subject), "lifecycle_revision": revision,
                "profile_edge": episode.definition.edge_reference(edge), "evidence": [pin(claim), pin(occurrence)],
                "assessment": pin(assessment), "effective_at": claim["body"]["applicability"]["start"]}
            operation = episode.lifecycle.prepare(transition, profile=f.profile.reference, condition=episode.condition_a,
                claim=pin(claim), occurrence=pin(occurrence), token=token, access_context=context)
            applied = episode.lifecycle.transition(operation)
            self.assertEqual(applied.get("outcome"), "applied", applied)
            return assessment

        publish_and_transition("open", claim_a, occurrence_a, "establish")
        assessment = publish_and_transition("resolved", claim_b, occurrence_b, "resolve")
        references = [pin(assessment), *admitted]
        token, context = original_context("assessment", references, assessment=assessment)
        selected_lifecycle = {"profile": f.profile.reference, "condition": episode.condition_a}
        prepared = self.prepare(assessment, token=token, access_context=context, lifecycle=selected_lifecycle)
        result = self.service.evaluate(prepared)
        self.assertEqual(result["status"], "success", result)
        self.assertIn("recovery_established", result["extensions"][RESULT_EXTENSION]["value"]["reasons"])
        current_address = _address(f.subject, self.policy.reference, self.purpose_ref, self.audience_ref)
        previous = f.storage.get(current_address)
        pending = self.prepare(assessment, token=token, access_context=context, lifecycle=selected_lifecycle)
        denied = _in_scope(control_command("deny-access-attention-source", f.authority, targets=[source_b],
            action="deny", capabilities=["read"], now=f.now), f.storage.scope_id)
        denied["actor"] = deepcopy(f.actor)
        denied["body"]["control"]["body"]["actor"] = deepcopy(f.actor)
        self.assertEqual(f.controls.apply(f.controls.prepare(denied))["status"], "success")
        refused = self.service.evaluate(pending)
        self.assertEqual(refused["status"], "failure")
        self.assertIn(refused["error"]["code"], {"E_AUTHORITY_REQUIRED", "E_DEPENDENCY_STALE"})
        self.assertEqual(f.storage.get(current_address), previous)
        replay = self.service.evaluate(prepared)
        self.assertEqual(replay["error"]["code"], "E_AUTHORITY_REQUIRED")
        self.assertEqual(f.storage.command_receipt(prepared["idempotency_key"])["result"], result)
